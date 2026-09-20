#!/usr/bin/python3
"""Run Codex TUI through a local app-server proxy to observe real approval prompts."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

# Server-to-client requests represent prompts shown to the human after auto-review.
APPROVAL_METHODS = frozenset((
    'item/commandExecution/requestApproval',
    'item/fileChange/requestApproval',
    'item/permissions/requestApproval',
))
MAX_MESSAGE = 1024 * 1024


def notifier_module():
    sibling = Path(__file__).with_name('codex_note_reminder.py')
    if not sibling.exists():
        sibling = Path(__file__).with_name('bark_notify.py')
    spec = importlib.util.spec_from_file_location('codex_note_reminder_runtime', sibling)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_headers(sock):
    data = bytearray()
    while b'\r\n\r\n' not in data:
        part = sock.recv(4096)
        if not part or len(data) + len(part) > 65536:
            raise ConnectionError('Invalid WebSocket handshake')
        data.extend(part)
    end = data.index(b'\r\n\r\n') + 4
    return bytes(data[:end]), bytes(data[end:])


def remove_extensions(headers):
    # Disable compression so approval JSON remains directly inspectable.
    return b'\r\n'.join(line for line in headers.split(b'\r\n')
                       if not line.lower().startswith(b'sec-websocket-extensions:'))


class FrameObserver:
    def __init__(self, callback):
        self.callback = callback
        self.buffer = bytearray()
        self.message = bytearray()
        self.text = False
        self.skip = 0

    def feed(self, chunk):
        self.buffer.extend(chunk)
        while self.buffer:
            if self.skip:
                amount = min(self.skip, len(self.buffer))
                del self.buffer[:amount]
                self.skip -= amount
                continue
            if len(self.buffer) < 2:
                return
            first, second = self.buffer[:2]
            length = second & 0x7f
            header = 2
            if length == 126:
                if len(self.buffer) < 4:
                    return
                length = struct.unpack('!H', self.buffer[2:4])[0]
                header = 4
            elif length == 127:
                if len(self.buffer) < 10:
                    return
                length = struct.unpack('!Q', self.buffer[2:10])[0]
                header = 10
            masked = bool(second & 0x80)
            size = header + (4 if masked else 0) + length
            if length > MAX_MESSAGE:
                self.text = False
                self.message.clear()
                self.skip = size
                continue
            if len(self.buffer) < size:
                return
            frame = bytes(self.buffer[header + (4 if masked else 0):size])
            del self.buffer[:size]
            if masked:
                continue  # App-server to TUI frames must be unmasked.
            opcode = first & 0x0f
            if opcode == 1:
                self.message.clear()
                self.text = True
            elif opcode != 0:
                continue
            if not self.text:
                continue
            if len(self.message) + len(frame) > MAX_MESSAGE:
                self.text = False
                self.message.clear()
                continue
            self.message.extend(frame)
            if first & 0x80:
                try:
                    value = json.loads(self.message)
                    if isinstance(value, dict) and value.get('method') in APPROVAL_METHODS and 'id' in value:
                        self.callback(value)
                except (UnicodeDecodeError, ValueError):
                    pass
                finally:
                    self.text = False
                    self.message.clear()


def relay(source, target, observer=None):
    try:
        while True:
            chunk = source.recv(65536)
            if not chunk:
                break
            target.sendall(chunk)
            if observer:
                observer.feed(chunk)
    except OSError:
        pass
    finally:
        try:
            target.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def connect_unix(path):
    connection = socket.socket(socket.AF_UNIX)
    connection.connect(str(path))
    return connection


def handle_client(client, upstream_path, callback):
    try:
        with client, connect_unix(upstream_path) as upstream:
            request, extra = read_headers(client)
            upstream.sendall(remove_extensions(request) + extra)
            response, extra = read_headers(upstream)
            client.sendall(response + extra)
            if b' 101 ' not in response.split(b'\r\n', 1)[0]:
                return
            observer = FrameObserver(callback)
            if extra:
                observer.feed(extra)
            outbound = threading.Thread(target=relay, args=(client, upstream), daemon=True)
            outbound.start()
            relay(upstream, client, observer)
            outbound.join(timeout=1)
    except (OSError, ConnectionError):
        try:
            client.close()
        except OSError:
            pass


def serve(listener, upstream_path, callback, stop):
    listener.settimeout(0.5)
    while not stop.is_set():
        try:
            client, _ = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=handle_client, args=(client, upstream_path, callback), daemon=True).start()


def wait_for_server(process, path):
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError('Codex app-server exited before startup')
        try:
            with connect_unix(path):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError('Codex app-server did not start')


def notify_approval(notifier, proxy, cwd):
    if not notifier.is_background():
        return
    try:
        notifier.send({'cwd': cwd}, '需要授权', proxy=proxy)
    except Exception:
        pass  # Never interrupt an approval prompt.


def main():
    parser = argparse.ArgumentParser(description='Launch Codex with accurate Bark approval alerts')
    parser.add_argument('--bark-proxy', help='Override the Bark proxy configured during installation')
    parser.add_argument('codex_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    forwarded = args.codex_args[1:] if args.codex_args[:1] == ['--'] else args.codex_args
    if any(item == '--remote' or item.startswith('--remote=') for item in forwarded):
        parser.error('--remote is managed by this launcher')
    codex = shutil.which('codex')
    if not codex:
        parser.error('codex CLI is not on PATH')
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
    state = home / 'codex-note-reminder-install.json'
    configured_proxy = None
    if state.exists():
        configured_proxy = json.loads(state.read_text(encoding='utf-8')).get('proxy')
    proxy = args.bark_proxy or configured_proxy
    notifier = notifier_module()
    seen = set()
    seen_lock = threading.Lock()

    def on_approval(request):
        params = request.get('params') or {}
        if not isinstance(params, dict):
            params = {}
        request_id = (params.get('threadId'), params.get('turnId'), request.get('id'))
        with seen_lock:
            if request_id in seen:
                return
            if len(seen) >= 4096:
                seen.clear()
            seen.add(request_id)
        request_cwd = params.get('cwd')
        if not isinstance(request_cwd, str) or not request_cwd:
            request_cwd = os.getcwd()
        threading.Thread(target=notify_approval,
                         args=(notifier, proxy, request_cwd), daemon=True).start()

    with tempfile.TemporaryDirectory(prefix='codex-reminder-', dir='/private/tmp') as private_dir:
        upstream_path = Path(private_dir) / 'up.sock'
        proxy_path = Path(private_dir) / 'proxy.sock'
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(proxy_path))
            listener.listen(8)
            server = subprocess.Popen([codex, 'app-server', '--listen', 'unix://' + str(upstream_path)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            stop = threading.Event()
            try:
                wait_for_server(server, upstream_path)
                thread = threading.Thread(target=serve, args=(listener, upstream_path, on_approval, stop), daemon=True)
                thread.start()
                return subprocess.call([codex, '--remote', 'unix://' + str(proxy_path)] + forwarded)
            finally:
                stop.set()
                server.terminate()
                try:
                    server.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print('Codex reminder launcher: ' + str(exc), file=sys.stderr)
        sys.exit(1)
