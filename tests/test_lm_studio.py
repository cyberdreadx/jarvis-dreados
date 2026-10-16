import unittest
from unittest.mock import patch
import lm_studio as lm

class ModelManagerTests(unittest.TestCase):
 def setUp(self):
  self.model={'key':'demo','type':'llm','max_context_length':8192,'loaded_instances':[]}
 def test_list(self):
  with patch.object(lm,'call',return_value={'models':[self.model]}):
   self.assertEqual(lm.action({'action':'list'})['models'][0]['key'],'demo')
 def test_load_validated(self):
  with patch.object(lm,'call',side_effect=[{'models':[self.model]},{'status':'loaded'}]) as call:
   self.assertEqual(lm.action({'action':'load','model':'demo','context_length':4096})['status'],'loaded')
   self.assertEqual(call.call_args.args,('models/load',{'model':'demo','echo_load_config':True,'context_length':4096}))
 def test_reject_bad_limits_and_unknown_models(self):
  with patch.object(lm,'call',return_value={'models':[self.model]}):
   for d in [{'model':'missing'},{'model':'demo','context_length':99999},{'model':'demo','eval_batch_size':-1}]:
    with self.assertRaises(ValueError):lm.action({'action':'load',**d})
 def test_unload_requires_known_instance(self):
  self.model['loaded_instances']=[{'id':'instance-1'}]
  with patch.object(lm,'call',return_value={'models':[self.model]}):
   with self.assertRaises(ValueError):lm.action({'action':'unload','model':'demo','instance_id':'other'})
 def test_select_loaded_chat_instance(self):
  self.model['loaded_instances']=[{'id':'instance-1'}]
  with patch.object(lm,'call',return_value={'models':[self.model]}),patch.object(lm.providers,'configure',return_value={}) as configure:
   lm.action({'action':'select','model':'demo'})
   self.assertEqual(configure.call_args.args[0]['model'],'instance-1')
