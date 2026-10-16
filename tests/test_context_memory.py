import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import chat_store
import context_memory as memory
import providers
import server
import test_server

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=patch.object(chat_store,'DB_PATH',Path(self.tmp.name)/'chats.db');self.db.start()
        self.limit=patch.object(memory,'context_limit',return_value=(8192,True));self.limit.start()
        self.chat_id=chat_store.mutate({'action':'create'})['id']
    def tearDown(self):
        self.limit.stop();self.db.stop();self.tmp.cleanup()
    def populate(self,n=16):
        for i in range(n): chat_store.append(self.chat_id,i,f'Project Aurora decision {i}: use teal. '+('Details. '*35),'Confirmed. '+('Notes. '*25),'test')
        return chat_store.get(self.chat_id)
    def test_compact_commit_and_retrieve_originals(self):
        chat=self.populate();originals=chat['messages'];stages=[]
        with patch.object(providers,'reply',return_value='Project Aurora uses teal. Keep the agreed launch plan.'):
            history,instructions,summary,info=memory.prepare(chat,'What were the Aurora decisions?','Be helpful.',[],'local',stages.append)
        self.assertIn('compacting',stages)
        self.assertGreater(info['compacted_messages'],0)
        self.assertIn('original conversation excerpts',instructions)
        self.assertEqual(history[-2]['content'],originals[-2]['content'])
        self.assertEqual(history[-1]['content'],originals[-1]['content'])
        self.assertIsNone(chat_store.get(self.chat_id)['summary'])
        chat_store.append(self.chat_id,chat['version'],'Next','Answer','test',summary=summary)
        saved=chat_store.get(self.chat_id)
        self.assertEqual(saved['messages'][:-2],originals)
        self.assertEqual(saved['summary']['through_id'],summary['through_id'])
        with patch.object(providers,'reply') as model:
            memory.prepare(saved,'Continue','Be helpful.',[],'local')
            model.assert_not_called()
    def test_failure_does_not_replace_summary_or_originals(self):
        chat=self.populate()
        with patch.object(providers,'reply',side_effect=providers.ProviderError('Offline')):
            with self.assertRaisesRegex(memory.ContextError,'No saved messages'):
                memory.prepare(chat,'Continue','Help.',[],'local')
        self.assertEqual(chat_store.get(self.chat_id),chat)
    def test_version_conflict_cannot_commit_summary(self):
        chat=self.populate(2)
        summary={'content':'Old summary','through_id':chat['messages'][0]['id']}
        chat_store.mutate({'action':'update','id':self.chat_id,'version':2,'memory':'New preference'})
        with self.assertRaises(ValueError):chat_store.append(self.chat_id,2,'x','y','test',summary=summary)
        self.assertIsNone(chat_store.get(self.chat_id)['summary'])
        self.assertEqual(len(chat_store.get(self.chat_id)['messages']),4)
    def test_oversized_current_input_is_explicit(self):
        with self.assertRaisesRegex(memory.ContextError,'too large'):
            memory.prepare(chat_store.get(self.chat_id),'x'*20000,'Help.',[],'local')
    def test_small_history_does_not_call_summarizer(self):
        chat=self.populate(2)
        with patch.object(providers,'reply') as model:
            history,_,summary,_=memory.prepare(chat,'Continue','Help.',[],'local')
        self.assertEqual(len(history),4);self.assertIsNone(summary);model.assert_not_called()
    def test_summary_deleted_with_chat(self):
        chat=self.populate(1)
        chat_store.append(self.chat_id,1,'Next','Done','test',summary={'content':'Memory','through_id':chat['messages'][1]['id']})
        chat_store.mutate({'action':'delete','id':self.chat_id,'version':2})
        with chat_store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chat_summaries').fetchone()[0],0)
    def test_loaded_limit_not_advertised_maximum(self):
        self.limit.stop()
        models={'models':[{'key':'test','max_context_length':262144,'loaded_instances':[{'id':'test','config':{'context_length':8192}}]}]}
        with patch.object(providers,'config',return_value=('local',{'model':'test','base_url':'http://127.0.0.1:1234/v1','key':''})),patch.object(providers,'local_open') as network:
            network.return_value.__enter__.return_value=io.BytesIO(json.dumps(models).encode())
            self.assertEqual(memory.context_limit('local'),(8192,True))

class CommandRouting(unittest.TestCase):
    setUpClass=classmethod(test_server.HTTP.setUpClass.__func__)
    tearDownClass=classmethod(test_server.HTTP.tearDownClass.__func__)
    request=test_server.HTTP.request
    def test_calculator_precedes_web_search(self):
        with patch('server.subprocess.Popen') as launch,patch('web_search.search') as search,patch('providers.reply') as model:
            status,body=self.request('/api/chat',json.dumps({'message':'Open calculator','web_search':True}).encode(),{'X-Jarvis-Token':server.TOKEN})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['source'],'local')
        launch.assert_called_once();search.assert_not_called();model.assert_not_called()

if __name__=='__main__':unittest.main()
