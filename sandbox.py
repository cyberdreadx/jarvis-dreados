"""Optional Docker sandbox for Build's terminal commands and dev server.

When a project has the sandbox on, the OpenCode plugin (opencode-plugins/sandbox.mjs) rewrites each
Bash call into `python sandbox.py run <payload>`, which runs the original command inside a per-project
Linux container that can only see that project folder (mounted at /work). The container runs as an
unprivileged user with no Linux capabilities, a read-only system, memory/CPU/process limits and,
optionally, no internet. Nothing else from this PC (home folder, SSH keys, other projects) is mounted.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / 'data/opencode/sandbox.json'
IMAGE = 'node:22-bookworm'  # Node, npm, git, python3, curl and build tools for native modules.
DEV_PORTS = (5173, 3000, 4321, 8080)  # Vite, React/Next, Astro, generic; published on 127.0.0.1 only.
WORK = PurePosixPath('/work')
VERSION = '2'  # bump when container settings change; older containers are recreated
WINDOWS = os.name == 'nt'
NO_WINDOW = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if WINDOWS else {}
# What the plugin produces; the UI and the approval logic decode it back to the original command.
WRAPPED_RE = re.compile(r'sandbox\.py"?\s+run\s+([A-Za-z0-9+/=]+)\s*$')

_lock = threading.Lock()
_pull = {'running': False, 'error': ''}


def docker():
    found = shutil.which('docker')
    if found:
        return found
    default = Path(r'C:\Program Files\Docker\Docker\resources\bin\docker.exe')
    return str(default) if WINDOWS and default.is_file() else None


def _docker(*args, timeout=60, check=False):
    exe = docker()
    if not exe:
        raise ValueError('Docker is not installed. Install Docker Desktop to use the sandbox.')
    result = subprocess.run([exe, *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=timeout, **NO_WINDOW)
    if check and result.returncode:
        raise ValueError((result.stderr or result.stdout).strip()[-400:] or f'docker {args[0]} failed.')
    return result


def key(folder):
    value = str(Path(folder).resolve())
    return value.lower() if WINDOWS else value


def _load():
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) and isinstance(data.get('projects'), dict) else {'projects': {}}
    except (OSError, ValueError):
        return {'projects': {}}


def _save(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=1), encoding='utf-8')
    os.replace(tmp, STATE_FILE)


def setting(folder):
    """{'network': bool} if this project's commands run in the sandbox, else None."""
    entry = _load()['projects'].get(key(folder))
    return {'network': entry.get('network') is not False} if isinstance(entry, dict) else None


def root_for(path):
    """The sandboxed project folder containing path, if any."""
    target = key(path)
    for root in _load()['projects']:
        if target == root or target.startswith(root.rstrip('\\/') + os.sep):
            return root
    return None


def name(folder):
    folder = Path(folder).resolve()
    slug = re.sub(r'[^a-z0-9]+', '-', folder.name.lower()).strip('-')[:30] or 'project'
    return f'dreados-sbx-{slug}-{hashlib.sha256(key(folder).encode()).hexdigest()[:8]}'


def _inspect(folder):
    result = _docker('inspect', name(folder), timeout=20)
    if result.returncode:
        return None
    try:
        return json.loads(result.stdout)[0]
    except (ValueError, IndexError):
        return None


def image_ready():
    return _docker('image', 'inspect', IMAGE, timeout=20).returncode == 0


def _pull_image():
    try:
        _docker('pull', IMAGE, timeout=1800, check=True)
        _pull['error'] = ''
    except (ValueError, subprocess.SubprocessError) as error:
        _pull['error'] = f'Could not download the sandbox image: {error}'
    finally:
        _pull['running'] = False


def prepare():
    """Start the one-time image download in the background."""
    with _lock:
        if _pull['running'] or image_ready():
            return
        _pull.update(running=True, error='')
    threading.Thread(target=_pull_image, daemon=True).start()


def status(folder=None):
    info = {'installed': bool(docker()), 'running': False, 'image': False, 'downloading': _pull['running'],
            'error': _pull['error'], 'image_name': IMAGE}
    if info['installed']:
        try:
            info['running'] = _docker('info', '--format', '{{.ServerVersion}}', timeout=20).returncode == 0
            info['image'] = info['running'] and image_ready()
        except subprocess.SubprocessError:
            pass
    if folder is not None:
        cfg = setting(folder)
        info['enabled'] = cfg is not None
        info['network'] = cfg['network'] if cfg else True
        container = _inspect(folder) if info['running'] else None
        info['container'] = bool(container and container['State'].get('Running'))
    return info


def _create(folder, network):
    ports = [arg for port in DEV_PORTS for arg in ('-p', f'127.0.0.1::{port}')]
    _docker('run', '-d', '--init', '--name', name(folder), '--label', 'dreados.sandbox=' + VERSION,
            '--label', 'dreados.root=' + key(folder), '--user', '1000:1000', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--pids-limit', '1024', '--memory', '4g', '--cpus', '4',
            '--read-only', '--tmpfs', '/tmp:rw,exec,size=1g', '--tmpfs', '/home/node:rw,exec,size=2g,uid=1000,gid=1000',
            '-e', 'HOME=/home/node', '-e', 'npm_config_update_notifier=false', '-e', 'DREADOS_SANDBOX=1',
            '-v', f'{Path(folder).resolve()}:{WORK}', '-w', str(WORK), *ports, IMAGE, 'sleep', 'infinity',
            timeout=120, check=True)
    if not network:
        _docker('network', 'disconnect', 'bridge', name(folder), timeout=30)


def ensure(folder):
    """Make sure this project's container is running; returns its name."""
    cfg = setting(folder)
    if cfg is None:
        raise ValueError('The sandbox is off for this project.')
    if not image_ready():
        if _pull['running']:
            raise ValueError('The sandbox image is still downloading. Try again in a minute.')
        print(f'Preparing the sandbox (one-time download of {IMAGE})…', file=sys.stderr, flush=True)
        _docker('pull', IMAGE, timeout=1800, check=True)
    container = _inspect(folder)
    labels = container['Config'].get('Labels', {}) if container else {}
    if container and (labels.get('dreados.root') != key(folder) or labels.get('dreados.sandbox') != VERSION):
        _docker('rm', '-f', name(folder), timeout=60)
        container = None
    if container is None:
        _create(folder, cfg['network'])
    elif not container['State'].get('Running'):
        _docker('start', name(folder), timeout=60, check=True)
    return name(folder)


def set_project(folder, enabled, network=True):
    data = _load()
    if enabled:
        data['projects'][key(folder)] = {'network': bool(network)}
        _save(data)
        prepare()
        container = _inspect(folder) if docker() else None
        if container:
            attached = 'bridge' in (container['NetworkSettings'].get('Networks') or {})
            if network and not attached:
                _docker('network', 'connect', 'bridge', name(folder), timeout=30)
            elif not network and attached:
                _docker('network', 'disconnect', 'bridge', name(folder), timeout=30)
    else:
        data['projects'].pop(key(folder), None)
        _save(data)
        if docker():
            _docker('rm', '-f', name(folder), timeout=60)
    return status(folder)


def host_port(folder, port):
    result = _docker('port', name(folder), f'{port}/tcp', timeout=20)
    for line in result.stdout.splitlines():
        found = re.search(r'127\.0\.0\.1:(\d+)', line)
        if found:
            return int(found.group(1))
    return None


def stop_commands(folder):
    """Stop the AI's running commands (each runs under `timeout`); leaves the dev server alone."""
    if setting(folder) is not None and _inspect(folder):
        _docker('exec', name(folder), 'pkill', '-TERM', '-x', 'timeout', timeout=20)


def encode(command, workdir, seconds, root=None):
    raw = json.dumps({'c': command, 'w': str(workdir), 'r': key(root or workdir), 't': int(seconds)})
    return base64.b64encode(raw.encode()).decode()


def decode(payload):
    data = json.loads(base64.b64decode(payload, validate=True).decode())
    if not isinstance(data.get('c'), str) or not isinstance(data.get('w'), str):
        raise ValueError('Invalid sandbox command.')
    return data


def unwrap(command):
    """Original command for a plugin-wrapped one, else None."""
    found = isinstance(command, str) and WRAPPED_RE.search(command)
    if not found:
        return None
    try:
        return decode(found.group(1))['c']
    except (ValueError, TypeError):
        return None


def container_path(root, workdir):
    rel = Path(workdir).resolve().relative_to(Path(root).resolve())  # ValueError if outside the project
    return WORK.joinpath(*rel.parts)


def run(payload):
    data = decode(payload)
    root = root_for(data['w'])
    if root is None and isinstance(data.get('r'), str) and data['r'] in _load()['projects']:
        root = data['r']
    if root is None:
        print('The sandbox was turned off for this project, so the command was not run. Run it again.', file=sys.stderr)
        return 126
    try:
        inside = container_path(root, data['w'])
    except ValueError:
        print('Sandboxed commands can only run inside the project folder.', file=sys.stderr)
        return 126
    container = ensure(root)
    seconds = max(5, min(int(data.get('t') or 120), 3600))
    cmd = [docker(), 'exec', '-w', str(inside), container, 'timeout', '-k', '5', str(seconds), 'sh', '-c', data['c']]
    code = subprocess.run(cmd, stdin=subprocess.DEVNULL, **NO_WINDOW).returncode
    if code == 124:
        print(f'Sandbox: the command was stopped after {seconds} seconds (time limit).', file=sys.stderr)
    return code


def dev_command(folder, npm_args, script_text=''):
    """docker exec argv running npm in the container, in its own process group so stop_dev can end it.
    Dev servers must listen on 0.0.0.0 inside the container for the published port to reach them."""
    extra = ''
    if npm_args[:1] == ['run']:
        if re.search(r'\b(vite|astro)\b', script_text):
            extra = ' -- --host 0.0.0.0'
        elif re.search(r'\bnext\b', script_text):
            extra = ' -- -H 0.0.0.0'
    inner = 'echo $$ > /tmp/dreados-dev.pid; exec npm ' + ' '.join(npm_args) + extra
    return [docker(), 'exec', '-e', 'HOST=0.0.0.0', '-e', 'BROWSER=none', '-e', 'NO_COLOR=1', '-w', str(WORK),
            ensure(folder), 'setsid', '-w', 'sh', '-c', inner]


def stop_dev(folder):
    if _inspect(folder):
        _docker('exec', name(folder), 'sh', '-c', 'p=$(cat /tmp/dreados-dev.pid 2>/dev/null) && kill -TERM -$p', timeout=20)


def host_url(folder, url):
    """Map a URL printed inside the container (localhost:5173) to its published 127.0.0.1 port."""
    found = re.match(r'(https?://)(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0):(\d+)(.*)', url)
    if not found:
        return None
    port = host_port(folder, int(found.group(2)))
    return f'{found.group(1)}127.0.0.1:{port}{found.group(3)}' if port else None


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'run':
        try:
            sys.exit(run(sys.argv[2]))
        except (ValueError, subprocess.SubprocessError) as error:
            print(f'Sandbox error: {error}', file=sys.stderr)
            sys.exit(125)
    print('usage: sandbox.py run <payload>', file=sys.stderr)
    sys.exit(2)
