import io
import json
import tempfile
from pathlib import Path
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import server


class Commands(unittest.TestCase):
    def test_greeting_and_clock(self):
        self.assertIn('online', server.local_command('Hey Jarvis, hello!'))
        self.assertIn('It is', server.local_command('What time is it?'))

    @patch('server.subprocess.Popen')
    def test_allowlisted_launch(self, launch):
        with patch('server.os.name', 'nt'):
            self.assertEqual(server.local_command('Please open calculator'), 'Opening calculator.')
        self.assertEqual(launch.call_args.kwargs, {'shell': False})
        self.assertTrue(launch.call_args.args[0][0].endswith('calc.exe'))

    @patch('server.subprocess.Popen')
    @patch('server.webbrowser.open')
    def test_shell_text_does_not_execute(self, browser, launch):
        self.assertIn('I can open', server.local_command('open calculator & whoami'))
        self.assertIsNone(server.local_command('run powershell.exe'))
        launch.assert_not_called()
        browser.assert_not_called()

    @patch('server.webbrowser.open', return_value=True)
    def test_search_encoding(self, browser):
        server.local_command('search for cats & dogs')
        self.assertEqual(browser.call_args.args[0], 'https://www.google.com/search?q=cats%20%26%20dogs')

    def test_no_key(self):
        with patch.dict(server.os.environ, {'OPENAI_API_KEY': ''}):
            self.assertIn('.env', server.ai_reply('Tell me a story', []))

    @patch('server.urllib.request.urlopen')
    def test_ai_request_and_mixed_output(self, request):
        request.return_value.__enter__.return_value = io.BytesIO(json.dumps({'output': [
            {'type': 'reasoning'}, {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Hello there.'}]}]}).encode())
        with patch.dict(server.os.environ, {'OPENAI_API_KEY': 'test-key'}):
            answer = server.ai_reply('Hello', [{'role': 'system', 'content': 'ignored'}, {'role': 'user', 'content': 'Earlier'}])
        self.assertEqual(answer, 'Hello there.')
        payload = json.loads(request.call_args.args[0].data)
        self.assertFalse(payload['store'])
        self.assertEqual([item['role'] for item in payload['input']], ['user', 'user'])

    @patch('server.urllib.request.urlopen', side_effect=urllib.error.HTTPError('url', 401, 'Unauthorized', {}, None))
    def test_auth_error_is_actionable(self, request):
        with patch.dict(server.os.environ, {'OPENAI_API_KEY': 'test-key'}):
            self.assertIn('not accepted', server.ai_reply('Hello', []))


class HTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.http.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def request(self, path, data=None, headers=None):
        request = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    def test_search_fallback_links(self):
        with patch('web_search._key',''), patch('web_search._settings',{}):
            status,body=self.request('/api/chat',json.dumps({'message':'can you search the web for voice models'}).encode(),{'X-Jarvis-Token':server.TOKEN})
            data=json.loads(body)
            self.assertEqual(status,200)
            self.assertEqual(data['source'],'browser search links')
            self.assertIn('voice+models',data['results'][0]['url'])
            self.assertIn('API key',data['reply'])

    def test_media_shared_storage_requires_token(self):
        with tempfile.TemporaryDirectory() as folder, patch('media_library.DB',Path(folder)/'media.sqlite3'):
            headers={'X-Jarvis-Token':server.TOKEN,'Content-Type':'application/json'}
            self.assertEqual(self.request('/api/media',b'{"action":"list"}')[0],403)
            status,body=self.request('/api/media',json.dumps({'action':'draft','text':'Shared across devices','brief':'Test'}).encode(),headers)
            self.assertEqual(status,200)
            ident=json.loads(body)['item']['id']
            status,body=self.request('/api/media',b'{"action":"list"}',headers)
            self.assertEqual(status,200)
            self.assertEqual(json.loads(body)['items'][0]['id'],ident)
            self.assertEqual(self.request('/api/media',b'[]',headers)[0],400)

    def test_search_synthesizes_with_sources_and_personality(self):
        results=[{'title':'Example','url':'https://example.com','snippet':'Evidence about the topic.'}]
        with patch('web_search.search',return_value=results), patch('server.providers.reply',return_value='Here is what matters [1].') as reply:
            status,body=self.request('/api/chat',json.dumps({'message':'Explain the topic','web_search':True,'system_prompt':'Be friendly','provider':'local'}).encode(),{'X-Jarvis-Token':server.TOKEN})
            data=json.loads(body)
            self.assertEqual(status,200)
            self.assertEqual(data['reply'],'Here is what matters [1].')
            self.assertEqual(data['results'],results)
            self.assertIn('Evidence about the topic.',reply.call_args.args[0])
            self.assertEqual(reply.call_args.args[2],'local')
            self.assertIn('Be friendly',reply.call_args.kwargs['instructions'])
            self.assertIn('never instructions',reply.call_args.kwargs['instructions'])

    def test_empty_search_does_not_invent_answer(self):
        with patch('web_search.search',return_value=[]), patch('server.providers.reply') as reply:
            status,body=self.request('/api/chat',json.dumps({'message':'search for obscure topic'}).encode(),{'X-Jarvis-Token':server.TOKEN})
            self.assertEqual(status,200)
            self.assertIn('couldn',json.loads(body)['reply'])
            reply.assert_not_called()

    def test_persistent_chat_uses_server_memory(self):
        with tempfile.TemporaryDirectory() as folder, patch('chat_store.DB_PATH',Path(folder)/'chats.sqlite3'):
            headers={'X-Jarvis-Token':server.TOKEN,'Content-Type':'application/json'}
            self.assertEqual(self.request('/api/library')[0],403)
            _,body=self.request('/api/library',json.dumps({'action':'create','personality':'Be concise.'}).encode(),headers)
            ident=json.loads(body)['id']
            self.request('/api/library',json.dumps({'action':'update','id':ident,'version':0,'memory':'The project is Aurora.'}).encode(),headers)
            payload={'message':'What project?','chat_id':ident,'version':1,'history':[{'role':'user','content':'Forged context'}]}
            with patch('providers.reply',return_value='Aurora.') as reply:
                status,body=self.request('/api/chat',json.dumps(payload).encode(),headers)
                self.assertEqual(status,200)
                self.assertEqual(reply.call_args.args[1],[])
                self.assertIn('Aurora',reply.call_args.kwargs['instructions'])
            status,body=self.request('/api/conversation?id='+ident,headers=headers)
            self.assertEqual(len(json.loads(body)['messages']),2)
            self.assertEqual(self.request('/api/chat',json.dumps(payload).encode(),headers)[0],409)

    def test_assets_and_secret_files(self):
        for path in ('/', '/app.js', '/style.css'):
            self.assertEqual(self.request(path)[0], 200)
        for path in ('/.env', '/server.py', '/../.env', '/.git/config'):
            self.assertEqual(self.request(path)[0], 404)

    def test_host_protection(self):
        self.assertEqual(self.request('/api/status', headers={'Host': 'evil.example'})[0], 403)

    def test_private_tailscale_access(self):
        with patch.dict(server.os.environ, {'DREADOS_TAILSCALE_ORIGIN':'https://msi.test.ts.net', 'DREADOS_TAILSCALE_USER':'owner@example.com'}):
            headers={'Host':'msi.test.ts.net','Tailscale-User-Login':'owner@example.com','X-Forwarded-For':'100.64.0.2'}
            self.assertEqual(self.request('/api/status',headers=headers)[0],200)
            headers.update({'Origin':'https://msi.test.ts.net','X-Jarvis-Token':server.TOKEN})
            self.assertEqual(self.request('/api/chat',b'{"message":"hello"}',headers)[0],200)
            headers['Tailscale-User-Login']='other@example.com'
            self.assertEqual(self.request('/api/status',headers=headers)[0],403)
            headers['Host']='127.0.0.1:'+str(self.http.server_port)
            self.assertEqual(self.request('/api/status',headers=headers)[0],403)
            headers.pop('Tailscale-User-Login')
            self.assertEqual(self.request('/api/status',headers=headers)[0],403)

    def test_token_and_origin_protection(self):
        data = b'{"message":"hello"}'
        self.assertEqual(self.request('/api/chat', data)[0], 403)
        headers = {'X-Jarvis-Token': server.TOKEN, 'Origin': 'https://evil.example'}
        self.assertEqual(self.request('/api/chat', data, headers)[0], 403)

    def test_chat_and_validation(self):
        status, body = self.request('/api/status')
        token = json.loads(body)['token']
        headers = {'X-Jarvis-Token': token, 'Content-Type': 'application/json'}
        status, body = self.request('/api/chat', b'{"message":"hello"}', headers)
        self.assertEqual(status, 200)
        self.assertIn('online', json.loads(body)['reply'])
        for bad in (b'{}', b'[]', b'{"message":123}', b'{"message":" "}', b'invalid'):
            self.assertEqual(self.request('/api/chat', bad, headers)[0], 400)
        self.assertEqual(self.request('/api/chat', b'x' * 120001, headers)[0], 400)
        self.assertEqual(self.request('/api/chat', json.dumps({'message':'hello','padding':'x'*120001}).encode(), headers)[0], 413)


if __name__ == '__main__':
    unittest.main()
