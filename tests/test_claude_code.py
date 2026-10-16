import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import claude_code
import providers

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
log = os.environ['FAKE_CLAUDE_LOG']
if sys.argv[1:3] == ['auth', 'status']:
    print(json.dumps({'loggedIn': os.environ.get('FAKE_AUTH') != 'none', 'authMethod': os.environ.get('FAKE_AUTH', 'claude.ai')}))
    sys.exit(0 if os.environ.get('FAKE_AUTH') != 'none' else 1)
args = sys.argv[1:]
prompt_file = args[args.index('--system-prompt-file') + 1]
stdin = sys.stdin.read()
with open(log, 'w') as f:
    json.dump({'args': args, 'stdin': stdin, 'system': open(prompt_file).read(), 'has_key': 'ANTHROPIC_API_KEY' in os.environ, 'cwd': os.getcwd()}, f)
mode = os.environ.get('FAKE_MODE', 'ok')
print(json.dumps({'type': 'system', 'subtype': 'init'}))
if mode == 'ok':
    for part in ('Hello ', 'there'):
        print(json.dumps({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': part}}}))
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'Hello there'}))
else:
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': True, 'result': 'Not logged in · Please run /login'}))
'''


class ClaudeCodeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        fake = Path(self.dir.name) / 'claude'
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.log = Path(self.dir.name) / 'log.json'
        env = {'PATH': self.dir.name + os.pathsep + os.environ.get('PATH', ''), 'FAKE_CLAUDE_LOG': str(self.log),
               'ANTHROPIC_API_KEY': 'jarvis-api-key'}
        for context in (patch.dict(os.environ, env), patch.object(claude_code, 'WORKDIR', Path(self.dir.name) / 'work'),
                        patch.object(providers, '_settings', {}), patch.object(providers, '_active', 'openai')):
            context.start(); self.addCleanup(context.stop)
        claude_code._status.update(value=None)

    def test_status_reports_sign_in_without_credentials(self):
        self.assertEqual(claude_code.status(refresh=True), {'installed': True, 'ready': True, 'auth': 'claude.ai'})
        with patch.dict(os.environ, {'FAKE_AUTH': 'none'}):
            self.assertFalse(claude_code.status(refresh=True)['ready'])
        with patch.object(claude_code, 'executable', return_value=None):
            self.assertEqual(claude_code.status(refresh=True)['installed'], False)

    def test_reply_streams_and_keeps_chat_off_the_command_line(self):
        deltas = []
        history = [{'role': 'user', 'content': 'secret earlier question'}, {'role': 'assistant', 'content': 'earlier answer'}]
        answer = claude_code.reply('latest question', history, 'Be DreadOS.', 'sonnet', on_delta=deltas.append)
        self.assertEqual(answer, 'Hello there')
        self.assertEqual(deltas, ['Hello ', 'there'])
        run = json.loads(self.log.read_text())
        self.assertFalse(run['has_key'], 'the JARVIS API key must not reach Claude Code')
        self.assertEqual(run['system'], 'Be DreadOS.')
        self.assertIn('latest question', run['stdin']); self.assertIn('secret earlier question', run['stdin'])
        self.assertFalse(any('question' in arg or 'DreadOS' in arg for arg in run['args']))
        for flag in ('--tools', '--disallowedTools', '--no-session-persistence', '--strict-mcp-config'):
            self.assertIn(flag, run['args'])
        self.assertEqual(run['args'][run['args'].index('--tools') + 1], '')
        self.assertEqual(run['args'][run['args'].index('--model') + 1], 'sonnet')
        self.assertEqual(list(claude_code.WORKDIR.iterdir()), [], 'temporary system prompt file is removed')

    def test_not_signed_in_is_explained(self):
        with patch.dict(os.environ, {'FAKE_MODE': 'error'}):
            with self.assertRaisesRegex(claude_code.ClaudeCodeError, 'not signed in'):
                claude_code.reply('hi', [], 'x')

    def test_missing_install_is_explained(self):
        with patch.object(claude_code, 'executable', return_value=None):
            with self.assertRaisesRegex(claude_code.ClaudeCodeError, 'not installed'):
                claude_code.reply('hi', [], 'x')

    def test_provider_routes_without_key_and_accepts_blank_model(self):
        result = providers.configure({'provider': 'claudecode', 'key': 'ignored-key', 'model': ''})
        self.assertEqual(result['provider'], 'claudecode')
        self.assertTrue(result['ai'])
        self.assertNotIn('ignored-key', json.dumps(result))
        self.assertEqual(providers.reply('Hello', [], 'claudecode'), 'Hello there')
        image = {'type': 'image', 'mime': 'image/png', 'data': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='}
        self.assertIn('Image attachments', providers.reply('Look', [], 'claudecode', attachments=[image]))


if __name__ == '__main__':
    unittest.main()
