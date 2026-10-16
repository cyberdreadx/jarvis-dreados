import base64
import io
import json
import unittest
from unittest.mock import patch
import providers
import web_search

class ChatFeatures(unittest.TestCase):
    def test_reject_invalid_attachments(self):
        for value in ({}, [1], [{'type':'image','mime':'image/png','data':'bogus'}], [{'type':'text','text':'x'*40001}]):
            with self.assertRaises(ValueError): providers.validate_attachments(value)

    def test_vision_and_personality_payloads(self):
        image={'type':'image','mime':'image/png','data':base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()}
        cfg={'model':'test','key':'test','workspace':'','base_url':'http://127.0.0.1:1234/v1'}
        for provider in ('local','grok','claude','openai'):
            reply={'choices':[{'message':{'content':'A blue square.'}}], 'content':[{'type':'text','text':'A blue square.'}], 'output':[{'type':'message','content':[{'type':'output_text','text':'A blue square.'}]}]}
            with patch('providers.config',return_value=(provider,cfg)), patch('providers.local_open') as local, patch('providers.urllib.request.urlopen') as remote:
                transport=local if provider=='local' else remote
                transport.return_value.__enter__.return_value=io.BytesIO(json.dumps(reply).encode())
                self.assertEqual(providers.reply('Describe',[],provider,instructions='Be a patient coach.',attachments=[image]),'A blue square.')
                payload=json.loads(transport.call_args.args[0].data)
                self.assertIn('patient coach',json.dumps(payload))
                messages=payload.get('input',payload.get('messages'))
                self.assertIsInstance(messages[-1]['content'],list)
                self.assertIn(image['data'],json.dumps(messages[-1]))

    def test_search_links_filtered(self):
        payload={'web':{'results':[{'title':'Good','url':'https://example.com','description':'Useful'}, {'url':'javascript:alert(1)'}]}}
        with patch('web_search._settings',{}), patch('web_search._key','test-key'), patch('web_search.urllib.request.urlopen') as request:
            request.return_value.__enter__.return_value=io.BytesIO(json.dumps(payload).encode())
            results=web_search.search('cats & dogs')
            self.assertEqual(len(results),1)
            self.assertIn('cats+%26+dogs',request.call_args.args[0].full_url)
            self.assertEqual(request.call_args.args[0].get_header('X-subscription-token'),'test-key')

    def test_search_without_key_is_explicit(self):
        with patch('web_search._settings',{}), patch('web_search._key',''):
            with self.assertRaisesRegex(ValueError,'API key'): web_search.search('AI news')
        self.assertIn('AI+news',web_search.browser_links('AI news')[0]['url'])

    def test_retry_search_uses_previous_topic(self):
        history=[{'role':'user','content':'what vegan food exists around me'}, {'role':'assistant','content':'I cannot browse.'},{'role':'user','content':'try it'}]
        query,retry=web_search.resolve_followup('ok try now',history)
        self.assertTrue(retry)
        self.assertEqual(query,'what vegan food exists around me')
        self.assertEqual(web_search.resolve_followup('weather in Paris',history),('weather in Paris',False))
        self.assertEqual(web_search.resolve_followup('try it',[]),('',True))
