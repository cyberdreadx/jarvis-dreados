import io,json,tempfile,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch,MagicMock
import build_providers as bp
import opencode_bridge as bridge
class BuildProvidersTests(unittest.TestCase):
 def setUp(self):
  self.previous=bp._saved;bp._saved={'selected':'local','profiles':{}}
 def tearDown(self):bp._saved=self.previous
 def cloud(self,p='openai'):
  return {'provider':p,'model':'test-coding-model','key':'test-secret-123','context':65536,'output':8192,'vision':True}
 def test_encrypted_save_and_public_redaction(self):
  with patch.object(bp.secure_settings,'save') as save:
   result=bp.save(self.cloud());save.assert_called_once();self.assertEqual(result['selected'],'openai');self.assertNotIn('test-secret',json.dumps(result));self.assertTrue(result['profiles']['openai']['has_key'])
   bp.save({**self.cloud(),'key':''});self.assertEqual(bp.profile()[1]['key'],'test-secret-123')
 def test_invalid_input_does_not_persist(self):
  for changes in [{'provider':'bad'},{'model':'bad model'},{'key':'bad key'},{'context':100},{'output':65536},{'vision':'yes'}]:
   with patch.object(bp.secure_settings,'save') as save,self.assertRaises(ValueError):bp.save({**self.cloud(),**changes})
   save.assert_not_called()
 def test_cloud_config_and_context_preserve_permissions(self):
  with patch.object(bp.secure_settings,'save'):bp.save(self.cloud())
  with tempfile.TemporaryDirectory() as directory,patch.object(bridge,'STATE',Path(directory)),patch.object(bridge,'request',return_value={}),patch.object(bp,'relay_url',return_value=('http://127.0.0.1:12345/openai','relay-token')):
   result=bridge.configure_model();cfg=json.loads((Path(directory)/'opencode.json').read_text())
   self.assertEqual(result['providerID'],'openai');self.assertEqual(cfg['model'],'openai/test-coding-model');self.assertNotIn('test-secret',json.dumps(cfg));self.assertEqual({k:v for k,v in cfg['permission'].items() if k not in ('offline_docs_search_docs','preview_check_preview','site_tools_audit_site')},json.loads((bridge.ROOT/'opencode.config.json').read_text())['permission']);self.assertEqual(cfg['permission']['offline_docs_search_docs'],'allow');self.assertEqual(bridge.build_context([])['limit'],65536)
 def test_busy_guard_before_saving(self):
  with patch.object(bridge,'start'),patch.object(bridge,'request',return_value={'ses_test':{'type':'busy'}}),patch.object(bp,'save') as save:
   with self.assertRaisesRegex(ValueError,'Stop'):bridge.action({'action':'save_provider',**self.cloud()})
   save.assert_not_called()
 def test_relay_auth_routes_and_stream(self):
  with patch.object(bp.secure_settings,'save'):bp.save(self.cloud())
  base,token=bp.relay_url('openai')
  for suffix,headers,expected in [('responses',{},403),('unknown',{'Authorization':'Bearer '+token},404)]:
   with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(urllib.request.Request(base+'/'+suffix,data=b'{}',headers=headers))
   self.assertEqual(caught.exception.code,expected);caught.exception.close()
  response=MagicMock();response.__enter__.return_value=response;response.code=200;response.headers={'Content-Type':'text/event-stream'};response.read1.side_effect=[b'data: test\n\n',b'']
  opener=MagicMock();opener.open.return_value=response
  # Use a prebuilt client opener so only the relay's upstream transport is mocked.
  client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
  with patch.object(bp.urllib.request,'build_opener',return_value=opener):
   with client.open(urllib.request.Request(base+'/responses',data=b'{"stream":true}',headers={'Authorization':'Bearer '+token})) as result:self.assertEqual(result.read(),b'data: test\n\n')
  request=opener.open.call_args.args[0];self.assertEqual(request.full_url,'https://api.openai.com/v1/responses');self.assertEqual(request.get_header('Authorization'),'Bearer test-secret-123')
if __name__=='__main__':unittest.main()
