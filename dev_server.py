"""One managed project dev server (npm run dev) for Build's live Preview.

The user starts it explicitly from Build. It runs the project's own package.json
script with the user's normal permissions, is stopped with its whole process tree,
and only loopback URLs it prints are ever shown or captured. With the project's sandbox on,
npm runs inside its Docker container instead and the printed URL is mapped to the published port.
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
import sandbox

ROOT = Path(__file__).resolve().parent
# Read by preview_capture (OpenCode's MCP process) so the AI can screenshot the live app.
STATE_FILE = ROOT / 'data/opencode/dev-server.json'
SCRIPTS = ('dev', 'start', 'serve')
URL_RE = re.compile(r'https?://(?:localhost|127\.0\.0\.1|\[::1\]):(\d{2,5})(?:/[^\s\x1b\'"]*)?')
ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')
WINDOWS = os.name == 'nt'

_lock = threading.Lock()
_state = {'gen': 0, 'project': None, 'root': None, 'proc': None, 'status': 'stopped', 'url': None, 'sandboxed': False,
          'script': None, 'error': '', 'started': 0.0, 'log': deque(maxlen=400)}


def _script_text(root, script):
    try:
        return str(json.loads((Path(root) / 'package.json').read_text(encoding='utf-8'))['scripts'][script])
    except (OSError, ValueError, KeyError, TypeError):
        return ''


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


def _npm(root, npm, args, sandboxed):
    if sandboxed:
        return _spawn(sandbox.dev_command(root, args, _script_text(root, args[-1]) if args[0] == 'run' else ''), root)
    return _spawn([npm, *args], root)


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
                    url = found.group(0).rstrip('/') + '/'
                    if _state['sandboxed']:
                        mapped = sandbox.host_url(_state['root'], url)
                        if not mapped:
                            _state['log'].append(f'Port {found.group(1)} is not one the sandbox publishes '
                                                 f'({", ".join(map(str, sandbox.DEV_PORTS))}). Set the dev server to one of them.')
                            continue
                        url = mapped
                    _state.update(url=url, status='running')
                    _write_state()


NATIVE_SCOPES = ('@esbuild', '@rollup', '@swc', '@next', '@parcel', '@tailwindcss', '@biomejs')
OS_TOKENS = ('win32', 'linux', 'darwin')


def modules_platforms(root):
    """Operating systems the installed native packages were built for (empty for pure-JS installs)."""
    found = set()
    modules = Path(root) / 'node_modules'
    for scope in NATIVE_SCOPES:
        try:
            names = [entry.name for entry in (modules / scope).iterdir()]
        except OSError:
            continue
        found.update(token for name in names for token in OS_TOKENS if token in name)
    return found


def _target_os(sandboxed):
    return 'linux' if sandboxed else ('win32' if WINDOWS else os.uname().sysname.lower())


def _run(gen, root, npm, script, sandboxed=False):
    try:
        modules = Path(root) / 'node_modules'
        built_for = modules_platforms(root)
        if modules.is_dir() and built_for and _target_os(sandboxed) not in built_for:
            # Packages installed on Windows can't run in the Linux sandbox (and vice versa): reinstall.
            with _lock:
                if gen != _state['gen']:
                    return
                _state['status'] = 'installing'
                _state['log'].append(f'node_modules was installed for {"/".join(sorted(built_for))}; '
                                     f'reinstalling for {"the Linux sandbox" if sandboxed else "this PC"}…')
            shutil.rmtree(modules, ignore_errors=True)
            if modules.exists():
                raise OSError('could not remove the old node_modules folder; close programs using it and retry')
        if not (Path(root) / 'node_modules').is_dir():
            with _lock:
                if gen != _state['gen']:
                    return
                _state['log'].append('$ npm install')
                proc = _state['proc'] = _npm(root, npm, ['install'], sandboxed)
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
            proc = _state['proc'] = _npm(root, npm, ['run', script], sandboxed)
        _pump(proc, gen, True)
        code = proc.wait()
        with _lock:
            if gen == _state['gen']:
                _state.update(status='crashed' if code else 'stopped', proc=None,
                              error=f'The dev server exited (code {code}). See the log.' if code else '')
                _write_state()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        with _lock:
            if gen == _state['gen']:
                _state.update(status='crashed', error=f'Could not start npm ({error}).', proc=None)


def start(root, project):
    root = str(Path(root).resolve())
    script = script_for(root)
    sandboxed = sandbox.setting(root) is not None
    if sandboxed and not sandbox.setting(root)['network']:
        raise ValueError('The sandbox has internet turned off, which also cuts the preview connection. '
                         'Turn sandbox internet on to run the dev server.')
    npm = shutil.which('npm')
    if not npm and not sandboxed:
        raise ValueError('Node.js is not installed (npm was not found). Install Node.js LTS, then try again.')
    with _lock:
        if _state['project'] == project and _state['status'] in ('installing', 'starting', 'running'):
            return _status_locked()
        old = _state['proc']
        _state['gen'] += 1
        gen = _state['gen']
        _state['log'].clear()
        old_root, was_sandboxed = _state['root'], _state['sandboxed']
        _state.update(project=project, root=root, proc=None, url=None, script=script, error='', started=time.time(), sandboxed=sandboxed,
                      status='installing' if not (Path(root) / 'node_modules').is_dir() else 'starting')
        _write_state()
    _kill(old)
    if was_sandboxed:
        _stop_container_dev(old_root)
    threading.Thread(target=_run, args=(gen, root, npm, script, sandboxed), daemon=True).start()
    return status()


def _stop_container_dev(root):
    # Killing the local docker client leaves the server running in the container; end its process group.
    try:
        sandbox.stop_dev(root)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def stop():
    with _lock:
        proc, root, sandboxed = _state['proc'], _state['root'], _state['sandboxed']
        _state['gen'] += 1
        _state.update(proc=None, status='stopped', url=None, error='')
        _write_state()
    _kill(proc)
    if sandboxed:
        _stop_container_dev(root)
    return status()


def _status_locked():
    return {'project': _state['project'], 'status': _state['status'], 'url': _state['url'], 'script': _state['script'], 'sandboxed': _state['sandboxed'],
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
