import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import providers
import mcp_client


class FakeService(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    received = []

    def log_message(self, *args):
        pass

    def respond(self, data, sse=False):
        raw = json.dumps(data).encode()
        if sse:
            raw = b'data: ' + raw + b'\n\n'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream' if sse else 'application/json')
        self.send_header('Transfer-Encoding', 'chunked')
        self.send_header('Mcp-Session-Id', 'test-session')
        self.end_headers()
        self.wfile.write(f'{len(raw):X}\r\n'.encode() + raw + b'\r\n0\r\n\r\n')

    def do_GET(self):
        self.respond({'data': [{'id': 'test/local-model'}]})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.received.append((self.path, data, dict(self.headers)))
        if self.path == '/v1/chat/completions':
            return self.respond({'choices': [{'message': {'content': 'Local model reply'}}]})
        method = data['method']
        if method == 'notifications/initialized':
            self.send_response(202)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        result = {'protocolVersion': '2025-11-25', 'capabilities': {}, 'serverInfo': {'name': 'fixture', 'version': '1'}}
        if method == 'tools/list':
            result = {'tools': [{'name': 'make_art', 'inputSchema': {'type': 'object', 'properties': {'prompt': {'type': 'string'}}, 'required': ['prompt']}}]}
        elif method == 'tools/call':
            result = {'content': [{'type': 'text', 'text': 'Generated test artifact'}]}
        self.respond({'jsonrpc': '2.0', 'id': data['id'], 'result': result}, sse=method == 'tools/call')


class LocalAndMCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), FakeService)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        FakeService.received = []
        for context in (patch.dict(providers.os.environ, {}, clear=True), patch.object(providers, '_settings', {}),
                        patch.object(providers, '_active', 'openai'), patch.object(mcp_client, '_connections', {}), patch.object(mcp_client, '_pending', {})):
            context.start()
            self.addCleanup(context.stop)

    def test_local_chat_and_discovery_without_key(self):
        result = providers.local_models({'base_url': self.base})
        self.assertEqual(result['models'], ['test/local-model'])
        providers.configure({'provider': 'local', 'model': result['models'][0], 'base_url': self.base})
        self.assertTrue(providers.status()['ai'])
        self.assertEqual(providers.reply('Hello', [], 'local'), 'Local model reply')
        path, data, headers = FakeService.received[-1]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertEqual(data['model'], 'test/local-model')
        self.assertNotIn('Authorization', headers)

    def test_local_url_restrictions(self):
        for value in ('https://api.openai.com/v1', 'http://127.0.0.1:1234/v1?key=secret', 'file:///a', 'http://user:pass@localhost:1234/v1', 'http://192.168.1.2:1234/v1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                providers.local_url(value)
        self.assertEqual(providers.local_url('http://localhost:1234/'), 'http://127.0.0.1:1234/v1')

    def test_mcp_discovery_then_explicit_sse_tool_call(self):
        result = mcp_client.add({'name': 'Test media', 'url': self.base + '/mcp', 'token': 'test-only-secret'})
        connection = result['connections'][0]
        self.assertEqual(connection['status'], 'connected')
        self.assertEqual([item[1]['method'] for item in FakeService.received], ['initialize', 'notifications/initialized', 'tools/list'])
        self.assertNotIn('test-only-secret', json.dumps(result))
        result = mcp_client.call({'id': connection['id'], 'tool': 'make_art', 'arguments': {'prompt': 'Ocean'}})
        self.assertEqual(result['result']['content'][0]['text'], 'Generated test artifact')
        self.assertEqual(FakeService.received[-1][2]['Mcp-Session-Id'], 'test-session')
        with self.assertRaises(ValueError):
            mcp_client.call({'id': connection['id'], 'tool': 'unknown', 'arguments': {}})
        mcp_client.remove(connection['id'])
        self.assertEqual(mcp_client.public_connections(), [])

    def test_mcp_endpoint_validation(self):
        for value in ('http://example.com/mcp', 'file:///etc/passwd', 'https://user:secret@example.com/mcp', 'https://example.com/mcp?token=secret'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mcp_client.endpoint(value)

    @patch('mcp_client._json_request')
    def test_oauth_pkce_and_one_time_state(self, request):
        connection = mcp_client.add({'name': 'Fixture', 'url': self.base + '/mcp'})['connections'][0]
        request.side_effect = [
            {'authorization_servers': ['https://auth.example.com'], 'scopes_supported': ['read']},
            {'issuer': 'https://auth.example.com', 'authorization_endpoint': 'https://auth.example.com/authorize', 'token_endpoint': 'https://auth.example.com/token', 'registration_endpoint': 'https://auth.example.com/register', 'code_challenge_methods_supported': ['S256']},
            {'client_id': 'public-client', 'token_endpoint_auth_method': 'none'},
            {'access_token': 'oauth-private-token'},
        ]
        result = mcp_client.authorize(connection['id'], 'http://127.0.0.1:8765/oauth/callback')
        query = parse_qs(urlsplit(result['authorization_url']).query)
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertNotIn('code_verifier', query)
        mcp_client.callback({'state': query['state'], 'code': ['one-use-code']})
        self.assertEqual(mcp_client._get(connection['id'])['token'], 'oauth-private-token')
        self.assertIn('code_verifier', request.call_args.args[1])
        with self.assertRaises(ValueError):
            mcp_client.callback({'state': query['state'], 'code': ['one-use-code']})
