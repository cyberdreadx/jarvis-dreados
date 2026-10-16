import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
import media_library as media

class MediaLibrary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(media, 'DB', Path(self.temp.name)/'media.sqlite3')
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.quotes = patch.object(media, '_quotes', {})
        self.quotes.start(); self.addCleanup(self.quotes.stop)

    def catalog(self):
        response = {'result': {'content': [{'type':'text','text':json.dumps({'engines':[{'models':[{'id':'comfy-zimage','credits_per_unit':3}]}]})}]}}
        with patch('mcp_client.public_connections', return_value=[{'id':'g','url':'https://api.gltch.app','status':'connected'}]), patch('mcp_client.call', return_value=response) as call:
            result=media.catalog()
            self.assertEqual(call.call_args.args[0]['tool'],'list_models')
            return result

    def test_catalog_review_and_deduplicated_submission(self):
        catalog=self.catalog()
        payload={'approved':True,'request_id':str(uuid.uuid4()),'ticket':catalog['ticket'],'model':'zimage','prompt':'Jungle city','shape':'square'}
        with patch('media_library.threading.Thread') as worker:
            first=media.submit(payload); second=media.submit(payload)
            self.assertEqual(first,second)
            self.assertEqual(worker.call_count,1)
            self.assertEqual(first['credits'],3)
            self.assertEqual(first['arguments']['width'],1024)
        self.assertEqual(len(media.listing()['items']),1)

    def test_approval_and_price_expiry(self):
        with self.assertRaises(ValueError):media.submit({})
        catalog=self.catalog()
        media._quotes[catalog['ticket']]['created']=0
        with patch('media_library.threading.Thread') as worker:
            with self.assertRaises(ValueError):media.submit({'approved':True,'request_id':str(uuid.uuid4()),'ticket':catalog['ticket'],'model':'zimage','prompt':'test','shape':'square'})
            worker.assert_not_called()

    def test_restart_does_not_resubmit_paid_work(self):
        media.put({'id':'running','created':1,'status':'running','kind':'image'})
        with patch('mcp_client.call') as call:
            media.recover();call.assert_not_called()
        self.assertEqual(media.get('running')['status'],'unknown')

    def test_worker_saves_result_and_library_survives_reopen(self):
        media.put({'id':'job','created':1,'status':'queued','kind':'image','arguments':{'prompt':'test'}})
        with patch('mcp_client.call',return_value={'result':{'content':[{'type':'text','text':'https://cdn.example/image.png\n3 credits used'}]}}):media._run('job','g')
        item=media.get('job')
        self.assertEqual(item['status'],'complete')
        self.assertEqual(item['assets'][0]['url'],'https://cdn.example/image.png')
        self.assertEqual(media.listing()['items'][0],item)

    def test_timeout_is_unknown_not_retried(self):
        media.put({'id':'job','created':1,'status':'queued','arguments':{}})
        with patch('mcp_client.call',side_effect=ValueError('timeout')) as call:media._run('job','g')
        self.assertEqual(call.call_count,1)
        self.assertEqual(media.get('job')['status'],'unknown')

    def test_drafts_and_unsafe_urls(self):
        item=media.action({'action':'draft','text':'A saved post','brief':'Launch','format':'post'})['item']
        self.assertEqual(media.get(item['id'])['text'],'A saved post')
        fields=media.result_fields({'content':[{'type':'resource_link','uri':'javascript:alert(1)'},{'type':'text','text':'https://user:secret@example.com/image.png'}]},'generate_image')
        self.assertEqual(fields['assets'],[])

    def test_video_capture_and_service_error(self):
        item=media.capture({'tool':'generate_video','arguments':{'prompt':'Animate'}},{'connection':'GLTCH','result':{'content':[{'type':'text','text':'https://cdn.example/video.mp4'}]}})
        self.assertEqual(item['kind'],'video');self.assertEqual(item['assets'][0]['kind'],'video')
        item=media.capture({'tool':'generate_image','arguments':{}},{'connection':'GLTCH','result':{'isError':True,'content':[{'type':'text','text':'Not enough credits'}]}})
        self.assertEqual(item['status'],'failed')
