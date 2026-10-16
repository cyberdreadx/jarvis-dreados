import io
import json
import unittest
from unittest.mock import patch
import web_search

class SearXNGTests(unittest.TestCase):
    def test_local_urls_only(self):
        for value in ('https://example.com', 'http://127.0.0.1@evil.com', 'http://localhost/path', 'file:///etc/passwd'):
            with self.assertRaises(ValueError): web_search.local_endpoint(value)

    def test_results_and_query(self):
        with patch.object(web_search,'_settings',{'engine':'searxng','url':'http://127.0.0.1:8088'}), patch('web_search.urllib.request.build_opener') as factory:
            factory.return_value.open.return_value.__enter__.return_value=io.BytesIO(json.dumps({'results':[{'title':'Result','url':'https://example.com','content':'<b>Useful</b>'},{'url':'javascript:alert(1)'}]}).encode())
            results=web_search.search('cats & dogs')
            self.assertEqual(len(results),1)
            self.assertEqual(results[0]['snippet'],'Useful')
            self.assertIn('format=json',factory.return_value.open.call_args.args[0])

    def test_unreachable_is_explicit(self):
        with patch.object(web_search,'_settings',{'engine':'searxng'}), patch('web_search.urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect=OSError('offline')
            with self.assertRaisesRegex(ValueError,'Start its Docker'): web_search.search('test')
