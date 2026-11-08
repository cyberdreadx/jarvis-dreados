"""Build's terminal panel: run one command at a time inside a project folder.

Each command is its own process (PowerShell on Windows, sh elsewhere, or `sh` in the project's
Docker container when its sandbox is on). `cd` is handled here and cannot leave the project folder.
Output is kept in a bounded buffer that the page polls by offset; typed lines go to the running
command's stdin, so scripts that ask for input work.
"""
import atexit
import codecs
import os
import re
import signal
import subprocess
import threading
from pathlib import Path
import sandbox

WINDOWS = os.name == 'nt'
NO_WINDOW = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if WINDOWS else {'start_new_session': True}
KEEP = 200_000  # characters of output kept per project
MAX_COMMAND = 8000
CD_RE = re.compile(r'\s*(?:cd|chdir|Set-Location|sl)(?:\s+(.*?)|(\.\.))?\s*', re.I)
PID_FILE = '/tmp/dreados-term.pid'

_lock = threading.Lock()
_terms = {}


class _Term:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.cwd = ()  # path parts relative to the project
        self.proc = None
        self.sandboxed = False
        self.text = ''
        self.start = 0  # offset of self.text[0] in the whole output
        self.exit = None
        self.command = ''
        self.stopped = False

    @property
    def end(self):
        return self.start + len(self.text)

    def write(self, text):
        self.text += text
        if len(self.text) > KEEP:
            cut = len(self.text) - KEEP
            self.text, self.start = self.text[cut:], self.start + cut

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def cwd_label(self):
        return '/'.join(self.cwd) or '.'


def _term(root):
    root = Path(root).resolve()
    return _terms.setdefault(sandbox.key(root), _Term(root))


def _strip_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        return value[1:-1]
    return value


def _change_dir(term, target):
    if not target or target == '~':
        term.cwd = ()
        return
    target = _strip_quotes(target)
    if target in ('/', '\\') or re.match(r'^[A-Za-z]:[\\/]?$', target):
        raise ValueError('The terminal stays inside the project folder.')
    base = Path(target) if Path(target).is_absolute() else term.root.joinpath(*term.cwd, target)
    folder = base.resolve()
    try:
        rel = folder.relative_to(term.root)
    except ValueError:
        raise ValueError('The terminal stays inside the project folder.') from None
    if not folder.is_dir():
        raise ValueError(f'No such folder: {target}')
    term.cwd = rel.parts


def _argv(term, command):
    folder = term.root.joinpath(*term.cwd)
    if term.sandboxed:
        inside = sandbox.WORK.joinpath(*term.cwd)
        inner = f'echo $$ > {PID_FILE}; exec sh -c "$0"'
        return [sandbox.docker(), 'exec', '-i', '-e', 'PYTHONUNBUFFERED=1', '-w', str(inside),
                sandbox.ensure(term.root), 'setsid', '-w', 'sh', '-c', inner, command], folder
    if WINDOWS:
        # UTF-8 both ways, and the command's own exit code instead of PowerShell's 0/1.
        script = ('[Console]::OutputEncoding=[Text.Encoding]::UTF8;$OutputEncoding=[Text.Encoding]::UTF8;'
                  "$ProgressPreference='SilentlyContinue'\n& {\n" + command +
                  '\n}\n$dreadosOk=$?;if($LASTEXITCODE){exit $LASTEXITCODE};if(-not $dreadosOk){exit 1}')
        # Plain flags on purpose: hidden PowerShell with -ExecutionPolicy Bypass/-NonInteractive is a
        # malware pattern that Norton's behavioural scanner blocks (IDP.Generic). Same rules as your own terminal.
        return ['powershell.exe', '-NoLogo', '-NoProfile', '-Command', script], folder
    return [os.environ.get('SHELL') or '/bin/sh', '-c', command], folder


def _pump(term, proc):
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    while True:
        chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, 'read1') else proc.stdout.read(4096)
        if not chunk:
            break
        text = decoder.decode(chunk).replace('\r\n', '\n')
        with _lock:
            term.write(text)
    code = proc.wait()
    for pipe in (proc.stdout, proc.stdin):
        try:
            pipe.close()
        except OSError:
            pass
    with _lock:
        tail = decoder.decode(b'', final=True)
        if tail:
            term.write(tail)
        if term.proc is proc:
            term.exit = None if term.stopped else code
            if term.text and not term.text.endswith('\n'):
                term.write('\n')
            if code and not term.stopped:
                term.write(f'[exit code {code}]\n')


def run(root, command):
    if not isinstance(command, str) or not command.strip():
        raise ValueError('Type a command to run.')
    if len(command) > MAX_COMMAND:
        raise ValueError('That command is too long.')
    command = command.strip()
    with _lock:
        term = _term(root)
        if term.running():
            raise ValueError('A command is still running. Stop it first, or type into it.')
        term.write(f'{term.cwd_label()}> {command}\n')
        cd = CD_RE.fullmatch(command)
        if cd and not re.search(r'[;&|]', command):
            try:
                _change_dir(term, cd.group(1) or cd.group(2))
            except ValueError as error:
                term.write(f'{error}\n')
            return _status(term)
        term.sandboxed = sandbox.setting(term.root) is not None
    try:
        argv, folder = _argv(term, command)
        if not folder.is_dir():
            term.cwd = ()
            argv, folder = _argv(term, command)
        env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'FORCE_COLOR': '0',
               'NO_COLOR': '1', 'BROWSER': 'none'}
        proc = subprocess.Popen(argv, cwd=folder, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, **NO_WINDOW)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        with _lock:
            term.write(f'Could not run the command: {error}\n')
            return _status(term)
    with _lock:
        term.proc, term.exit, term.command, term.stopped = proc, None, command, False
    threading.Thread(target=_pump, args=(term, proc), daemon=True).start()
    with _lock:
        return _status(term)


def send_input(root, text):
    if not isinstance(text, str) or len(text) > MAX_COMMAND:
        raise ValueError('Invalid input.')
    with _lock:
        term = _term(root)
        if not term.running():
            raise ValueError('No command is running.')
        term.write(text + '\n')
        proc = term.proc
    try:
        proc.stdin.write((text + '\n').encode('utf-8'))
        proc.stdin.flush()
    except OSError:
        pass
    return status(root)


def _kill(term):
    proc = term.proc
    if not proc or proc.poll() is not None:
        return
    if term.sandboxed:
        try:
            name = sandbox.name(term.root)
            sandbox._docker('exec', name, 'sh', '-c', f'p=$(cat {PID_FILE} 2>/dev/null) && kill -TERM -$p', timeout=20)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        if WINDOWS:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True, timeout=20, **NO_WINDOW)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def stop(root):
    with _lock:
        term = _term(root)
        running = term.running()
    if running:
        term.stopped = True
        _kill(term)
        with _lock:
            term.write('^C stopped\n')
    return status(root)


def clear(root):
    with _lock:
        term = _term(root)
        term.start, term.text = term.end, ''
        return _status(term)


def _status(term, since=None):
    reset = isinstance(since, bool) or not isinstance(since, int) or not term.start <= since <= term.end
    since = term.start if reset else since
    return {'output': term.text[since - term.start:], 'offset': term.end, 'reset': reset,
            'running': term.running(), 'exit': term.exit, 'cwd': term.cwd_label(), 'command': term.command,
            'sandboxed': sandbox.setting(term.root) is not None}


def status(root, since=None):
    with _lock:
        return _status(_term(root), since)


def _shutdown():
    for term in list(_terms.values()):
        _kill(term)


atexit.register(_shutdown)
