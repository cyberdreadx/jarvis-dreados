import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import chat_store

class Persistence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patch=patch('chat_store.DB_PATH',Path(self.tmp.name)/'chats.sqlite3');self.patch.start()
    def tearDown(self):
        self.patch.stop();self.tmp.cleanup()
    def test_persistence_context_and_isolation(self):
        a=chat_store.mutate({'action':'create','personality':'Be concise.'})['id']
        b=chat_store.mutate({'action':'create'})['id']
        chat_store.append(a,0,'My project is Aurora.','Understood.','local ai',[{'type':'text','text':'Launch in May.'}])
        loaded=chat_store.get(a)
        self.assertEqual(loaded['personality'],'Be concise.')
        self.assertEqual(len(loaded['messages']),2)
        self.assertEqual(chat_store.get(b)['messages'],[])
        self.assertIn('Launch in May.',chat_store.context(loaded)[0]['content'])
        self.assertEqual(loaded['version'],1)
        with self.assertRaises(ValueError): chat_store.append(a,0,'stale','No','test')
    def test_folder_archive_restore_memory(self):
        folder=chat_store.mutate({'action':'folder_create','name':'Music'})['id']
        chat=chat_store.mutate({'action':'create','folder_id':folder})['id']
        chat_store.mutate({'action':'update','id':chat,'version':0,'memory':'Prefer D minor.','archived':True})
        with self.assertRaises(ValueError):chat_store.append(chat,1,'hello','hi','test')
        chat_store.mutate({'action':'update','id':chat,'version':1,'archived':False})
        chat_store.mutate({'action':'folder_remove','id':folder})
        loaded=chat_store.get(chat)
        self.assertIsNone(loaded['folder_id'])
        self.assertEqual(loaded['memory'],'Prefer D minor.')
        self.assertFalse(loaded['archived'])
    def test_validation(self):
        with self.assertRaises(ValueError):chat_store.mutate({'action':'create','folder_id':'missing'})
        with self.assertRaises(ValueError):chat_store.mutate({'action':'folder_create','name':''})
