import io
import json
import unittest
from unittest.mock import patch

import providers
import test_server


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(providers.os.environ, {}, clear=True)
        self.settings = patch.object(providers, '_settings', {})
        self.active = patch.object(providers, '_active', 'openai')
        for context in (self.env, self.settings, self.active):
            context.start()
            self.addCleanup(context.stop)

    def save(self, provider, key='private-test-key'):
        return providers.configure({'provider': provider, 'key': key, 'model': providers.PROVIDERS[provider]['model']})

    def test_provider_keys_are_separate_and_never_returned(self):
        self.save('openai', 'openai-private')
        result = self.save('claude', 'claude-private')
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(providers.config('openai')[1]['key'], 'openai-private')
        self.assertEqual(providers.config('claude')[1]['key'], 'claude-private')
        self.assertEqual(providers.config('grok')[1]['key'], '')
        self.save('claude', '')
        self.assertEqual(providers.config('claude')[1]['key'], 'claude-private')

    def test_removal_does_not_affect_other_provider(self):
        self.save('openai')
        self.save('grok')
        providers.configure({'provider': 'grok', 'action': 'remove'})
        self.assertFalse(providers.status()['ai'])
        self.assertTrue(providers.status()['providers']['openai']['configured'])

    def test_invalid_settings_do_not_replace_working_config(self):
        self.save('openai')
        for changes in ({'provider': 'unknown'}, {'provider': []}, {'key': 'bad\nheader'}, {'model': ''}, {'workspace': 'bad\rheader'}):
            with self.assertRaises(ValueError):
                providers.configure({'provider': 'claude', 'key': 'test', 'model': 'claude-sonnet-5-5', **changes})
        self.assertEqual(providers.status()['provider'], 'openai')
        self.assertFalse(providers.status()['providers']['claude']['configured'])

    @patch('providers.urllib.request.urlopen')
    def test_provider_wire_formats_and_destinations(self, network):
        responses = {
            'openai': {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Reply'}]}]},
            'claude': {'content': [{'type': 'thinking', 'thinking': 'ignore'}, {'type': 'text', 'text': 'Reply'}]},
            'grok': {'choices': [{'message': {'content': 'Reply'}}]},
        }
        for provider, response in responses.items():
            with self.subTest(provider=provider):
                self.save(provider, provider + '-private')
                network.return_value.__enter__.return_value = io.BytesIO(json.dumps(response).encode())
                self.assertEqual(providers.reply('Hello', [], provider), 'Reply')
                request = network.call_args.args[0]
                self.assertEqual(request.full_url, providers.PROVIDERS[provider]['url'])
                payload = json.loads(request.data)
                headers = {k.lower(): v for k, v in request.header_items()}
                self.assertNotIn(provider + '-private', request.data.decode())
                if provider == 'claude':
                    self.assertEqual(headers['x-api-key'], 'claude-private')
                    self.assertEqual(headers['anthropic-version'], '2023-06-01')
                    self.assertIn('system', payload)
                    self.assertNotIn('Authorization', headers)
                else:
                    self.assertEqual(headers['authorization'], 'Bearer ' + provider + '-private')

    @patch('providers.urllib.request.urlopen')
    def test_missing_key_never_falls_back(self, network):
        self.save('openai')
        self.assertIn('Grok API key', providers.reply('Hello', [], 'grok'))
        network.assert_not_called()


class SettingsHTTP(unittest.TestCase):
    setUpClass = classmethod(test_server.HTTP.setUpClass.__func__)
    tearDownClass = classmethod(test_server.HTTP.tearDownClass.__func__)
    request = test_server.HTTP.request

    def test_creator_requires_provider_and_uses_creative_instructions(self):
        headers = {'X-Jarvis-Token': __import__('server').TOKEN, 'Content-Type': 'application/json'}
        body = json.dumps({'kind': 'post', 'brief': 'A coffee launch', 'provider': 'local', 'platform': 'Instagram', 'tone': 'Warm'}).encode()
        with patch.object(providers, '_settings', {}), patch.object(providers, '_active', 'openai'), patch.dict(providers.os.environ, {}, clear=True):
            self.assertEqual(self.request('/api/create', body, headers)[0], 400)
            providers.configure({'provider': 'local', 'model': 'test', 'base_url': 'http://localhost:1234/v1'})
            with patch('providers.reply', return_value='A polished post') as reply:
                code, response = self.request('/api/create', body, headers)
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(response)['draft'], 'A polished post')
                self.assertIn('coffee launch', reply.call_args.args[0])
                self.assertIn('creative collaborator', reply.call_args.args[3])

    def test_creator_returns_error_instead_of_failed_draft(self):
        headers = {'X-Jarvis-Token': __import__('server').TOKEN, 'Content-Type': 'application/json'}
        body = json.dumps({'kind': 'art', 'brief': 'Latina girl', 'provider': 'local'}).encode()
        with patch.object(providers, '_settings', {}), patch.object(providers, '_active', 'openai'):
            providers.configure({'provider': 'local', 'model': 'test', 'base_url': 'http://localhost:1234/v1'})
            with patch('providers.reply', side_effect=providers.ProviderError('No text answer was returned.')) as reply:
                code, response = self.request('/api/create', body, headers)
                self.assertEqual(code, 502)
                self.assertIn('error', json.loads(response))
                self.assertNotIn('draft', json.loads(response))
                self.assertTrue(reply.call_args.kwargs['strict'])
                self.assertEqual(reply.call_args.kwargs['max_tokens'], 4096)

    def test_mcp_routes_reject_unauthorized_calls(self):
        for path in ('/api/mcp/add', '/api/mcp/auth', '/api/mcp/call', '/api/local-models', '/api/create'):
            self.assertEqual(self.request(path, b'{}')[0], 403)

    def test_settings_auth_validation_and_no_secret_echo(self):
        with patch.object(providers, '_settings', {}), patch.object(providers, '_active', 'openai'):
            body = json.dumps({'provider': 'claude', 'key': 'private-test-only', 'model': 'claude-sonnet-5-5'}).encode()
            headers = {'X-Jarvis-Token': __import__('server').TOKEN, 'Content-Type': 'application/json'}
            self.assertEqual(self.request('/api/settings', body)[0], 403)
            self.assertEqual(self.request('/api/settings', body, {**headers, 'Origin': 'https://evil.example'})[0], 403)
            code, result = self.request('/api/settings', body, headers)
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(result)['provider'], 'claude')
            self.assertNotIn(b'private-test-only', result)
            self.assertNotIn(b'private-test-only', self.request('/api/status')[1])
            self.assertEqual(self.request('/api/settings', b'{"provider":"bad"}', headers)[0], 400)
