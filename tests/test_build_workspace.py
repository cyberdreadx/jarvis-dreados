import json,tempfile,unittest
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
  for name in ['a*b','a?b','a[1]','say"hi"','$HOME','a|b','a<b','a\tb']:
   with self.subTest(name=name),self.assertRaises(ValueError):w.safe_path(self.root,name)
 def test_reveal_opens_file_manager_only_inside_project(self):
  (self.root/'samples').mkdir();(self.root/'samples/a b.mp3').write_bytes(b'x')
  with patch.object(w.subprocess,'Popen') as popen:
   w.reveal(self.root,'samples/a b.mp3');w.reveal(self.root,'samples');w.reveal(self.root)
   for name in ['../x','samples/missing.mp3','C:/Windows']:
    with self.subTest(name=name),self.assertRaises(ValueError):w.reveal(self.root,name)
  commands=[c.args[0] for c in popen.call_args_list]
  self.assertEqual(len(commands),3)
  if w.os.name=='nt':
   self.assertEqual(commands[0],f'explorer.exe /select,"{self.root.resolve()/"samples"/"a b.mp3"}"')
   self.assertEqual(commands[1],f'explorer.exe "{self.root.resolve()/"samples"}"')
   self.assertEqual(commands[2],f'explorer.exe "{self.root.resolve()}"')
 def test_common_music_and_document_names_are_listed(self):
  names=["samples/Jack_Hylton/Alexander's_Ragtime_Band.mp3","samples/Wilson,_Weinberg/Gems (Live) & More!.mp3","Café/notes.txt"]
  for name in names:
   path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x')
   self.assertEqual(w.safe_path(self.root,name),self.root.resolve()/name)
  self.assertEqual(sorted(f['path'] for f in w.tree(self.root)['files']),sorted(names))
 def test_large_javascript_is_viewable_without_allowing_large_writes(self):
  content='// library\n'*(w.LIMIT//10)
  (self.root/'library.js').write_text(content,encoding='utf-8',newline='')
  result=w.read(self.root,'library.js')
  self.assertEqual(result['content'],content)
  self.assertTrue(result['readonly'])
  with self.assertRaises(ValueError):w.save(self.root,'library.js',content,result['revision'])
  with patch.object(w,'VIEW_LIMIT',10):
   with self.assertRaisesRegex(ValueError,'viewer limit'):w.read(self.root,'library.js')
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
 def _stale_env(self,status):
  pid_file=self.root/'server.pid'
  calls=[{'healthy':True},status,{'healthy':True,'version':'new'}]
  def respond(path,*a,**k):return calls.pop(0)
  return pid_file,respond
 def test_connect_restarts_opencode_that_predates_plugin_changes(self):
  pid_file,respond=self._stale_env({})
  with patch.object(bridge,'PID_FILE',pid_file),patch.object(bridge,'request',side_effect=respond),\
       patch.object(bridge,'_stale_pid',return_value=4242),patch.object(bridge,'_kill') as kill,\
       patch.object(bridge.socket,'create_connection',side_effect=OSError),patch.object(bridge.subprocess,'Popen') as launch:
   launch.return_value.poll.return_value=None;launch.return_value.pid=999
   self.assertEqual(bridge.start(restart_stale=True)['version'],'new')
   kill.assert_called_once_with(4242);launch.assert_called_once()
   self.assertEqual(json.loads(pid_file.read_text())['pid'],999)
 def test_connect_never_restarts_opencode_while_a_task_runs(self):
  pid_file,respond=self._stale_env({'s1':{'type':'busy'}})
  with patch.object(bridge,'PID_FILE',pid_file),patch.object(bridge,'request',side_effect=respond),\
       patch.object(bridge,'_stale_pid',return_value=4242),patch.object(bridge,'_kill') as kill,patch.object(bridge.subprocess,'Popen') as launch:
   self.assertTrue(bridge.start(restart_stale=True)['healthy'])
   kill.assert_not_called();launch.assert_not_called()
 def test_stale_pid_only_when_plugins_changed_after_launch(self):
  pid_file=self.root/'server.pid'
  with patch.object(bridge,'PID_FILE',pid_file),patch.object(bridge,'_code_stamp',return_value=100.0),\
       patch.object(bridge.subprocess,'run') as run:
   run.return_value.stdout='opencode.exe  4242 Console'
   self.assertIsNone(bridge._stale_pid())  # no record of a launch: leave it alone
   pid_file.write_text(json.dumps({'pid':4242,'stamp':100.0}))
   self.assertIsNone(bridge._stale_pid())  # nothing changed since launch
   pid_file.write_text(json.dumps({'pid':4242,'stamp':50.0}))
   self.assertEqual(bridge._stale_pid(),4242)  # plugins changed after launch
   run.return_value.stdout='notepad.exe 4242 Console'
   if bridge.os.name=='nt':self.assertIsNone(bridge._stale_pid())  # PID reused by another program
 def test_start_does_not_launch_over_occupied_port(self):
  with patch.object(bridge,'request',side_effect=ValueError('health failed')),patch.object(bridge.socket,'create_connection'),patch.object(bridge.time,'sleep'),patch.object(bridge.subprocess,'Popen') as launch:
   with self.assertRaisesRegex(ValueError,'already occupied'):bridge.start()
   launch.assert_not_called()
