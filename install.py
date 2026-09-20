#!/usr/bin/python3
"""Install Codex Bark notifications without replacing unrelated configuration."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
from urllib.parse import urlsplit

HOME = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
SCRIPT = HOME / 'hooks' / 'codex_note_reminder.py'
CONFIG = HOME / 'config.toml'
HOOKS = HOME / 'hooks.json'
STATE = HOME / 'codex-note-reminder-install.json'
SOURCE = Path(__file__).resolve().with_name('bark_notify.py')
START = '# BEGIN codex-note-reminder\n'
END = '# END codex-note-reminder\n'
MATCHER = r'(?:^|__|\.)(?:request_user_input(?:_async)?|send_user_message_async)$'


def safe(path):
    if path.is_symlink():
        raise ValueError('Refusing symlink: ' + str(path))


def read(path):
    safe(path)
    return path.read_text(encoding='utf-8') if path.exists() else ''


def write(path, data, mode=0o600):
    safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.codex-note-reminder-tmp')
    safe(temp)
    try:
        temp.write_text(data, encoding='utf-8')
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def backup(paths):
    existing = [p for p in paths if p.exists()]
    if not existing:
        return None
    root = HOME / 'backups' / 'codex-note-reminder'
    root.mkdir(parents=True, exist_ok=True)
    folder = root / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder.mkdir(mode=0o700)
    for p in existing:
        safe(p)
        shutil.copy2(p, folder / p.name)
    return folder


def managed_block(text):
    if (START in text) != (END in text) or text.count(START) > 1 or text.count(END) > 1:
        raise ValueError('Malformed managed block in config.toml')
    if START not in text:
        return text, False
    begin = text.index(START)
    end = text.index(END, begin) + len(END)
    return text[:begin] + text[end:], True


def other_notify(text):
    # A TOML key belongs to the root until the first table header. Ignore comments.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('['):
            break
        if re.match(r'^(?:notify|"notify"|\'notify\')\s*=', stripped):
            return True
    return False


def command(proxy):
    cmd = '/usr/bin/python3 ' + shlex.quote(str(SCRIPT))
    if proxy:
        cmd += ' --proxy ' + shlex.quote(proxy)
    return cmd


def hook_entries(cmd):
    leaf = {'type': 'command', 'command': cmd, 'timeout': 8}
    return {
        'PermissionRequest': {'hooks': [leaf]},
        'PreToolUse': {'matcher': MATCHER, 'hooks': [leaf]},
    }


def owned_command(value):
    if not isinstance(value, str):
        return False
    try:
        parts = shlex.split(value)
    except ValueError:
        return False
    return len(parts) >= 2 and parts[:2] == ['/usr/bin/python3', str(SCRIPT)]


def is_ours(group):
    return isinstance(group, dict) and any(
        isinstance(h, dict) and owned_command(h.get('command'))
        for h in group.get('hooks', []) if isinstance(group.get('hooks'), list)
    )


def load_hooks():
    raw = read(HOOKS)
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict):
        raise ValueError('hooks.json must contain an object with a hooks object')
    return data


def update_hooks(data, cmd, uninstall=False):
    hooks = data.setdefault('hooks', {})
    for event in ('PermissionRequest', 'PreToolUse'):
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError('Invalid hooks.json event: ' + event)
        # Keep other commands even if they share a hook group.
        revised = []
        for group in groups:
            if not is_ours(group):
                revised.append(group)
                continue
            rest = dict(group)
            rest['hooks'] = [h for h in group['hooks'] if not (
                isinstance(h, dict) and owned_command(h.get('command')))]
            if rest['hooks']:
                revised.append(rest)
        if not uninstall:
            revised.append(hook_entries(cmd)[event])
        if revised:
            hooks[event] = revised
        else:
            hooks.pop(event, None)
    return data


def validate_proxy(value):
    if not value:
        return None
    url = urlsplit(value)
    if url.scheme not in ('http', 'https', 'socks5', 'socks5h') or not url.hostname or url.username or url.password or '"' in value or '\n' in value:
        raise ValueError('Use a proxy URL without embedded credentials or quotes')
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--proxy', help='Explicit proxy URL; direct Bark access is the default')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise ValueError('This release supports macOS only')
    proxy = validate_proxy(args.proxy)
    for p in (HOME, HOME / 'hooks', CONFIG, HOOKS, SCRIPT, STATE):
        safe(p)
    state = json.loads(read(STATE)) if STATE.exists() else None
    if state is not None and state.get('script') != str(SCRIPT):
        raise ValueError('Invalid installation state')
    if args.uninstall and state is None:
        print('Nothing installed by codex-note-reminder.')
        return
    if not args.uninstall and SCRIPT.exists() and state is None:
        raise ValueError('Target script already exists without installation state')
    config, owned = managed_block(read(CONFIG))
    if not args.uninstall and other_notify(config):
        raise ValueError('Another notify command is configured; config.toml was not changed')
    if args.uninstall and not owned:
        raise ValueError('Managed notify block missing; refusing partial uninstall')
    hooks = load_hooks()
    new_hooks = update_hooks(hooks, command(proxy), args.uninstall)
    if args.uninstall:
        new_config = config
    else:
        if config and not config.endswith('\n'):
            config += '\n'
        new_config = START + 'notify = ["/usr/bin/python3", ' + json.dumps(str(SCRIPT))
        if proxy:
            new_config += ', "--proxy", ' + json.dumps(proxy)
        new_config += ']\n' + END + config
    prior = backup([CONFIG, HOOKS, SCRIPT, STATE])
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    if new_config or CONFIG.exists():
        write(CONFIG, new_config)
    if new_hooks.get('hooks') or HOOKS.exists():
        write(HOOKS, json.dumps(new_hooks, ensure_ascii=False, indent=2) + '\n')
    if args.uninstall:
        if SCRIPT.exists() and hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == state.get('sha256'):
            SCRIPT.unlink()
        STATE.unlink()
        print('Uninstalled. Bark key retained. Backup: ' + str(prior))
    else:
        SCRIPT.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(SOURCE, SCRIPT)
        os.chmod(SCRIPT, 0o700)
        digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        write(STATE, json.dumps({'script': str(SCRIPT), 'sha256': digest}, indent=2) + '\n')
        print('Installed. Run /hooks in Codex to trust the hooks. Backup: ' + str(prior))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        sys.exit(1)
