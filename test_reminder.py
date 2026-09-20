import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
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
        for _ in range(2):
            result = self.install()
            self.assertEqual(result.returncode, 0, result.stderr)
        config = (self.home / 'config.toml').read_text()
        self.assertEqual(config.count('# BEGIN codex-note-reminder'), 1)
        self.assertIn('model = "test"', config)
        hooks = json.loads((self.home / 'hooks.json').read_text())['hooks']
        self.assertEqual(len(hooks['PermissionRequest']), 1)
        self.assertEqual(len(hooks['PreToolUse']), 1)
        self.assertEqual(hooks['Stop'][0]['hooks'][0]['command'], 'other')
        result = self.install('--uninstall')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('codex-note-reminder', (self.home / 'config.toml').read_text())
        self.assertEqual(json.loads((self.home / 'hooks.json').read_text())['hooks']['Stop'], hooks['Stop'])
        self.assertFalse((self.home / 'hooks' / 'codex_note_reminder.py').exists())
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
                ({'hook_event_name': 'PermissionRequest'}, '需要授权'),
                ({'hook_event_name': 'PreToolUse', 'tool_name': 'functions.request_user_input_async'}, '需要输入或选择'),
            ]:
                with patch.object(sys, 'argv', ['bark_notify.py', json.dumps(payload)]):
                    self.assertEqual(m.main(), 0)
                self.assertEqual(send.call_args.args[1], status)
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


if __name__ == '__main__':
    unittest.main()
