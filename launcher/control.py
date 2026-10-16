"""Start/stop this DreadOS installation without a packaged executable."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / '.venv-voice/Scripts/python.exe'
BOOT = ROOT / 'launcher/server_boot.py'
POWERSHELL = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


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


def listener(port):
    value = ps(f"$c=Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue; "
               "if($c){Get-CimInstance Win32_Process -Filter ('ProcessId=' + @($c)[0].OwningProcess) | "
               "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress}; exit 0")
    return json.loads(value) if value else None


def owned(process):
    # Match the complete executable and entry point, never just a process name.
    command = process.get('CommandLine') or ''
    executable = re.escape(str(PYTHON))
    entries = '|'.join(re.escape(str(path)) for path in (BOOT, ROOT / 'server.py'))
    return bool(re.fullmatch(r'"?' + executable + r'"?\s+(?:"?(?:' + entries + r')"?|server\.py)\s*',
                             command, re.IGNORECASE))


def run(action, port, no_browser):
    if action == 'start':
        if not ready(port):
            if listener(port):
                raise RuntimeError(f'Port {port} is occupied. No other application was stopped.')
            env = dict(os.environ, JARVIS_PORT=str(port))
            process = subprocess.Popen([str(PYTHON), str(BOOT)], cwd=ROOT, env=env,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
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
        return 'DreadOS is already stopped.'
    if not owned(process):
        raise RuntimeError('The process on this port does not match this DreadOS installation. It was left running.')
    pid = int(process['ProcessId'])
    ps(f'Stop-Process -Id {pid} -ErrorAction Stop')
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
        if args.action == 'stop' and not args.quiet:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'DreadOS', 0x40)
    except Exception as error:
        if sys.stderr:
            print(str(error), file=sys.stderr)
        if not args.quiet:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), 'DreadOS', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
