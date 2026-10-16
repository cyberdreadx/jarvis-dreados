import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import build_workspace as w
import opencode_bridge as bridge

class WorkspaceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def test_read_create_save_conflict(self):
  created=w.save(self.root,'src/test.py','print(1)',None,create=True)
  saved=w.save(self.root,'src/test.py','print(2)',created['revision'])
  self.assertEqual(w.read(self.root,'src/test.py')['content'],'print(2)')
  with self.assertRaisesRegex(ValueError,'changed'):w.save(self.root,'src/test.py','stale',created['revision'])
  self.assertEqual(w.read(self.root,'src/test.py')['revision'],saved['revision'])
  with self.assertRaises(ValueError):w.save(self.root,'src/test.py','',None,create=True)
 def test_path_boundaries(self):
  for name in ['../secret','C:/secret','a/../../secret','.env','.env.local','a/.git/config','a:stream','CON.txt','file.','/abs','a//b','.dreados-history/test']:
   with self.subTest(name=name),self.assertRaises(ValueError):w.safe_path(self.root,name)
 def test_tree_and_preview(self):
  w.save(self.root,'index.html','<h1>Hello</h1>',None,create=True)
  (self.root/'node_modules').mkdir();(self.root/'node_modules/private.js').write_text('secret')
  (self.root/'.env').write_text('secret')
  self.assertEqual([f['path'] for f in w.tree(self.root)['files']],['index.html'])
  ticket=w.preview(self.root,'index.html')['url'].split('/')[2]
  self.assertEqual(w.preview_file(ticket,'index.html')[0],b'<h1>Hello</h1>')
  with self.assertRaises(ValueError):w.preview_file(ticket,'.env')
  with patch('build_workspace.time.monotonic',return_value=10**12):
   with self.assertRaises(ValueError):w.preview_file(ticket,'index.html')
 def test_edit_without_opencode_session(self):
  with patch.object(bridge,'PROJECTS',self.root):
   (self.root/'demo').mkdir()
   result=bridge.action({'action':'new_file','project':'demo','path':'notes.md','content':'hello'})
   self.assertEqual(result['content'],'hello')
   self.assertEqual(bridge.action({'action':'files','project':'demo'})['files'][0]['path'],'notes.md')

 def test_preview_drafts_do_not_write_disk(self):
  w.save(self.root,'index.html','saved',None,create=True)
  w.save(self.root,'style.css','old',None,create=True)
  ticket=w.preview(self.root,'index.html',{'index.html':'draft','style.css':'new'})['url'].split('/')[2]
  self.assertEqual(w.preview_file(ticket,'index.html')[0],b'draft')
  self.assertEqual(w.preview_file(ticket,'style.css')[0],b'new')
  self.assertEqual((self.root/'index.html').read_text(),'saved')
  with self.assertRaises(ValueError):w.preview(self.root,'index.html',{'../outside.html':'bad'})

 def test_start_reuses_existing_opencode(self):
  with patch.object(bridge,'request',return_value={'healthy':True,'version':'test'}),patch.object(bridge.subprocess,'Popen') as launch:
   self.assertTrue(bridge.start()['healthy'])
   launch.assert_not_called()
 def test_start_does_not_launch_over_occupied_port(self):
  with patch.object(bridge,'request',side_effect=ValueError('health failed')),patch.object(bridge.socket,'create_connection'),patch.object(bridge.time,'sleep'),patch.object(bridge.subprocess,'Popen') as launch:
   with self.assertRaisesRegex(ValueError,'already occupied'):bridge.start()
   launch.assert_not_called()
