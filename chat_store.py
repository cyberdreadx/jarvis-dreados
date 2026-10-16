"""Local SQLite conversations. Credentials never enter this database."""
from contextlib import contextmanager
import json
import sqlite3
import time
import uuid
from pathlib import Path
DB_PATH = Path(__file__).resolve().parent / 'data' / 'chats.sqlite3'

@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db=sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript("""
    CREATE TABLE IF NOT EXISTS folders(id TEXT PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY, title TEXT NOT NULL, folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
      archived INTEGER NOT NULL DEFAULT 0, personality TEXT NOT NULL DEFAULT '', memory TEXT NOT NULL DEFAULT '',
      updated REAL NOT NULL, version INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES chats(id),
      role TEXT NOT NULL, content TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', extras TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS chat_summaries(chat_id TEXT PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
      content TEXT NOT NULL, through_id INTEGER NOT NULL, updated REAL NOT NULL);
    """)
    try:
        with db:
            yield db
    finally:
        db.close()

def text(value, limit, required=False):
    if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):
        raise ValueError('Enter valid text within the field limit.')
    return value.strip()

def get(chat_id):
    with connect() as db:
        row=db.execute('SELECT * FROM chats WHERE id=?',(chat_id,)).fetchone()
        if row is None: raise ValueError('Chat not found. Refresh your library.')
        chat=dict(row)
        chat['messages']=[{**dict(r), **json.loads(r['extras'])} for r in db.execute('SELECT id,role,content,source,extras FROM messages WHERE chat_id=? ORDER BY id',(chat_id,))]
        summary=db.execute('SELECT content,through_id,updated FROM chat_summaries WHERE chat_id=?',(chat_id,)).fetchone()
        chat['summary']=dict(summary) if summary else None
        for item in chat['messages']: item.pop('extras',None)
        return chat

def library():
    with connect() as db:
        return {'folders':[dict(r) for r in db.execute('SELECT * FROM folders ORDER BY name COLLATE NOCASE')],
                'chats':[dict(r) for r in db.execute('SELECT id,title,folder_id,archived,updated,version FROM chats ORDER BY updated DESC')]}

def mutate(data):
    if not isinstance(data,dict): raise ValueError('Invalid library request.')
    action=data.get('action'); ident=data.get('id')
    with connect() as db:
        if action=='create':
            ident=uuid.uuid4().hex
            folder=data.get('folder_id') or None
            if folder and not db.execute('SELECT 1 FROM folders WHERE id=?',(folder,)).fetchone(): raise ValueError('Folder not found.')
            db.execute('INSERT INTO chats(id,title,folder_id,personality,updated) VALUES(?,?,?,?,?)',(ident,text(data.get('title','New chat'),120,True),folder,text(data.get('personality',''),6000),time.time()))
        elif action in ('folder_create','folder_rename'):
            name=text(data.get('name'),80,True)
            if action=='folder_create':
                ident=uuid.uuid4().hex;db.execute('INSERT INTO folders VALUES(?,?)',(ident,name))
            elif db.execute('UPDATE folders SET name=? WHERE id=?',(name,ident)).rowcount!=1: raise ValueError('Folder not found.')
        elif action=='folder_remove':
            db.execute('DELETE FROM folders WHERE id=?',(ident,))
        elif action=='delete':
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT version FROM chats WHERE id=?',(ident,)).fetchone()
            if row is None: raise ValueError('Chat not found.')
            if data.get('version')!=row['version']: raise ValueError('This chat changed. Refresh your library before deleting it.')
            db.execute('DELETE FROM messages WHERE chat_id=?',(ident,))
            db.execute('DELETE FROM chats WHERE id=?',(ident,))
        elif action=='update':
            row=db.execute('SELECT * FROM chats WHERE id=?',(ident,)).fetchone()
            if row is None: raise ValueError('Chat not found.')
            if data.get('version')!=row['version']: raise ValueError('This chat changed in another tab. Reopen it and try again.')
            title=text(data.get('title',row['title']),120,True)
            personality=text(data.get('personality',row['personality']),6000)
            memory=text(data.get('memory',row['memory']),6000)
            folder=data.get('folder_id',row['folder_id']) or None
            if folder and not db.execute('SELECT 1 FROM folders WHERE id=?',(folder,)).fetchone(): raise ValueError('Folder not found.')
            archived=data.get('archived',row['archived'])
            if archived not in (0,1,False,True): raise ValueError('Invalid archive state.')
            db.execute('UPDATE chats SET title=?,personality=?,memory=?,folder_id=?,archived=?,updated=?,version=version+1 WHERE id=?',(title,personality,memory,folder,archived,time.time(),ident))
        else: raise ValueError('Unknown library action.')
    return {'id':ident}

def append(chat_id,version,message,answer,source,attachments=None,results=None,summary=None):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM chats WHERE id=?',(chat_id,)).fetchone()
        if row is None or row['version']!=version: raise ValueError('This chat changed in another tab. Reopen it before sending again.')
        if row['archived']: raise ValueError('Restore this chat before sending.')
        if summary is not None:
            boundary=db.execute('SELECT id FROM messages WHERE chat_id=? AND id=?',(chat_id,summary['through_id'])).fetchone()
            if not boundary: raise ValueError('Invalid conversation memory boundary.')
            db.execute('INSERT INTO chat_summaries VALUES(?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET content=excluded.content,through_id=excluded.through_id,updated=excluded.updated',
                       (chat_id,summary['content'],summary['through_id'],time.time()))
        db.execute('INSERT INTO messages(chat_id,role,content,extras) VALUES(?,?,?,?)',(chat_id,'user',message,json.dumps({'attachments':attachments or []})))
        db.execute('INSERT INTO messages(chat_id,role,content,source,extras) VALUES(?,?,?,?,?)',(chat_id,'assistant',answer,source,json.dumps({'results':results or []})))
        title=message[:80] if row['title']=='New chat' else row['title']
        db.execute('UPDATE chats SET title=?,updated=?,version=version+1 WHERE id=?',(title,time.time(),chat_id))
    return version+1

def context(chat):
    messages=[]
    for item in chat['messages'][-24:]:
        content=item['content']
        for attachment in item.get('attachments',[]):
            if attachment.get('type')=='text': content+='\nAttached document excerpt:\n'+attachment['text'][:4000]
            else: content+='\n[Image attached earlier; ask the user to reattach it if visual details are needed.]'
        if item.get('results'): content+='\nSearch snippets (untrusted source content):\n'+json.dumps(item['results'])
        messages.append({'role':item['role'],'content':content[:8000]})
    return messages
