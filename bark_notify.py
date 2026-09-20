#!/usr/bin/python3
"""Send minimal Codex status notifications to a Bark device."""
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

CODEX_HOME = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
KEY_FILE = CODEX_HOME / 'bark_device_key'
LOG_FILE = CODEX_HOME / 'bark_notify.log'
API_URL = 'https://api.day.app/push'
INPUT_TOOL = re.compile(r'(?:^|__|\.)((?:request_user_input(?:_async)?)|(?:send_user_message_async))$')



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


def device_key():
    try:
        if KEY_FILE.is_symlink():
            raise ValueError('Refusing a symlink for the Bark key file')
        stat = KEY_FILE.stat()
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise ValueError('Bark key file must be owned by the current user and mode 0600')
        key = KEY_FILE.read_text(encoding='utf-8').strip()
        if not key or not re.fullmatch(r'[A-Za-z0-9_-]+', key):
            raise ValueError('Invalid Bark device key')
        return key
    except FileNotFoundError:
        return None


def project_name(payload):
    cwd = payload.get('cwd')
    if not isinstance(cwd, str) or not cwd:
        return 'Codex'
    name = Path(cwd.rstrip('/')).name or 'Codex'
    # Project names are the only event-derived text allowed in a notification.
    name = re.sub(r'[\x00-\x1f\x7f]', ' ', name).strip()
    return name[:60] or 'Codex'


def send(payload, status, timeout=6, proxy=None):
    key = device_key()
    if not key:
        return False
    body = json.dumps({
        'device_key': key,
        'title': 'Codex',
        'body': f'{project_name(payload)}：{status}',
        'group': 'Codex',
    }, ensure_ascii=False).encode('utf-8')
    curl = ['/usr/bin/curl', '--silent', '--show-error']
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
    """Return whether the originating iTerm session is not the visible session."""
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
    KEY_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if KEY_FILE.is_symlink():
        raise ValueError('Refusing a symlink for the Bark key file')
    key = getpass.getpass('Bark device key (input hidden): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', key):
        raise ValueError('Invalid Bark device key')
    fd, path = tempfile.mkstemp(prefix='.bark_device_key.', dir=KEY_FILE.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(key + '\n')
        os.replace(path, KEY_FILE)
    finally:
        if os.path.exists(path):
            os.unlink(path)
    print('Bark key saved with mode 0600.')


def main():
    parser = argparse.ArgumentParser(description='Codex Bark status notifier')
    parser.add_argument('--setup-key', action='store_true')
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--proxy', help='Explicit HTTP(S) proxy URL')
    args = parser.parse_args() if sys.argv[1:2] and sys.argv[1].startswith('--') else None
    if args and args.setup_key:
        setup_key()
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
        except (OSError, ValueError):
            print('Bark response could not be read. Retry after checking network.', file=sys.stderr)
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
        event = status = None
        if payload.get('type') == 'agent-turn-complete':
            event, status = 'turn', '本轮回复已完成'
        elif (payload.get('hook_event_name') == 'PreToolUse'
              and INPUT_TOOL.search(str(payload.get('tool_name', '')))):
            event, status = 'input', '需要输入或选择'
        if status:
            log_event(event, 'invoked')
            if is_background():
                log_event(event, 'background')
                try:
                    accepted = send(payload, status, proxy=args.proxy if args else None)
                    log_event(event, 'accepted' if accepted else 'rejected_or_missing_key')
                except Exception as exc:
                    log_event(event, 'error_' + (str(exc) if isinstance(exc, ConnectionError) else type(exc).__name__))
            else:
                log_event(event, 'foreground_suppressed')
    except Exception:
        # Notification failure must never interrupt Codex or change an approval decision.
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
