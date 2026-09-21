import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PI_ROOT = ROOT / 'pi'


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'pi-agent'
        self.home.mkdir()

    def module(self):
        with patch.dict(os.environ, PI_CODING_AGENT_DIR=str(self.home)):
            spec = importlib.util.spec_from_file_location('reminder_test', PI_ROOT / 'bark_notify.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module

    def test_key_permissions_and_routing(self):
        m = self.module()
        with patch.object(m.getpass, 'getpass', return_value='fake_test_key'):
            m.setup_key()
        self.assertEqual(m.KEY_FILE.stat().st_mode & 0o777, 0o600)
        self.assertEqual(m.device_key(), 'fake_test_key')
        with patch.object(m, 'is_background', return_value=True), patch.object(m, 'send', return_value=True) as send:
            for event, status in [
                ('agent_settled', '本轮回复已完成'),
                ('ui_prompt_start', '需要输入或选择'),
            ]:
                with patch.object(sys, 'argv', ['bark_notify.py', json.dumps({'event': event, 'cwd': '/tmp/demo'})]):
                    self.assertEqual(m.main(), 0)
                self.assertEqual(send.call_args.args[1], status)
        with patch.object(m, 'is_background', return_value=False), patch.object(m, 'send') as send:
            with patch.object(sys, 'argv', ['bark_notify.py', '{"event":"agent_settled"}']):
                m.main()
            send.assert_not_called()
        os.chmod(m.KEY_FILE, 0o644)
        with self.assertRaises(ValueError):
            m.device_key()

    def test_migrate_legacy_key_without_overwrite(self):
        m = self.module()
        legacy = Path(self.temp.name) / 'legacy-key'
        legacy.write_text('legacy_test_key\n')
        os.chmod(legacy, 0o600)
        m.LEGACY_KEY_FILE = legacy
        m.migrate_codex_key()
        self.assertEqual(m.device_key(), 'legacy_test_key')
        with self.assertRaises(ValueError):
            m.migrate_codex_key()

    def test_iterm_bark_and_proxy_mock(self):
        m = self.module()
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
        m.setup_proxy('http://127.0.0.1:7890')
        self.assertEqual(m.CONFIG_FILE.stat().st_mode & 0o777, 0o600)
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'{"code":200}', b'')) as run:
            m.send({}, 'test')
            self.assertIn('--proxy', run.call_args.args[0])
            self.assertIn('http://127.0.0.1:7890', run.call_args.args[0])
        with self.assertRaises(ValueError):
            m.setup_proxy('http://user:secret@127.0.0.1:7890')

    def test_typescript_extension_registers_native_pi_events(self):
        script = r'''
import { registerReminder } from "./pi/extensions/pi-bark-reminder.ts";
const handlers = new Map();
const pi = { on(name, handler) { handlers.set(name, handler); } };
const calls = [];
registerReminder(pi, (event, cwd) => calls.push([event, cwd]));
await handlers.get("agent_settled")({}, { cwd: "/tmp/one" });
await handlers.get("ui_prompt_start")({}, { cwd: "/tmp/two" });
if (handlers.size !== 2 || JSON.stringify(calls) !== JSON.stringify([
  ["agent_settled", "/tmp/one"],
  ["ui_prompt_start", "/tmp/two"],
])) process.exit(1);
'''
        result = subprocess.run(
            ['node', '--experimental-strip-types', '--input-type=module', '--eval', script],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_package_manifest_points_to_extension(self):
        manifest = json.loads((ROOT / 'package.json').read_text())
        self.assertIn('pi-package', manifest['keywords'])
        for relative in manifest['pi']['extensions']:
            self.assertTrue((ROOT / relative).is_file())


if __name__ == '__main__':
    unittest.main()
