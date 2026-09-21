#!/usr/bin/python3
"""Send minimal Pi status notifications to a Bark device."""
from datetime import datetime, timezone
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

PI_HOME = Path(os.environ.get('PI_CODING_AGENT_DIR', str(Path.home() / '.pi' / 'agent'))).expanduser()
KEY_FILE = PI_HOME / 'bark_device_key'
CONFIG_FILE = PI_HOME / 'bark-reminder.json'
LOG_FILE = PI_HOME / 'bark_notify.log'
LEGACY_KEY_FILE = Path.home() / '.codex' / 'bark_device_key'
API_URL = 'https://api.day.app/push'
STATUSES = {
    'agent_settled': ('turn', '本轮回复已完成'),
    'ui_prompt_start': ('input', '需要输入或选择'),
}


def log_event(event, outcome):
    """Record fixed diagnostic labels only; never store payloads or credentials."""
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
        fd = os.open(LOG_FILE, flags, 0o600)
        try:
            stat = os.fstat(fd)
            if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
                return
            if stat.st_size > 65536:
                os.ftruncate(fd, 0)
            stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            os.write(fd, f'{stamp} {event} {outcome}\n'.encode('ascii'))
        finally:
            os.close(fd)
    except OSError:
        pass


def read_private_text(path):
    if path.is_symlink():
        raise ValueError('Refusing a symlink: ' + str(path))
    stat = path.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise ValueError(str(path) + ' must be owned by the current user and mode 0600')
    return path.read_text(encoding='utf-8')


def atomic_write(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Refusing a symlink: ' + str(path))
    fd, temp_path = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(value)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def device_key():
    try:
        key = read_private_text(KEY_FILE).strip()
    except FileNotFoundError:
        return None
    if not key or not re.fullmatch(r'[A-Za-z0-9_-]+', key):
        raise ValueError('Invalid Bark device key')
    return key


def validate_proxy(value):
    if not value:
        return None
    url = urlsplit(value)
    if (url.scheme not in ('http', 'https', 'socks5', 'socks5h') or not url.hostname
            or url.username or url.password or '\n' in value or '\r' in value):
        raise ValueError('Use a proxy URL without embedded credentials')
    return value


def configured_proxy():
    try:
        data = json.loads(read_private_text(CONFIG_FILE))
    except FileNotFoundError:
        return None
    if not isinstance(data, dict):
        raise ValueError('Invalid Bark reminder configuration')
    return validate_proxy(data.get('proxy'))


def project_name(payload):
    cwd = payload.get('cwd')
    if not isinstance(cwd, str) or not cwd:
        return 'Pi'
    name = Path(cwd.rstrip('/')).name or 'Pi'
    name = re.sub(r'[\x00-\x1f\x7f]', ' ', name).strip()
    return name[:60] or 'Pi'


def send(payload, status, timeout=6, proxy=None):
    key = device_key()
    if not key:
        return False
    body = json.dumps({
        'device_key': key,
        'title': 'Pi',
        'body': f'{project_name(payload)}：{status}',
        'group': 'Pi',
    }, ensure_ascii=False).encode('utf-8')
    curl = ['/usr/bin/curl', '--silent', '--show-error']
    proxy = proxy if proxy is not None else configured_proxy()
    if proxy:
        curl += ['--proxy', proxy]
    else:
        curl += ['--noproxy', 'api.day.app']
    result = subprocess.run(
        curl + [
            '--connect-timeout', str(min(timeout, 5)), '--max-time', str(timeout),
            '--request', 'POST', '--header', 'Content-Type: application/json; charset=utf-8',
            '--data-binary', '@-', API_URL],
        input=body, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout + 1, check=False)
    if result.returncode != 0:
        raise ConnectionError('curl_exit_' + str(result.returncode))
    response = json.loads(result.stdout)
    return response.get('code') == 200


def is_background():
    """Return whether the originating iTerm2 session is not the visible session."""
    session_id = os.environ.get('ITERM_SESSION_ID', '').rsplit(':', 1)[-1]
    if not session_id:
        return False
    try:
        result = subprocess.run(
            ['/usr/bin/osascript',
             '-e', 'tell application "iTerm2"',
             '-e', 'if frontmost is false then return "background"',
             '-e', 'return "foreground:" & (unique ID of current session of current window)',
             '-e', 'end tell'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=2, check=False)
        if result.returncode != 0:
            return False
        visible = result.stdout.strip()
        return visible.lower() != ('foreground:' + session_id).lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


def setup_key():
    key = getpass.getpass('Bark device key (input hidden): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', key):
        raise ValueError('Invalid Bark device key')
    atomic_write(KEY_FILE, key + '\n')
    print('Bark key saved with mode 0600.')


def migrate_codex_key():
    if KEY_FILE.exists():
        raise ValueError('Pi Bark key already exists; refusing to overwrite it')
    key = read_private_text(LEGACY_KEY_FILE).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', key):
        raise ValueError('Invalid legacy Bark device key')
    atomic_write(KEY_FILE, key + '\n')
    print('Bark key migrated to Pi with mode 0600.')


def setup_proxy(value):
    proxy = validate_proxy(value)
    atomic_write(CONFIG_FILE, json.dumps({'proxy': proxy}, indent=2) + '\n')
    print('Bark proxy saved with mode 0600.')


def clear_proxy():
    if CONFIG_FILE.is_symlink():
        raise ValueError('Refusing a symlink: ' + str(CONFIG_FILE))
    CONFIG_FILE.unlink(missing_ok=True)
    print('Bark proxy configuration cleared.')


def main():
    parser = argparse.ArgumentParser(description='Pi Bark status notifier')
    parser.add_argument('--setup-key', action='store_true')
    parser.add_argument('--migrate-codex-key', action='store_true')
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--setup-proxy', metavar='URL')
    parser.add_argument('--clear-proxy', action='store_true')
    parser.add_argument('--proxy', help='Override the saved proxy for this invocation')
    args = parser.parse_args() if sys.argv[1:2] and sys.argv[1].startswith('--') else None
    if args and args.setup_key:
        setup_key()
        return 0
    if args and args.migrate_codex_key:
        migrate_codex_key()
        return 0
    if args and args.setup_proxy:
        setup_proxy(args.setup_proxy)
        return 0
    if args and args.clear_proxy:
        clear_proxy()
        return 0
    if args and args.test:
        if not device_key():
            print('Bark key is missing. Run --setup-key first.', file=sys.stderr)
            return 1
        try:
            accepted = send({'cwd': os.getcwd()}, '测试通知', timeout=15, proxy=args.proxy)
        except (TimeoutError, subprocess.TimeoutExpired, ConnectionError):
            print('Bark connection timed out or failed. Check network and proxy, then retry.', file=sys.stderr)
            return 1
        except (OSError, ValueError, json.JSONDecodeError):
            print('Bark response or local configuration could not be read.', file=sys.stderr)
            return 1
        if accepted:
            print('Test notification accepted by Bark.')
            return 0
        print('Bark did not accept the test notification. Check the device key.', file=sys.stderr)
        return 1
    try:
        payload = json.loads(sys.argv[1] if args is None and len(sys.argv) > 1 else sys.stdin.read())
        if not isinstance(payload, dict):
            return 0
        route = STATUSES.get(payload.get('event'))
        if route:
            label, status = route
            log_event(label, 'invoked')
            if is_background():
                log_event(label, 'background')
                try:
                    accepted = send(payload, status)
                    log_event(label, 'accepted' if accepted else 'rejected_or_missing_key')
                except Exception as exc:
                    outcome = str(exc) if isinstance(exc, ConnectionError) else type(exc).__name__
                    log_event(label, 'error_' + outcome)
            else:
                log_event(label, 'foreground_suppressed')
    except Exception:
        # Notification failures must never interrupt Pi.
        pass
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        sys.exit(1)
