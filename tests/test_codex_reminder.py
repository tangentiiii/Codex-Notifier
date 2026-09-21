import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'codex'
PYTHON = '/usr/bin/python3'


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'codex'
        self.home.mkdir()
        self.env = dict(os.environ, CODEX_HOME=str(self.home), PYTHONDONTWRITEBYTECODE='1')

    def install(self, *args):
        return subprocess.run([PYTHON, str(ROOT / 'install.py'), *args], env=self.env,
                              capture_output=True, text=True)

    def module(self):
        with patch.dict(os.environ, CODEX_HOME=str(self.home)):
            spec = importlib.util.spec_from_file_location('reminder_test', ROOT / 'bark_notify.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module

    def test_install_merge_repeat_uninstall(self):
        (self.home / 'config.toml').write_text('model = "test"\n[features]\nhooks = true\n')
        (self.home / 'hooks.json').write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'other'}]}]}}))
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        # Upgrade from a release that installed the misleading approval hook.
        (self.home / 'hooks' / 'codex_note_reminder_cli.py').unlink()
        old_state = json.loads((self.home / 'codex-note-reminder-install.json').read_text())
        old_state.pop('launcher_sha256')
        old_state.pop('proxy')
        (self.home / 'codex-note-reminder-install.json').write_text(json.dumps(old_state))
        old_hooks = json.loads((self.home / 'hooks.json').read_text())
        old_hooks['hooks']['PermissionRequest'] = [
            {'hooks': [{'type': 'command', 'command': '/usr/bin/python3 "' +
                        str(self.home / 'hooks' / 'codex_note_reminder.py') + '"'}]}]
        (self.home / 'hooks.json').write_text(json.dumps(old_hooks))
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        config = (self.home / 'config.toml').read_text()
        self.assertEqual(config.count('# BEGIN codex-note-reminder'), 1)
        self.assertIn('model = "test"', config)
        hooks = json.loads((self.home / 'hooks.json').read_text())['hooks']
        self.assertNotIn('PermissionRequest', hooks)
        self.assertEqual(len(hooks['PreToolUse']), 1)
        self.assertEqual(hooks['Stop'][0]['hooks'][0]['command'], 'other')
        self.assertTrue((self.home / 'hooks' / 'codex_note_reminder_cli.py').exists())
        result = self.install('--uninstall')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('codex-note-reminder', (self.home / 'config.toml').read_text())
        self.assertEqual(json.loads((self.home / 'hooks.json').read_text())['hooks']['Stop'], hooks['Stop'])
        self.assertFalse((self.home / 'hooks' / 'codex_note_reminder.py').exists())
        self.assertFalse((self.home / 'hooks' / 'codex_note_reminder_cli.py').exists())
        self.assertTrue(any((self.home / 'backups' / 'codex-note-reminder').iterdir()))

    def test_existing_notify_unchanged(self):
        config = 'notify = ["other"]\n'
        (self.home / 'config.toml').write_text(config)
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.home / 'config.toml').read_text(), config)
        self.assertFalse((self.home / 'hooks.json').exists())

    def test_key_permissions_and_routing(self):
        m = self.module()
        with patch.object(m.getpass, 'getpass', return_value='fake_test_key'):
            m.setup_key()
        self.assertEqual(m.KEY_FILE.stat().st_mode & 0o777, 0o600)
        self.assertEqual(m.device_key(), 'fake_test_key')
        with patch.object(m, 'is_background', return_value=True), patch.object(m, 'send', return_value=True) as send:
            for payload, status in [
                ({'type': 'agent-turn-complete'}, '本轮回复已完成'),
                ({'hook_event_name': 'PreToolUse', 'tool_name': 'functions.request_user_input_async'}, '需要输入或选择'),
            ]:
                with patch.object(sys, 'argv', ['bark_notify.py', json.dumps(payload)]):
                    self.assertEqual(m.main(), 0)
                self.assertEqual(send.call_args.args[1], status)
        with patch.object(m, 'is_background', return_value=True), patch.object(m, 'send') as send:
            with patch.object(sys, 'argv', ['bark_notify.py', '{"hook_event_name":"PermissionRequest"}']):
                self.assertEqual(m.main(), 0)
            send.assert_not_called()
        with patch.object(m, 'is_background', return_value=False), patch.object(m, 'send') as send:
            with patch.object(sys, 'argv', ['bark_notify.py', '{"type":"agent-turn-complete"}']):
                m.main()
            send.assert_not_called()
        os.chmod(m.KEY_FILE, 0o644)
        with self.assertRaises(ValueError):
            m.device_key()

    def test_iterm_and_bark_mock(self):
        m = self.module()
        os.chmod(self.home, 0o700)
        m.KEY_FILE.write_text('fake_test_key\n')
        os.chmod(m.KEY_FILE, 0o600)
        with patch.dict(os.environ, ITERM_SESSION_ID='w0t0p0:ABC'):
            with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'foreground:ABC\n')):
                self.assertFalse(m.is_background())
            with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'foreground:OTHER\n')):
                self.assertTrue(m.is_background())
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'{"code":200}', b'')) as run:
            self.assertTrue(m.send({'cwd': '/tmp/project'}, 'test'))
            self.assertIn(b'fake_test_key', run.call_args.kwargs['input'])
            self.assertIn('--noproxy', run.call_args.args[0])
            self.assertNotIn('--proxy', run.call_args.args[0])
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'{"code":200}', b'')) as run:
            m.send({}, 'test', proxy='http://127.0.0.1:7890')
            self.assertIn('--proxy', run.call_args.args[0])

    def test_only_client_facing_approval_request_triggers_launcher(self):
        spec = importlib.util.spec_from_file_location('launcher_test', ROOT / 'codex_note_reminder_cli.py')
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        seen = []
        observer = launcher.FrameObserver(seen.append)

        def frame(message, opcode=1, fin=True):
            data = json.dumps(message).encode()
            return bytes([(0x80 if fin else 0) | opcode, len(data)]) + data

        auto = {'id': 6, 'method': 'item/autoApprovalReview/started', 'params': {'id': 'a'}}
        manual = {'id': 7, 'method': 'item/commandExecution/requestApproval', 'params': {'threadId': 't'}}
        resolved = {'method': 'serverRequest/resolved', 'params': {'requestId': 7}}
        observer.feed(frame(auto) + frame(resolved))
        self.assertEqual(seen, [])
        packed = frame(manual)
        observer.feed(packed[:3])
        observer.feed(packed[3:])
        self.assertEqual(seen, [manual])
        for method in ('item/fileChange/requestApproval', 'item/permissions/requestApproval'):
            request = {'id': method, 'method': method}
            observer.feed(frame(request))
            self.assertEqual(seen[-1], request)
        # A method name in ordinary model text is not a server request.
        observer.feed(frame({'method': 'item/commandExecution/requestApproval'}))
        self.assertEqual(len(seen), 3)
        class FakeNotifier:
            def __init__(self, background):
                self.background = background
                self.sent = []

            def is_background(self):
                return self.background

            def send(self, payload, status, proxy=None):
                self.sent.append((payload, status, proxy))

        front = FakeNotifier(False)
        launcher.notify_approval(front, None, '/tmp/project')
        self.assertEqual(front.sent, [])
        back = FakeNotifier(True)
        launcher.notify_approval(back, 'http://127.0.0.1:7890', '/tmp/project')
        self.assertEqual(back.sent, [({'cwd': '/tmp/project'}, '需要授权', 'http://127.0.0.1:7890')])

    def test_websocket_proxy_forwards_and_observes_approval(self):
        spec = importlib.util.spec_from_file_location('launcher_proxy_test', ROOT / 'codex_note_reminder_cli.py')
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        client, proxy_client = socket.socketpair()
        proxy_upstream, upstream = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(upstream.close)
        client.settimeout(2)
        upstream.settimeout(2)
        seen = []
        with patch.object(launcher, 'connect_unix', return_value=proxy_upstream):
            worker = threading.Thread(target=launcher.handle_client, args=(proxy_client, 1234, seen.append))
            worker.start()
            client.sendall(b'GET / HTTP/1.1\r\nUpgrade: websocket\r\nSec-WebSocket-Extensions: permessage-deflate\r\n\r\n')
            request = upstream.recv(4096)
            self.assertNotIn(b'Sec-WebSocket-Extensions:', request)
            approval = json.dumps({'id': 8, 'method': 'item/fileChange/requestApproval'}).encode()
            upstream.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n' +
                             bytes([0x81, len(approval)]) + approval)
            self.assertIn(b'101 Switching Protocols', client.recv(4096))
            upstream.shutdown(socket.SHUT_WR)
            client.shutdown(socket.SHUT_WR)
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(seen, [{'id': 8, 'method': 'item/fileChange/requestApproval'}])


if __name__ == '__main__':
    unittest.main()
