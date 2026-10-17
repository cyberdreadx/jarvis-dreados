"""Optional bridge to the user's own installed Claude Code CLI.

DreadOS never sees, stores, or asks for Claude credentials. The user installs
Claude Code and signs in through Anthropic's own flow (`claude auth login`);
this module only runs that unmodified `claude` program in print mode with all
tools turned off, so it acts as a plain chat model.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKDIR = ROOT / 'data/claude-code'  # empty folder: no project CLAUDE.md or .mcp.json is picked up
_status = {'checked': 0.0, 'value': None}
_lock = threading.Lock()


class ClaudeCodeError(RuntimeError):
    pass


def _known_locations():
    # A server started before Claude Code was installed keeps its old PATH, so also look where the installers put it.
    home, appdata, local = Path.home(), os.environ.get('APPDATA', ''), os.environ.get('LOCALAPPDATA', '')
    places = [home / '.local/bin/claude.exe', home / '.local/bin/claude']
    if appdata: places.append(Path(appdata) / 'npm/claude.cmd')
    if local: places.append(Path(local) / 'Microsoft/WinGet/Links/claude.exe')
    # macOS: Homebrew (Apple silicon and Intel), npm global installs and the older local installer.
    places += [Path('/opt/homebrew/bin/claude'), Path('/usr/local/bin/claude'),
               home / '.npm-global/bin/claude', home / '.claude/local/claude']
    return places


def executable():
    found = shutil.which('claude')
    if found:
        return found
    return next((str(path) for path in _known_locations() if path.is_file()), None)


def _env():
    env = dict(os.environ)
    # Use the person's own Claude Code sign-in, never a key DreadOS holds for its API provider.
    for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_WORKSPACE_ID', 'ANTHROPIC_MODEL'):
        env.pop(name, None)
    return env


def _flags():
    return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}


def status(refresh=False):
    """Report whether `claude` is installed and signed in. Never returns credentials."""
    with _lock:
        ttl = 300 if (_status['value'] or {}).get('ready') else 15
        if not refresh and _status['value'] and time.monotonic() - _status['checked'] < ttl:
            return _status['value']
        path = executable()
        if not path:
            value = {'installed': False, 'ready': False, 'auth': 'none'}
        else:
            try:
                result = subprocess.run([path, 'auth', 'status'], capture_output=True, text=True, timeout=20, env=_env(), **_flags())
                method = json.loads(result.stdout or '{}').get('authMethod', 'none') if result.stdout.strip().startswith('{') else 'none'
                value = {'installed': True, 'ready': result.returncode == 0 and method != 'none', 'auth': method if isinstance(method, str) else 'none'}
            except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
                value = {'installed': True, 'ready': False, 'auth': 'none'}
        _status.update(checked=time.monotonic(), value=value)
        return value


def transcript(message, history):
    """Fold JARVIS's chat history into one prompt; Claude Code runs one turn per call."""
    lines = []
    for item in history:
        speaker = 'User' if item['role'] == 'user' else 'Assistant'
        lines.append(f'{speaker}: {item["content"]}')
    if not lines:
        return message
    return 'Conversation so far:\n' + '\n\n'.join(lines) + '\n\nReply to the latest user message:\nUser: ' + message


def command(path, model, prompt_file):
    args = [path, '-p', '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
            '--system-prompt-file', prompt_file,
            '--tools', '', '--disallowedTools', '*', '--strict-mcp-config', '--disable-slash-commands',
            '--permission-mode', 'dontAsk', '--max-turns', '1', '--no-session-persistence']
    if model:
        args += ['--model', model]
    return args


def reply(message, history, instructions, model='', on_delta=None, cancelled=None, timeout=300):
    path = executable()
    if not path:
        raise ClaudeCodeError('I can’t find Claude Code on this PC. In PowerShell run: irm https://claude.ai/install.ps1 | iex — then open a new terminal, run “claude” to sign in, and restart DreadOS.')
    WORKDIR.mkdir(parents=True, exist_ok=True)
    prompt = transcript(message, history)
    # The system prompt goes in a file and the conversation on stdin, so no chat text is ever put on the command line.
    handle, prompt_file = tempfile.mkstemp(prefix='dreados-system-', suffix='.txt', dir=WORKDIR)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as file:
            file.write(instructions)
        process = subprocess.Popen(command(path, model, prompt_file), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, cwd=WORKDIR, env=_env(), **_flags())
        timer = threading.Timer(timeout, process.kill)
        timer.start()
        chunks, result = [], None
        try:
            process.stdin.write(prompt.encode('utf-8'))
            process.stdin.close()
            for raw in process.stdout:
                if cancelled and cancelled():
                    process.kill()
                    raise ClaudeCodeError('Generation stopped. Partial answer was not saved.')
                try:
                    event = json.loads(raw.decode('utf-8'))
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get('type') == 'stream_event':
                    delta = (event.get('event') or {}).get('delta') or {}
                    if delta.get('type') == 'text_delta' and isinstance(delta.get('text'), str) and delta['text']:
                        chunks.append(delta['text'])
                        if on_delta: on_delta(delta['text'])
                elif event.get('type') == 'result':
                    result = event
            process.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            raise ClaudeCodeError('Claude Code stopped unexpectedly. Check that it runs in a terminal, then try again.') from None
        except BaseException:
            process.kill()  # e.g. the chat was stopped from the stream callback
            raise
        finally:
            timer.cancel()
            process.stdout.close()
    finally:
        try: os.remove(prompt_file)
        except OSError: pass
    if result is None:
        raise ClaudeCodeError('Claude Code did not answer. Open a terminal, run “claude” to check your sign-in, then try again.')
    text = result.get('result') if isinstance(result.get('result'), str) else ''
    if result.get('is_error'):
        lowered = text.lower()
        if 'login' in lowered or 'log in' in lowered or 'auth' in lowered:
            _status.update(value=None)
            raise ClaudeCodeError('Claude Code is not signed in. Open a terminal, run “claude”, sign in, then try again.')
        if 'limit' in lowered:
            raise ClaudeCodeError('Your Claude plan has reached its usage limit for now. Try again later or switch provider in Setup.')
        raise ClaudeCodeError('Claude Code returned an error. Run “claude” in a terminal to check it, then try again.')
    answer = text or ''.join(chunks)
    if not answer.strip():
        raise ClaudeCodeError('Claude Code returned no text. Please try again.')
    return answer
