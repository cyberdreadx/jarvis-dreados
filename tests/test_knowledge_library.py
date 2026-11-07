import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import knowledge_library as k
class KnowledgeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  swap=patch.object(k,'DB',Path(self.temp.name)/'docs.sqlite3');swap.start();self.addCleanup(swap.stop)
 def seed(self,pack='threejs',body='Camera aspect ratio changes when resizing the canvas. ' * 150):
  k.store_page(pack,k.PACKS[pack]['urls'][0],'Camera reference',body)
 def test_offline_search_bounded_and_cited(self):
  self.seed()
  with patch.object(k,'fetch',side_effect=AssertionError('Must stay offline')):
   result=k.search('camera aspect ratio','threejs')
  self.assertTrue(result['results']);self.assertLessEqual(len(result['results']),5)
  for hit in result['results']:
   self.assertEqual(hit['version'],'r187 / 0.187.0');self.assertTrue(hit['source'].startswith('https://'));self.assertLessEqual(len(hit['excerpt']),2800)
  self.assertFalse(k.search('camera','python')['results'])
 def test_refresh_replaces_chunks(self):
  self.seed(body='oldcamera '*100);self.seed(body='newcamera '*100)
  self.assertFalse(k.search('oldcamera')['results']);self.assertTrue(k.search('newcamera')['results'])
 def test_input_boundaries(self):
  for pack in ['../../private','unknown']:
   with self.assertRaises(ValueError):k.search('hello',pack)
  self.assertEqual(k.search('" OR * ()')['results'],[])
  with self.assertRaises(ValueError):k.search('x'*501)
  with self.assertRaises(ValueError):k.store_page('threejs','file:///secret','x','y')
 def test_failed_download_keeps_installed_copy(self):
  self.seed()
  with patch.object(k,'fetch',side_effect=OSError('offline')):
   k.install('threejs')
   for _ in range(200):
    if not k.status()['job']['running']:break
    time.sleep(.01)
  self.assertTrue(k.status()['job']['errors']);self.assertTrue(k.search('camera')['results'])
 def test_parser_discards_script_and_navigation(self):
  p=k.Extractor();p.feed('<nav>navigation</nav><main><h1>Camera</h1><script>secret()</script><pre>let x = 1;</pre></main>')
  self.assertIn('let x = 1;',p.text());self.assertNotIn('secret',p.text());self.assertNotIn('navigation',p.text())
 def test_mcp_read_only_surface(self):
  tools=k.mcp_result('tools/list',{})['tools'];self.assertEqual([t['name'] for t in tools],['search_docs'])
  self.assertTrue(tools[0]['annotations']['readOnlyHint']);self.seed()
  reply=k.mcp_result('tools/call',{'name':'search_docs','arguments':{'query':'camera'}})
  self.assertTrue(json.loads(reply['content'][0]['text'])['results'])
  with self.assertRaises(ValueError):k.mcp_result('tools/call',{'name':'install','arguments':{}})
