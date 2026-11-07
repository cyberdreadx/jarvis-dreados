import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import opencode_bridge as b
class RecoveryTests(unittest.TestCase):
 def result(self,info=None,parts=None,status='idle'):
  messages=[{'info':{'role':'user'},'parts':[]}]
  if info is not None:messages.append({'info':{'role':'assistant',**info},'parts':parts or []})
  return b.task_recovery(messages,{'type':status})
 def test_idle_is_not_success(self):
  self.assertEqual(self.result()['label'],'Interrupted')
  self.assertEqual(self.result({})['label'],'Awaiting summary')
  self.assertEqual(self.result({'finish':'length'})['label'],'Output limit reached')
  self.assertEqual(self.result({'error':{'name':'MessageAbortedError'}})['label'],'Stopped')
 def test_running_never_offers_continue(self):
  self.assertFalse(self.result({'error':{'name':'Error'}},status='busy')['can_continue'])
 def test_failed_and_finished_turns(self):
  self.assertTrue(self.result({},[{'type':'tool','tool':'write','state':{'status':'error'}}])['can_continue'])
  self.assertEqual(self.result({},[{'type':'text','text':'Done; tests passed.'}])['label'],'Turn finished')
 def test_busy_send_rejected_before_model_or_side_effects(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'demo').mkdir()
   def response(path,*args,**kwargs):return {'/session/ses_test':{'directory':str(root/'demo')},'/session/status':{'ses_test':{'type':'busy'}}}.get(path,{})
   with patch.object(b,'PROJECTS',root),patch.object(b,'request',side_effect=response) as req,patch.object(b,'configure_model') as configure:
    with self.assertRaisesRegex(ValueError,'already working'):b.action({'action':'send','project':'demo','session':'ses_test','prompt':'again'})
    configure.assert_not_called();self.assertFalse(any('prompt_async' in str(c) for c in req.call_args_list))
 def test_diff_failure_does_not_drop_chat(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'demo').mkdir()
   messages=[{'info':{'role':'user'},'parts':[]}]
   def response(path,*args,**kwargs):
    if path.endswith('/diff'):raise ValueError('Diff unavailable')
    return {'/session/ses_test':{'directory':str(root/'demo')},'/session/ses_test/message':messages,'/session/status':{},'/permission':[]}.get(path,{})
   with patch.object(b,'PROJECTS',root),patch.object(b,'request',side_effect=response),patch.object(b,'build_context',return_value={}):
    result=b.action({'action':'poll','project':'demo','session':'ses_test'})
    self.assertEqual(result['messages'],messages);self.assertIsNone(result['diff']);self.assertTrue(result['warnings']);self.assertTrue(result['recovery']['can_continue'])

class ContextRecoveryTests(unittest.TestCase):
 def user(self,text,**info):
  return {'info':{'role':'user',**info},'parts':[{'type':'text','text':text}]}
 def failure(self,error=None):
  return {'info':{'role':'assistant','error':error or {'name':'ContextOverflowError'}},'parts':[]}
 def wrapped(self,text):
  return ('DreadOS project directory: C:\\projects\\demo\nUse absolute file paths inside this directory.\n\nUser request:\n'
          +text+'\n\nThe user has this project file open: lib/three.module.js. Read its current disk contents before editing.')
 def test_provider_context_errors_offer_fresh_session(self):
  errors=[
   {'name':'ContextOverflowError'},
   {'name':'ContextWindowExceededError'},
   {'name':'APIError','data':{'message':'The request (136065 tokens) exceeds the available context size (32768 tokens).'}},
   {'name':'APIError','data':{'message':'maximum context length is 32768 tokens'}},
   {'name':'APIError','data':{'message':'context_length_exceeded'}},
   {'name':'APIError','data':{'message':'prompt is too long: 140000 tokens > 32768 maximum'}},
  ]
  for error in errors:
   with self.subTest(error=error):
    result=b.task_recovery([self.user('Improve the building'),self.failure(error)],{'type':'idle'})
    self.assertEqual(result.get('action'),'recover_context');self.assertTrue(result['can_continue'])
 def test_unrelated_errors_do_not_trigger_context_recovery(self):
  for error in [None,{}, {'name':'MessageAbortedError'}, {'name':'APIError','data':{'message':'Rate limit exceeded. Try again later.'}}, {'name':'APIError','data':{'message':'Failed to decode model output'}}, {'name':'APIError','data':{'message':'Context is unavailable while the server is disconnected.'}}]:
   with self.subTest(error=error):self.assertFalse(b.context_overflow(error))
 def test_only_latest_turn_failure_triggers_recovery(self):
  success={'info':{'role':'assistant','finish':'stop'},'parts':[{'type':'text','text':'Verified saved files.'}]}
  messages=[self.user('Build a tower'),self.failure()]
  self.assertEqual(b.task_recovery(messages,{'type':'idle'}).get('action'),'recover_context')
  for tail in [[success],[self.user('Fix the window'),success],[self.user('What changed?')]]:
   with self.subTest(tail=tail):self.assertNotEqual(b.task_recovery(messages+tail,{'type':'idle'}).get('action'),'recover_context')
 def test_handoff_uses_human_requests_and_removes_internal_wrapper(self):
  messages=[self.user(self.wrapped('Build a tower with warm window lights.')),
            self.user('SUMMARY SHOULD NOT LEAK',summary=True),
            {'info':{'role':'user'},'parts':[{'type':'compaction','auto':True}]},
            {'info':{'role':'user'},'parts':[{'type':'text','synthetic':True,'text':'SYNTHETIC SHOULD NOT LEAK'}]},
            self.user(self.wrapped(b.CONTINUE_TASK_PROMPT)),
            {'info':{'role':'user'},'parts':[{'type':'text','ignored':True,'text':'IGNORED SHOULD NOT LEAK'}]},
            self.user('Continue improving the entrance without changing the windows.')]
  prompt=b.context_recovery_prompt(messages)
  self.assertIn('Build a tower with warm window lights.',prompt)
  self.assertIn('Continue improving the entrance without changing the windows.',prompt)
  for omitted in ['DreadOS project directory:','lib/three.module.js',b.CONTINUE_TASK_PROMPT,'SHOULD NOT LEAK']:
   self.assertNotIn(omitted,prompt)
 def test_handoff_bounds_history_and_excludes_tool_image_and_reasoning_data(self):
  messages=[self.user('OLDER REQUEST SHOULD NOT LEAK')]
  for name in ['FIRST','SECOND','THIRD']:
   messages.append(self.user(name+' '+('x'*10000)))
  messages[-1]['parts'].append({'type':'file','mime':'image/png','url':'data:image/png;base64,IMAGE_PAYLOAD_SHOULD_NOT_LEAK'})
  messages.append({'info':{'role':'assistant'},'parts':[
   {'type':'tool','tool':'read','state':{'output':'TOOL_OUTPUT_SHOULD_NOT_LEAK'*10000}},
   {'type':'reasoning','text':'REASONING_SHOULD_NOT_LEAK'}]})
  prompt=b.context_recovery_prompt(messages)
  self.assertLess(len(prompt),6500);self.assertEqual(prompt.count('[excerpt truncated]'),3)
  self.assertLess(prompt.index('FIRST'),prompt.index('SECOND'));self.assertLess(prompt.index('SECOND'),prompt.index('THIRD'))
  for omitted in ['OLDER REQUEST SHOULD NOT LEAK','IMAGE_PAYLOAD_SHOULD_NOT_LEAK','TOOL_OUTPUT_SHOULD_NOT_LEAK','REASONING_SHOULD_NOT_LEAK']:
   self.assertNotIn(omitted,prompt)
  self.assertIn('images were not copied',prompt);self.assertIn('Review these excerpts',prompt)
 def test_empty_handoff_requires_current_goal(self):
  prompt=b.context_recovery_prompt([self.user(b.CONTINUE_TASK_PROMPT)])
  self.assertIn('Add your current goal before sending',prompt)
 def test_recovery_revalidates_session_before_creating(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'demo').mkdir()
   cases=[('wrong project','elsewhere','idle',True,'does not belong'),
          ('busy','demo','busy',True,'Stop the current task'),
          ('no overflow','demo','idle',False,'no longer needs context recovery')]
   for label,directory,status,overflow,expected in cases:
    with self.subTest(case=label):
     def response(path,*args,**kwargs):
      return {'/session/ses_old':{'directory':str(root/directory)},
              '/session/status':{'ses_old':{'type':status}},
              '/session/ses_old/message':[self.user('Build a tower'),self.failure() if overflow else self.failure({'name':'MessageAbortedError'})]}.get(path,{})
     with patch.object(b,'PROJECTS',root),patch.object(b,'request',side_effect=response) as req,patch.object(b,'configure_model') as configure,patch.object(b.build_workspace,'save') as save:
      with self.assertRaisesRegex(ValueError,expected):b.action({'action':'recover_context','project':'demo','session':'ses_old'})
      self.assertFalse(any(call.args[0]=='/session' for call in req.call_args_list))
      configure.assert_not_called();save.assert_not_called()
 def test_recovery_creates_new_session_without_submitting_or_changing_files(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'demo';folder.mkdir();saved=folder/'index.html';saved.write_text('<h1>Existing work</h1>')
   messages=[self.user(self.wrapped('Add a glass entrance.')),self.failure()];original=copy.deepcopy(messages)
   new={'id':'ses_fresh','title':'demo recovered session','directory':str(folder)}
   def response(path,*args,**kwargs):
    return {'/session/ses_old':{'directory':str(folder)},'/session/status':{},'/session/ses_old/message':messages,'/session':new}[path]
   with patch.object(b,'PROJECTS',root),patch.object(b,'request',side_effect=response) as req,patch.object(b,'configure_model') as configure,patch.object(b.build_workspace,'save') as save:
    result=b.action({'action':'recover_context','project':'demo','session':'ses_old'})
    self.assertEqual(result['session'],new);self.assertEqual(result['source_session'],'ses_old');self.assertIn('Add a glass entrance.',result['prompt'])
    self.assertEqual([call.args[0] for call in req.call_args_list],['/session/ses_old','/session/status','/session/ses_old/message','/session'])
    self.assertEqual(req.call_args.kwargs,{'name':'demo'});configure.assert_not_called();save.assert_not_called()
   self.assertEqual(messages,original);self.assertEqual(saved.read_text(),'<h1>Existing work</h1>');self.assertEqual(list(folder.iterdir()),[saved])
 def test_send_open_file_hint_requests_only_relevant_bounded_reads(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'demo';(folder/'lib').mkdir(parents=True);(folder/'lib/three.module.js').write_text('// library')
   def response(path,*args,**kwargs):
    return {'/session/ses_test':{'directory':str(folder)},'/session/status':{}}.get(path,{})
   with patch.object(b,'PROJECTS',root),patch.object(b,'request',side_effect=response) as req,patch.object(b,'configure_model',return_value={'providerID':'local','modelID':'test','vision':False}):
    b.action({'action':'send','project':'demo','session':'ses_test','prompt':'Improve entrance lighting.','file':'lib/three.module.js'})
   submitted=req.call_args.args[1]['parts'][0]['text']
   self.assertIn('Inspect it only if relevant',submitted);self.assertIn('read the relevant current disk ranges',submitted)
   self.assertNotIn('Read its current disk contents before editing.',submitted)
