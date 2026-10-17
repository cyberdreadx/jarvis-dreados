"""Loopback-only managed OpenCode bridge, with project-scoped requests."""
import atexit
import base64
import json
import http.client
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode
import build_workspace
import providers
import context_memory
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'data/opencode'
PROJECTS=ROOT/'data/build-projects'
BASE='http://127.0.0.1:4098'
_process=None
_lock=threading.Lock()

def project(name):
    if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,49}',name):raise ValueError('Use a project name with lowercase letters, numbers, and hyphens.')
    path=PROJECTS/name
    if path.resolve().parent!=PROJECTS.resolve() or path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):raise ValueError('Invalid project path.')
    return path

def password():
    STATE.mkdir(parents=True,exist_ok=True)
    file=STATE/'server-secret'
    if not file.exists():file.write_text(secrets.token_urlsafe(32))
    return file.read_text().strip()

def request(path,data=None,method=None,name=None,timeout=15):
    if name:path+=('&' if '?' in path else '?')+urlencode({'directory':str(project(name))})
    headers={'Authorization':'Basic '+base64.b64encode(('opencode:'+password()).encode()).decode(),'Content-Type':'application/json'}
    body=json.dumps(data).encode() if data is not None else None
    # Fixed HTTP loopback endpoint: no proxy discovery or unnecessary TLS context.
    # Each polling connection has deterministic ownership, independent of garbage collection.
    connection=http.client.HTTPConnection('127.0.0.1',4098,timeout=timeout)
    try:
        connection.request(method or ('POST' if data is not None else 'GET'),path,body,headers)
        response=connection.getresponse()
        with response:
            if not 200 <= response.status < 300:
                raise ValueError(f'OpenCode returned HTTP {response.status}. Check its local log.')
            result=response.read()
        return json.loads(result) if result else {}
    except (OSError,http.client.HTTPException) as error:
        import logging
        logging.getLogger(__name__).warning('OpenCode local request failed: %s: %s',type(error).__name__,error)
        raise ValueError('OpenCode connection failed ('+type(error).__name__+'). Use Reconnect OpenCode to retry.') from None
    finally:
        connection.close()


def start():
    global _process
    with _lock:
        try:
            health=request('/global/health',timeout=2)
            if health.get('healthy'):return health
        except ValueError as health_error:
            try:
                with socket.create_connection(('127.0.0.1',4098),timeout=1):pass
            except OSError:pass
            else:
                # An existing listener may still be initializing. Never launch over it.
                for _ in range(3):
                    try:
                        health=request('/global/health',timeout=3)
                        if health.get('healthy'):return health
                    except ValueError:time.sleep(.3)
                raise ValueError('OpenCode port 4098 is already occupied, but its health check failed: '+str(health_error)) from None
        modules=ROOT/'.opencode-runtime/node_modules'
        binary=modules/'opencode-windows-x64-baseline/bin/opencode.exe'
        if sys.platform=='darwin':
            binary=next((p for p in (modules/'opencode-darwin-arm64/bin/opencode',modules/'opencode-darwin-x64/bin/opencode',modules/'opencode-darwin-x64-baseline/bin/opencode') if p.exists()),binary)
        if not binary.exists():raise ValueError('Install OpenCode with npm install --prefix .opencode-runtime opencode-ai')
        PROJECTS.mkdir(parents=True,exist_ok=True)
        if not (STATE/'opencode.json').exists():(STATE/'opencode.json').write_text((ROOT/'opencode.config.json').read_text())
        env={**os.environ,'OPENCODE_SERVER_PASSWORD':password(),'OPENCODE_CONFIG':str(STATE/'opencode.json'),
             'XDG_CONFIG_HOME':str(STATE/'config'),'XDG_DATA_HOME':str(STATE/'share'),'XDG_CACHE_HOME':str(STATE/'cache'),
             'NODE_OPTIONS':''}
        for folder in ('config','share','cache'):(STATE/folder).mkdir(exist_ok=True)
        with (STATE/'server.log').open('ab') as log:
            _process=subprocess.Popen([str(binary),'serve','--hostname','127.0.0.1','--port','4098'],cwd=PROJECTS,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(40):
            if _process.poll() is not None:raise ValueError('OpenCode could not start. Check data/opencode/server.log.')
            try:
                health=request('/global/health',timeout=1)
                if health.get('healthy'):return health
            except ValueError:time.sleep(.25)
        raise ValueError('OpenCode is starting. Try Connect again shortly.')

def stop():
    if _process and _process.poll() is None:_process.terminate()
atexit.register(stop)

def configure_model(name=None):
    _,cfg=providers.config('local')
    model=cfg['model'] or 'qwen/qwen3.8-27b'
    limit,_=context_memory.context_limit('local')
    options={'baseURL':providers.local_url(cfg['base_url'])}
    if cfg['key']:options['apiKey']=cfg['key']
    if cfg['key']:
        raise ValueError('Build currently requires a local model server without API-key authentication.')
    config=json.loads((ROOT/'opencode.config.json').read_text())
    config.update({'model':'lmstudio/'+model,'small_model':'lmstudio/'+model,
                   'provider':{'lmstudio':{'npm':'@ai-sdk/openai-compatible','name':'LM Studio','options':options,
                                          'models':{model:{'name':'Local coding model','options':{'reasoningEffort':'none'},'limit':{'context':limit,'output':min(8192,limit//3)}}}}}})
    target=STATE/'opencode.json'
    encoded=json.dumps(config,indent=2)
    if not target.exists() or target.read_text()!=encoded:
        target.write_text(encoded)
        request('/global/dispose',{},method='POST')


def action(data):
    if not isinstance(data,dict):raise ValueError('Invalid coding request.')
    verb=data.get('action')
    if verb=='connect':
        health=start()
        configure_model()
        return health
    if verb=='projects':return {'projects':sorted(p.name for p in PROJECTS.iterdir() if p.is_dir() and not p.is_symlink()) if PROJECTS.exists() else []}
    name=data.get('project');folder=project(name)
    if verb=='create':
        folder.mkdir(parents=True,exist_ok=True)
        return request('/session',{'title':name},name=name)
    if not folder.is_dir():raise ValueError('Project not found.')
    if verb=='files':return build_workspace.tree(folder)
    if verb=='read':return build_workspace.read(folder,data.get('path'))
    if verb in ('save','new_file'):return build_workspace.save(folder,data.get('path'),data.get('content',''),data.get('revision'),create=verb=='new_file')
    if verb=='preview':return build_workspace.preview(folder,data.get('path'),data.get('drafts'))
    if verb=='new_session':return request('/session',{'title':name+' coding session'},name=name)
    if verb=='sessions':return request('/session',name=name)
    session=data.get('session')
    if not isinstance(session,str) or not re.fullmatch(r'ses_[A-Za-z0-9]+',session):raise ValueError('Choose a coding session.')
    info=request('/session/'+session,name=name)
    if Path(info.get('directory','')).resolve()!=folder.resolve():raise ValueError('Session does not belong to this project.')
    if verb=='send':
        prompt=data.get('prompt')
        if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=12000:raise ValueError('Enter a coding request under 12,000 characters.')
        configure_model(name)
        _,config=providers.config('local')
        model=config['model'] or 'qwen/qwen3.8-27b'
        prompt='DreadOS project directory: '+str(folder.resolve())+'\nUse absolute file paths inside this directory. The Assistant chat is separate; use PROJECT_BRIEF.md if present.\n\nUser request:\n'+prompt
        current=data.get('file')
        if current:
            build_workspace.safe_path(folder,current)
            prompt+='\n\nThe user has this project file open: '+current+'. Read its current disk contents before editing.'
        return request('/session/'+session+'/prompt_async',{'agent':'build','model':{'providerID':'lmstudio','modelID':model},'parts':[{'type':'text','text':prompt}]},name=name)
    if verb=='poll':
        return {'messages':request('/session/'+session+'/message',name=name),'status':request('/session/status',name=name).get(session,{'type':'idle'}),'permissions':[p for p in request('/permission',name=name) if p.get('sessionID')==session],'diff':request('/session/'+session+'/diff',name=name)}
    if verb=='abort':return request('/session/'+session+'/abort',{},name=name)
    if verb=='permission':
        ident=data.get('permission');reply=data.get('reply')
        pending=request('/permission',name=name)
        if reply not in ('once','reject') or not any(p['id']==ident and p.get('sessionID')==session for p in pending):raise ValueError('Permission request is no longer pending.')
        return request('/permission/'+ident+'/reply',{'reply':reply},name=name)
    raise ValueError('Unknown coding action.')
