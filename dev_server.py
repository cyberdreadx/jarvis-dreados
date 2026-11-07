"""One managed project dev server (npm run dev) for Build's live Preview.

The user starts it explicitly from Build. It runs the project's own package.json
script with the user's normal permissions, is stopped with its whole process tree,
and only loopback URLs it prints are ever shown or captured.
"""
import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Read by preview_capture (OpenCode's MCP process) so the AI can screenshot the live app.
STATE_FILE = ROOT / 'data/opencode/dev-server.json'
SCRIPTS = ('dev', 'start', 'serve')
URL_RE = re.compile(r'https?://(?:localhost|127\.0\.0\.1|\[::1\]):(\d{2,5})(?:/[^\s\x1b\'"]*)?')
ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')
WINDOWS = os.name == 'nt'

_lock = threading.Lock()
_state = {'gen': 0, 'project': None, 'root': None, 'proc': None, 'status': 'stopped', 'url': None,
          'script': None, 'error': '', 'started': 0.0, 'log': deque(maxlen=400)}


def script_for(root):
    package = Path(root) / 'package.json'
    if not package.is_file():
        raise ValueError('This project has no package.json. Dev servers are for npm projects such as Vite or React; '
                         'plain HTML projects already preview live.')
    try:
        scripts = json.loads(package.read_text(encoding='utf-8')).get('scripts') or {}
    except (ValueError, OSError, AttributeError):
        raise ValueError('package.json could not be read as JSON.') from None
    for name in SCRIPTS:
        if isinstance(scripts.get(name), str) and scripts[name].strip():
            return name
    raise ValueError('package.json has no "dev", "start" or "serve" script to run.')


def _kill(proc):
    if not proc or proc.poll() is not None:
        return
    try:
        if WINDOWS:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass


def _write_state():
    try:
        if _state['status'] == 'running' and _state['url']:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps({'root': _state['root'], 'project': _state['project'], 'url': _state['url']}))
        else:
            STATE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _spawn(cmd, root):
    env = {**os.environ, 'BROWSER': 'none', 'NO_COLOR': '1', 'FORCE_COLOR': '0'}
    extra = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if WINDOWS else {'start_new_session': True}
    return subprocess.Popen(cmd, cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', **extra)


def _pump(proc, gen, find_url):
    for raw in proc.stdout:
        line = ANSI_RE.sub('', raw.rstrip())
        with _lock:
            if gen != _state['gen']:
                return
            if line.strip():
                _state['log'].append(line[:500])
            if find_url and not _state['url']:
                found = URL_RE.search(line)
                if found:
                    _state.update(url=found.group(0).rstrip('/') + '/', status='running')
                    _write_state()


def _run(gen, root, npm, script):
    try:
        if not (Path(root) / 'node_modules').is_dir():
            with _lock:
                if gen != _state['gen']:
                    return
                _state['log'].append('$ npm install')
                proc = _state['proc'] = _spawn([npm, 'install'], root)
            _pump(proc, gen, False)
            if proc.wait() != 0:
                with _lock:
                    if gen == _state['gen']:
                        _state.update(status='crashed', error='npm install failed. See the log.', proc=None)
                return
        with _lock:
            if gen != _state['gen']:
                return
            _state['log'].append(f'$ npm run {script}')
            _state['status'] = 'starting'
            proc = _state['proc'] = _spawn([npm, 'run', script], root)
        _pump(proc, gen, True)
        code = proc.wait()
        with _lock:
            if gen == _state['gen']:
                _state.update(status='crashed' if code else 'stopped', proc=None,
                              error=f'The dev server exited (code {code}). See the log.' if code else '')
                _write_state()
    except OSError as error:
        with _lock:
            if gen == _state['gen']:
                _state.update(status='crashed', error=f'Could not start npm ({error}).', proc=None)


def start(root, project):
    root = str(Path(root).resolve())
    script = script_for(root)
    npm = shutil.which('npm')
    if not npm:
        raise ValueError('Node.js is not installed (npm was not found). Install Node.js LTS, then try again.')
    with _lock:
        if _state['project'] == project and _state['status'] in ('installing', 'starting', 'running'):
            return _status_locked()
        old = _state['proc']
        _state['gen'] += 1
        gen = _state['gen']
        _state['log'].clear()
        _state.update(project=project, root=root, proc=None, url=None, script=script, error='', started=time.time(),
                      status='installing' if not (Path(root) / 'node_modules').is_dir() else 'starting')
        _write_state()
    _kill(old)
    threading.Thread(target=_run, args=(gen, root, npm, script), daemon=True).start()
    return status()


def stop():
    with _lock:
        proc = _state['proc']
        _state['gen'] += 1
        _state.update(proc=None, status='stopped', url=None, error='')
        _write_state()
    _kill(proc)
    return status()


def _status_locked():
    return {'project': _state['project'], 'status': _state['status'], 'url': _state['url'], 'script': _state['script'],
            'error': _state['error'], 'uptime': int(time.time() - _state['started']) if _state['started'] else 0,
            'log': '\n'.join(list(_state['log'])[-120:])}


def status():
    with _lock:
        return _status_locked()


def registered_url(root):
    """Dev URL for this project if its server is running (used by the AI screenshot tool)."""
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None
    if Path(data.get('root', '')).resolve() != Path(root).resolve():
        return None
    url = data.get('url') or ''
    return url if URL_RE.fullmatch(url.rstrip('/')) or URL_RE.match(url) else None


def _shutdown():
    # Only the process that started a server may stop it or clear the shared state file.
    # Other importers (the screenshot tool, tests) must leave a running server alone.
    with _lock:
        owned = _state['proc'] is not None or _state['status'] in ('installing', 'starting', 'running')
    if owned:
        stop()


atexit.register(_shutdown)
