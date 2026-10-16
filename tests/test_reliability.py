import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import secure_settings
import providers
import chat_tools

class Reliability(unittest.TestCase):
    def test_encrypted_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(secure_settings,'PATH',Path(folder)/'settings.dpapi'):
            secure_settings.save('test',{'key':'secret-test-value'})
            self.assertNotIn(b'secret-test-value',secure_settings.PATH.read_bytes())
            self.assertEqual(secure_settings.read()['test']['key'],'secret-test-value')
            secure_settings.save('second',{'value':2})
            self.assertEqual(secure_settings.read()['test']['key'],'secret-test-value')

    def test_stream_only_answer_not_reasoning(self):
        events=[{'choices':[{'delta':{'reasoning_content':'private reasoning'}}]}, {'choices':[{'delta':{'content':'Hello '}}]}, {'choices':[{'delta':{'content':'world'}}]}]
        raw=''.join('data: '+json.dumps(x)+'\n\n' for x in events)+'data: [DONE]\n'
        with patch.object(providers,'_settings',{'local':{'model':'test','base_url':'http://localhost:1234/v1','key':''}}), patch('providers.local_open') as network:
            network.return_value.__enter__.return_value=io.BytesIO(raw.encode())
            chunks=[]
            answer=providers.reply('Hi',[],'local',on_delta=chunks.append,strict=True)
            self.assertEqual(answer,'Hello world');self.assertEqual(chunks,['Hello ','world'])
            self.assertTrue(json.loads(network.call_args.args[0].data)['stream'])

    def test_stream_cancel(self):
        with patch.object(providers,'_settings',{'local':{'model':'test','base_url':'http://localhost:1234/v1','key':''}}), patch('providers.local_open') as network:
            network.return_value.__enter__.return_value=io.BytesIO(b'data: [DONE]\n')
            with self.assertRaises(providers.ProviderError): providers.reply('Hi',[],'local',on_delta=lambda x:None,cancelled=lambda:True,strict=True)

    def test_proposal_never_runs_without_approval_and_runs_once(self):
        connections=[{'id':'one','name':'Demo','status':'connected','tools':[{'name':'generate','inputSchema':{'required':['prompt']}}]}]
        with patch.object(chat_tools,'pending',{}), patch('mcp_client.public_connections',return_value=connections), patch('providers.reply',return_value=json.dumps({'connection_id':'one','tool':'generate','arguments':{'prompt':'test'}})), patch('mcp_client.call',return_value={'connection':'Demo','result':{'content':[{'type':'text','text':'done'}]}}) as call:
            proposal,_=chat_tools.propose('make image',[],'local')
            call.assert_not_called()
            self.assertEqual(chat_tools.approve(proposal['id'])['reply'],'done')
            with self.assertRaises(ValueError):chat_tools.approve(proposal['id'])
            self.assertEqual(call.call_count,1)
