import unittest
from unittest.mock import patch,MagicMock
import opencode_bridge as bridge
class OpenCodeTransportTests(unittest.TestCase):
    def test_success_closes_connection(self):
        conn=MagicMock();response=conn.getresponse.return_value;response.status=200;response.read.return_value=b'{"healthy":true}'
        with patch.object(bridge.http.client,'HTTPConnection',return_value=conn),patch.object(bridge,'password',return_value='test'):
            self.assertTrue(bridge.request('/global/health')['healthy'])
        conn.close.assert_called_once()
    def test_failures_close_connection(self):
        for failure in ['socket','http','json']:
            conn=MagicMock();response=conn.getresponse.return_value;response.status=500 if failure=='http' else 200;response.read.return_value=b'invalid'
            if failure=='socket':conn.request.side_effect=OSError('test')
            with self.subTest(failure=failure),patch.object(bridge.http.client,'HTTPConnection',return_value=conn),patch.object(bridge,'password',return_value='test'):
                with self.assertRaises(ValueError):bridge.request('/global/health')
            conn.close.assert_called_once()
