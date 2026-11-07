import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import opencode_bridge as b
class BuildPolicyTests(unittest.TestCase):
 def check_request(self,command,workdir=None):
  permission={'id':'check1','sessionID':'ses_test','permission':'bash','patterns':['*'],'tool':{'messageID':'msg_test','callID':'call_test'}}
  inputs={'command':command}
  if workdir is not None:inputs['workdir']=workdir
  messages=[{'info':{'id':'msg_test','sessionID':'ses_test'},'parts':[{'type':'tool','callID':'call_test','tool':'bash','state':{'status':'running','input':inputs}}]}]
  return permission,messages
 def test_only_exact_checks_in_project(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'project';root.mkdir();(root/'package.json').write_text(json.dumps({'scripts':{'test':'vitest run','build':'vite build'}}))
   for command in ['npm test','npm run build','pnpm run build','yarn test','python -m pytest -q','node --test']:
    p,m=self.check_request(command,str(root));self.assertTrue(b.safe_project_check(p,root,m),command)
   for command in ['npm install','npm ci','npm exec vite build','npx vite build','git push','rm -rf .','npm test && git push','npm test; rm foo','npm test\nwhoami','npm test > ../out','npm --prefix ../other test','pytest ../other','pytest --override-ini=addopts=x','npm run build -- --outDir ../other','$(npm test)','npm test ']:
    p,m=self.check_request(command);self.assertFalse(b.safe_project_check(p,root,m),command)
   for directory in [str(Path(tmp)),'..','../other','',str(root/'../outside')]:
    p,m=self.check_request('npm test',directory);self.assertFalse(b.safe_project_check(p,root,m),directory)
 def test_checks_require_matching_tool_session_and_script(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   p,m=self.check_request('npm test');self.assertFalse(b.safe_project_check(p,root,m))
   p,m=self.check_request('pytest');p['tool']['callID']='another';self.assertFalse(b.safe_project_check(p,root,m))
   p,m=self.check_request('pytest');m[0]['info']['sessionID']='ses_other';self.assertFalse(b.safe_project_check(p,root,m))
   p,m=self.check_request('pytest');m[0]['parts'][0]['state']['input']['cwd']='../other';self.assertFalse(b.safe_project_check(p,root,m))
   p,m=self.check_request('pytest');p['permission']='external_directory';self.assertFalse(b.safe_project_check(p,root,m))
 def test_poll_check_toggle_and_terminal_review(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'demo').mkdir()
   permission,messages=self.check_request('python -m pytest')
   pending=[permission,{'id':'shell1','sessionID':'ses_test','permission':'bash','patterns':['git push']}]
   def response(path,*args,**kwargs):
    return {'/session/ses_test':{'directory':str(root/'demo')},'/session/ses_test/message':messages,'/permission':pending,'/session/status':{},'/session/ses_test/diff':[]}.get(path,{})
   with patch.object(b,'PROJECTS',root),patch.object(b,'request',side_effect=response) as req,patch.object(b,'build_context',return_value={}):
    result=b.action({'action':'poll','project':'demo','session':'ses_test','auto_checks':False})
    self.assertEqual(len(result['permissions']),2)
    self.assertFalse(any('/reply' in str(c) for c in req.call_args_list))
    result=b.action({'action':'poll','project':'demo','session':'ses_test','auto_checks':True})
    self.assertEqual([p['id'] for p in result['permissions']],['shell1'])
    req.assert_any_call('/permission/check1/reply',{'reply':'once'},name='demo')
    self.assertFalse(any('/shell1/reply' in str(c) for c in req.call_args_list))
 def test_paths_and_commands(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'project';root.mkdir()
   for path in ['index.html','src/app.js',str(root/'hello.py')]:
    self.assertTrue(b.safe_project_edit({'permission':'edit','patterns':[path]},root))
   for path in ['../outside.txt','*','src/*.js','.env','opencode.json','.opencode/config.json',str(Path(tmp)/'other.txt')]:
    self.assertFalse(b.safe_project_edit({'permission':'edit','patterns':[path]},root),path)
   self.assertFalse(b.safe_project_edit({'permission':'bash','patterns':['index.html']},root))
   self.assertFalse(b.safe_project_edit({'permission':'edit','patterns':[]},root))
   self.assertFalse(b.safe_project_edit({'permission':'edit','patterns':['ok.txt','../bad']},root))
 def test_configuration(self):
  d=json.loads(Path('opencode.config.json').read_text())
  self.assertEqual(d['permission']['bash'],'ask')
  self.assertEqual(d['permission']['edit'],'ask')
  self.assertEqual(d['permission']['external_directory'],'deny')
  self.assertTrue(d['compaction']['auto'])
  self.assertFalse(d['compaction']['prune'])
  self.assertGreater(d['compaction']['reserved'],4096)
 def test_poll_only_approves_selected_session_edit_once(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'demo').mkdir()
   pending=[{'id':'edit1','sessionID':'ses_test','permission':'edit','patterns':['index.html']},{'id':'shell1','sessionID':'ses_test','permission':'bash','patterns':['echo hi']},{'id':'other1','sessionID':'ses_other','permission':'edit','patterns':['index.html']}]
   def response(path,*args,**kwargs):
    return {'/session/ses_test':{'directory':str(root/'demo')},'/session/ses_test/message':[], '/permission':pending,'/session/status':{},'/session/ses_test/diff':[]}.get(path,{})
   with patch.object(b,'PROJECTS',root),patch.object(b,'request',side_effect=response) as req,patch.object(b,'build_context',return_value={}):
    result=b.action({'action':'poll','project':'demo','session':'ses_test','auto_edits':True})
    self.assertEqual([p['id'] for p in result['permissions']],['shell1'])
    req.assert_any_call('/permission/edit1/reply',{'reply':'once'},name='demo')
    self.assertFalse(any('/shell1/reply' in str(c) or '/other1/reply' in str(c) for c in req.call_args_list))
 def test_explicit_terminal_mode_allows_general_commands(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for command in ['npm install','git status --short','python scripts/generate.py','npm run build && node check.js']:
    permission,messages=self.check_request(command,str(root))
    self.assertFalse(b.safe_project_check(permission,root,messages))
    self.assertTrue(b.project_command_allowed(permission,root,messages,checks_only=False))
   for directory in ['..','../outside','']:
    permission,messages=self.check_request('npm install',directory)
    self.assertFalse(b.project_command_allowed(permission,root,messages,checks_only=False))
   permission,messages=self.check_request('npm install')
   permission['permission']='external_directory'
   self.assertFalse(b.project_command_allowed(permission,root,messages,checks_only=False))
 def test_terminal_requires_actual_matching_running_tool(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for mutation in ['call','session','finished','unknown_input']:
    permission,messages=self.check_request('npm install')
    if mutation=='call':permission['tool']['callID']='wrong'
    if mutation=='session':messages[0]['info']['sessionID']='wrong'
    if mutation=='finished':messages[0]['parts'][0]['state']['status']='completed'
    if mutation=='unknown_input':messages[0]['parts'][0]['state']['input']['cwd']='..'
    self.assertFalse(b.project_command_allowed(permission,root,messages,checks_only=False))
 def test_terminal_toggle_scoped_once_and_disabled_by_default(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'demo').mkdir()
   permission,messages=self.check_request('npm install')
   other={**permission,'id':'other','sessionID':'ses_other'}
   pending=[permission,other,{'id':'external','sessionID':'ses_test','permission':'external_directory'}]
   def response(path,*args,**kwargs):
    return {'/session/ses_test':{'directory':str(root/'demo')},'/session/ses_test/message':messages,'/permission':pending,'/session/status':{},'/session/ses_test/diff':[]}.get(path,{})
   with patch.object(b,'PROJECTS',root),patch.object(b,'request',side_effect=response) as req,patch.object(b,'build_context',return_value={}):
    for value in [None,False,'true']:
     result=b.action({'action':'poll','project':'demo','session':'ses_test','auto_bash':value})
     self.assertEqual(len(result['permissions']),2)
    self.assertFalse(any('/reply' in str(call) for call in req.call_args_list))
    result=b.action({'action':'poll','project':'demo','session':'ses_test','auto_bash':True})
    self.assertEqual([p['id'] for p in result['permissions']],['external'])
    req.assert_any_call('/permission/check1/reply',{'reply':'once'},name='demo')
    self.assertFalse(any('/permission/other/reply' in str(call) for call in req.call_args_list))
 def test_broken_approval_metadata_keeps_chat_visible(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'demo').mkdir()
   messages=[{'info':{'role':'assistant'},'parts':[{'type':'text','text':'Researching gameplay'}]}]
   def response(path,*args,**kwargs):
    if path=='/permission':raise ValueError('HTTP 400: Expected JSON value, got undefined at metadata timeout')
    return {'/session/ses_test':{'directory':str(root/'demo')},'/session/ses_test/message':messages,'/session/status':{'ses_test':{'type':'busy'}},'/session/ses_test/diff':[]}.get(path,{})
   with patch.object(b,'PROJECTS',root),patch.object(b,'request',side_effect=response) as req,patch.object(b,'build_context',return_value={}):
    result=b.action({'action':'poll','project':'demo','session':'ses_test','auto_bash':True})
    self.assertEqual(result['messages'],messages)
    self.assertIn('Stop this task',result['permission_error'])
    self.assertFalse(any('/reply' in str(call) for call in req.call_args_list))
class SessionPermissionTests(unittest.TestCase):
 def setUp(self):
  temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
  self.root=Path(temporary.name)
  for name in ('demo','other'):(self.root/name).mkdir()
  self.sessions={'ses_test':'demo','ses_other':'demo','ses_second':'other'}
  self.pending={'demo':[],'other':[]};self.replies=[];self.failures=set();self.grants={}
  for target,value in [('PROJECTS',self.root),('_session_permissions',self.grants)]:
   mocked=patch.object(b,target,value);mocked.start();self.addCleanup(mocked.stop)
  mocked=patch.object(b,'build_context',return_value={});mocked.start();self.addCleanup(mocked.stop)
  mocked=patch.object(b,'request',side_effect=self.respond);self.request=mocked.start();self.addCleanup(mocked.stop)
 def respond(self,path,data=None,name=None,**kwargs):
  if path=='/permission':return list(self.pending[name])
  if path.startswith('/permission/') and path.endswith('/reply'):
   ident=path.split('/')[2];self.replies.append((name,ident,data['reply']))
   if ident in self.failures:raise ValueError('OpenCode connection failed')
   self.pending[name]=[p for p in self.pending[name] if p['id']!=ident]
   return {'ok':True}
  if path=='/session/status':return {}
  if path.endswith('/message') or path.endswith('/diff'):return []
  if path.startswith('/session/'):
   return {'directory':str(self.root/self.sessions[path.split('/')[2]])}
  self.fail('Unexpected OpenCode request: '+path)
 def add(self,ident,kind='webfetch',session='ses_test',project='demo'):
  permission={'id':ident,'sessionID':session,'permission':kind,'patterns':['https://example.com/'+ident]}
  self.pending[project].append(permission);return permission
 def approve(self,ident,reply='session',session='ses_test',project='demo'):
  return b.action({'action':'permission','project':project,'session':session,'permission':ident,'reply':reply})
 def poll(self,session='ses_test',project='demo'):
  return b.action({'action':'poll','project':project,'session':session})
 def test_session_remembers_only_selected_tool_and_session_using_once(self):
  self.add('first');self.assertEqual(self.approve('first'),{'ok':True})
  self.add('next');self.add('different-tool','bash');self.add('other-session',session='ses_other')
  result=self.poll()
  self.assertEqual([p['id'] for p in result['permissions']],['different-tool'])
  self.assertEqual([p['id'] for p in self.poll('ses_other')['permissions']],['other-session'])
  self.assertEqual(self.replies,[('demo','first','once'),('demo','next','once')])
  # A new client poll requires no remembered browser flags to use the same grant.
  self.add('after-refresh');self.poll()
  self.assertEqual(self.replies[-1],('demo','after-refresh','once'))
 def test_session_grants_do_not_cross_projects_even_with_same_session_identifier(self):
  self.add('first');self.approve('first')
  self.sessions['ses_test']='other';self.add('other-project',project='other')
  result=self.poll(project='other')
  self.assertEqual([p['id'] for p in result['permissions']],['other-project'])
  self.assertEqual(self.replies,[('demo','first','once')])
 def test_once_and_reject_do_not_remember_future_requests(self):
  for reply in ('once','reject'):
   with self.subTest(reply=reply):
    self.add(reply);self.approve(reply,reply)
    self.add(reply+'-later');result=self.poll()
    self.assertIn(reply+'-later',[p['id'] for p in result['permissions']])
    self.assertEqual(self.replies[-1],('demo',reply,reply))
    self.assertEqual(self.grants,{})
 def test_stale_foreign_and_invalid_replies_cannot_create_grants(self):
  self.add('pending');self.add('foreign',session='ses_other')
  cases=[('missing','session','ses_test','demo'),('foreign','session','ses_test','demo'),
         ('pending','always','ses_test','demo'),('pending','session','ses_test','other'),
         ('pending','session','bad-session','demo')]
  for ident,reply,session,project in cases:
   with self.subTest(case=(ident,reply,session,project)),self.assertRaises(ValueError):
    self.approve(ident,reply,session,project)
  self.assertEqual(self.replies,[]);self.assertEqual(self.grants,{})
 def test_session_approval_requires_a_tool_type(self):
  for kind in (None,'',[],{}):
   with self.subTest(kind=kind):
    self.pending['demo']=[];self.add('malformed',kind)
    with self.assertRaisesRegex(ValueError,'tool type'):self.approve('malformed')
  self.assertEqual(self.replies,[]);self.assertEqual(self.grants,{})
 def test_failed_initial_session_approval_does_not_remember(self):
  self.add('failure');self.failures.add('failure')
  with self.assertRaisesRegex(ValueError,'connection failed'):self.approve('failure')
  self.assertEqual(self.grants,{})
  self.failures.clear();result=self.poll()
  self.assertEqual([p['id'] for p in result['permissions']],['failure'])
  self.assertEqual(self.replies,[('demo','failure','once')])
 def test_failed_remembered_approval_stays_visible_and_stops_retrying(self):
  self.add('first');self.approve('first')
  self.add('failure');self.add('later');self.failures.add('failure')
  result=self.poll()
  self.assertEqual([p['id'] for p in result['permissions']],['failure','later'])
  self.assertTrue(any('Session approval for webfetch failed' in warning for warning in result['warnings']))
  calls=list(self.replies);self.poll();self.assertEqual(self.replies,calls)
  self.failures.clear();self.approve('failure');self.poll()
  self.assertEqual(self.replies[-1],('demo','later','once'))
 def test_process_reset_requires_session_approval_again(self):
  self.add('first');self.approve('first');self.add('after-restart')
  with patch.object(b,'_session_permissions',{}):result=self.poll()
  self.assertEqual([p['id'] for p in result['permissions']],['after-restart'])
  self.assertEqual(self.replies,[('demo','first','once')])

if __name__=='__main__':unittest.main()
