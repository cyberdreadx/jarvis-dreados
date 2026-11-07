"""Start/stop this DreadOS installation without a packaged executable."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = os.name == 'nt'
BOOT = ROOT / 'launcher/server_boot.py'
if WINDOWS:
    PYTHON = ROOT / '.venv-voice/Scripts/python.exe'
    POWERSHELL = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    HIDDEN = {'creationflags': subprocess.CREATE_NO_WINDOW}
else:
    # macOS: use the voice venv when it exists, otherwise the Python 3 that started this script.
    VENV = ROOT / '.venv-voice/bin/python'
    PYTHON = VENV if VENV.is_file() else Path(sys.executable)
    HIDDEN = {'start_new_session': True}  # keeps running after the Terminal window closes


def ps(command):
    result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
    if result.returncode:
        raise RuntimeError('Windows could not inspect or stop DreadOS. ' + result.stderr.strip())
    return result.stdout.strip()


def ready(port):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/api/status', timeout=2) as response:
            data = json.load(response)
            return all(key in data for key in ('token', 'platform', 'providers'))
    except Exception:
        return False


def posix_listener(port):
    found = subprocess.run(['/usr/sbin/lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-t'],
                           capture_output=True, text=True, timeout=20)
    pids = [int(x) for x in found.stdout.split() if x.isdigit()]
    if not pids:
        return None
    command = subprocess.run(['/bin/ps', '-o', 'command=', '-p', str(pids[0])],
                             capture_output=True, text=True, timeout=20).stdout.strip()
    return {'ProcessId': pids[0], 'CommandLine': command}


def listener(port):
    if not WINDOWS:
        return posix_listener(port)
    # Windows can list stale or unattributed listeners as PID 0; prefer a real owner when there is one.
    value = ps(f"$c=@(Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue); "
               "if($c){$o=@($c | Where-Object OwningProcess -gt 0); "
               "if($o){Get-CimInstance Win32_Process -Filter ('ProcessId=' + $o[0].OwningProcess) | "
               "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress} "
               "else{'{\"ProcessId\":0,\"CommandLine\":null}'}}; exit 0")
    return json.loads(value) if value else None


def port_free(port):
    """True if this port can actually be bound. Windows' connection table can keep PID-0
    'Listen' ghosts after a process exits, so trying the port is the reliable check."""
    import socket
    for _ in range(20):  # a just-stopped server can take a moment to release it
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return True
            except OSError:
                pass
        time.sleep(.25)
    return False


def own_processes():
    """This installation's running server processes, matched on the exact command line."""
    if WINDOWS:
        value = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                   "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress; exit 0")
        found = json.loads(value) if value else []
    else:
        out = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,command='], capture_output=True, text=True, timeout=20).stdout
        found = [{'ProcessId': int(a), 'ParentProcessId': int(b), 'CommandLine': c}
                 for a, b, c in (line.strip().split(None, 2) for line in out.splitlines() if line.strip().count(' ') >= 2)]
    found = [found] if isinstance(found, dict) else found
    return [p for p in found if owned(p)]


def stop_pids(pids):
    for pid in pids:
        if WINDOWS:
            # /T also ends what the server started (OpenCode, MCP servers) so none is left running stale.
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True, timeout=20, **HIDDEN)
        else:
            os.kill(pid, signal.SIGTERM)


def owned(process):
    # Match the complete executable and entry point, never just a process name.
    command = process.get('CommandLine') or ''
    entries = '|'.join(re.escape(str(path)) for path in (BOOT, ROOT / 'server.py'))
    if not WINDOWS:
        # macOS ps shows the interpreter as launched, which may be a framework path, so match on the entry point.
        return bool(re.fullmatch(r'.*python[\d.]*\s+(?:' + entries + r')\s*', command, re.IGNORECASE))
    executable = re.escape(str(PYTHON))
    return bool(re.fullmatch(r'"?' + executable + r'"?\s+(?:"?(?:' + entries + r')"?|server\.py)\s*',
                             command, re.IGNORECASE))


def run(action, port, no_browser):
    if action == 'start':
        if not ready(port):
            if not port_free(port):
                raise RuntimeError(f'Port {port} is occupied. No other application was stopped.')
            env = dict(os.environ, JARVIS_PORT=str(port))
            process = subprocess.Popen([str(PYTHON), str(BOOT)], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **HIDDEN)
            for _ in range(90):
                if ready(port):
                    break
                if process.poll() is not None:
                    raise RuntimeError('Startup failed. See data/launcher-server.log.')
                time.sleep(.5)
            else:
                raise RuntimeError('Startup is taking too long. See data/launcher-server.log.')
        if not no_browser:
            webbrowser.open(f'http://127.0.0.1:{port}/')
        return 'DreadOS is running.'
    process = listener(port)
    if not process:
        if not ready(port):
            return 'DreadOS is already stopped.'
        process = {'ProcessId': 0, 'CommandLine': None}  # answering, but Windows didn't list its listener
    if owned(process):
        pids = [int(process['ProcessId'])]
    elif not process.get('ProcessId') and ready(port):
        # Windows couldn't name the port's owner (PID 0), but the port answers as DreadOS. Stop this
        # installation's own server, found by exact command line; the venv launcher is the root.
        mine = own_processes()
        ids = {p['ProcessId'] for p in mine}
        pids = [int(p['ProcessId']) for p in mine if p.get('ParentProcessId') not in ids]
        if not pids:
            raise RuntimeError('DreadOS is answering on this port, but its process could not be identified. It was left running.')
    else:
        raise RuntimeError('The process on this port does not match this DreadOS installation. It was left running.')
    stop_pids(pids)
    for _ in range(20):
        if not ready(port):
            return 'DreadOS is stopped. Saved chats and files remain on disk.'
        time.sleep(.25)
    raise RuntimeError('DreadOS has not stopped yet.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop'])
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Invalid port')
    try:
        message = run(args.action, args.port, args.no_browser)
        if sys.stdout:
            print(message)
        if args.action == 'stop' and not args.quiet and WINDOWS:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'DreadOS', 0x40)
    except Exception as error:
        if sys.stderr:
            print(str(error), file=sys.stderr)
        if not args.quiet and WINDOWS:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), 'DreadOS', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
