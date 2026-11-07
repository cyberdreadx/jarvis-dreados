import unittest
from unittest.mock import patch,MagicMock
import opencode_bridge as bridge
class OpenCodeTransportTests(unittest.TestCase):
    def setUp(self):
        selected=patch("build_providers.profile",return_value=("local",{}))
        selected.start();self.addCleanup(selected.stop)
    def test_usage_uses_latest_step_not_session_total(self):
        messages=[{'info':{'role':'assistant','tokens':{'input':5000,'output':100}}},
                  {'info':{'role':'assistant','tokens':{'input':1200,'output':50,'reasoning':10,'cache':{'read':200,'write':100}}}}]
        with patch('context_memory.context_limit',return_value=(32768,True)):
            self.assertEqual(bridge.build_context(messages)['used'],1560)
            self.assertIsNone(bridge.build_context([])['used'])
    def test_rejected_request_usage(self):
        messages=[{'info':{'error':{'data':{'message':'request (8293 tokens) exceeds the available context size (8192 tokens)'}}}}]
        with patch('context_memory.context_limit',return_value=(32768,True)):
            value=bridge.build_context(messages)
            self.assertEqual((value['used'],value['limit']),(8293,8192))
    def test_context_guard_does_not_write_config(self):
        with patch('providers.config',return_value=('local',{'model':'test','base_url':'http://127.0.0.1:1234/v1','key':''})),patch('context_memory.context_limit',return_value=(8192,True)):
            with self.assertRaisesRegex(ValueError,'32,768'):bridge.configure_model()
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
