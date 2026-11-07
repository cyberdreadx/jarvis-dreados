"""Encrypted Build provider settings and an authenticated loopback credential relay."""
import json,re,secrets,threading,urllib.request,urllib.error
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import providers,secure_settings
CATALOG={
 'local':('LM Studio','lmstudio','@ai-sdk/openai-compatible',''),
 'claude':('Claude API','anthropic','@ai-sdk/anthropic','https://api.anthropic.com/v1'),
 'openai':('OpenAI API','openai','@ai-sdk/openai','https://api.openai.com/v1'),
 'grok':('Grok / xAI','xai','@ai-sdk/openai-compatible','https://api.x.ai/v1'),
 'openrouter':('OpenRouter','openrouter','@ai-sdk/openai-compatible','https://openrouter.ai/api/v1'),
 'deepseek':('DeepSeek','deepseek','@ai-sdk/openai-compatible','https://api.deepseek.com/v1')}
_lock=threading.RLock();_saved=None;_relay=None;_relay_token=secrets.token_urlsafe(40)
def settings():
 global _saved
 with _lock:
  if _saved is None:_saved=secure_settings.read().get('build_provider',{'selected':'local','profiles':{}})
  return _saved

def profile(provider=None):
 saved=settings();p=provider or saved.get('selected','local')
 if p not in CATALOG:raise ValueError('Choose a supported Build provider.')
 cfg=dict(saved.get('profiles',{}).get(p,{}))
 if p in providers.PROVIDERS:
  _,shared=providers.config(p)
  cfg.setdefault('model',shared['model']);cfg.setdefault('key',shared['key'])
 cfg.setdefault('model','');cfg.setdefault('key','');cfg.setdefault('context',32768);cfg.setdefault('output',8192);cfg.setdefault('vision',False)
 return p,cfg

def public_settings():
 return {'selected':settings().get('selected','local'),'profiles':{p:{'name':v[0],**{k:x for k,x in profile(p)[1].items() if k!='key'},'has_key':bool(profile(p)[1]['key'])} for p,v in CATALOG.items()}}

def save(data):
 p=data.get('provider')
 if p not in CATALOG:raise ValueError('Choose a supported Build provider.')
 _,old=profile(p)
 model=data.get('model','');key=data.get('key','')
 if not isinstance(model,str) or (p!='local' and not re.fullmatch(r'[A-Za-z0-9._:/-]{1,150}',model)):raise ValueError('Enter a model ID from your provider.')
 if not isinstance(key,str) or len(key)>4096 or (key and not re.fullmatch(r'[!-~]+',key)):raise ValueError('Enter an API key without spaces.')
 cfg={**old,'model':model or old['model'],'key':key or old['key']}
 for field,low,high in [('context',16384,2000000),('output',1024,65536)]:
  value=data.get(field,old[field])
  if type(value) is not int or not low<=value<=high:raise ValueError('Invalid '+field+' token budget.')
  cfg[field]=value
 if cfg['output']>cfg['context']//2:raise ValueError('Output budget must be at most half of context.')
 if type(data.get('vision',False)) is not bool:raise ValueError('Invalid vision setting.')
 cfg['vision']=data.get('vision',False)
 if p!='local' and not cfg['key']:raise ValueError('Add an API key here, or configure this provider in Setup first.')
 with _lock:
  current=settings();updated={'selected':p,'profiles':{**current.get('profiles',{}),p:cfg}}
  secure_settings.save('build_provider',updated)
  global _saved
  _saved=updated
 return public_settings()

class Relay(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def setup(self):
  super().setup();self.connection.settimeout(180)
 def do_POST(self):
  try:size=int(self.headers.get('Content-Length','0'))
  except ValueError:self.send_error(400);return
  if not 0<size<=32000000:self.send_error(413);return
  body=self.rfile.read(size)
  # This token grants access only to the explicitly configured cloud provider endpoints.
  auth=self.headers.get('Authorization','').removeprefix('Bearer ') or self.headers.get('x-api-key','')
  if not secrets.compare_digest(auth,_relay_token):self.send_error(403);return
  pieces=self.path.strip('/').split('/',1)
  if len(pieces)!=2 or pieces[0] not in CATALOG or pieces[0]=='local':self.send_error(404);return
  p,path=pieces
  allowed=('messages','messages/count_tokens') if p=='claude' else ('responses','chat/completions')
  if path not in allowed:self.send_error(404);return
  try:
   _,cfg=profile(p)
   if not cfg['key']:self.send_error(401,'Provider key missing');return
   headers={'Content-Type':'application/json','Accept':'text/event-stream, application/json'}
   if p=='claude':
    headers['x-api-key']=cfg['key'];headers['anthropic-version']=self.headers.get('anthropic-version','2023-06-01')
    if self.headers.get('anthropic-beta'):headers['anthropic-beta']=self.headers['anthropic-beta']
   else:headers['Authorization']='Bearer '+cfg['key']
   req=urllib.request.Request(CATALOG[p][3]+'/'+path,data=body,headers=headers)
   opener=urllib.request.build_opener(providers.NoRedirect())
   try:response=opener.open(req,timeout=180)
   except urllib.error.HTTPError as error:response=error
   with response:
    if response.code>=300:
     body=response.read(65536).decode('utf-8',errors='replace').replace(cfg['key'],'[redacted]')
     self.send_response(response.code);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'error':{'message':body[:2000]}}).encode());return
    self.send_response(response.code);self.send_header('Content-Type',response.headers.get('Content-Type','application/json'));self.send_header('Cache-Control','no-store');self.end_headers()
    while True:
     chunk=response.read1(65536)
     if not chunk:break
     self.wfile.write(chunk);self.wfile.flush()
  except (OSError,ValueError):
   # Never echo upstream exceptions, headers, or credentials into logs or errors.
   self.close_connection=True

def relay_url(p):
 global _relay
 with _lock:
  if _relay is None:
   _relay=ThreadingHTTPServer(('127.0.0.1',0),Relay)
   threading.Thread(target=_relay.serve_forever,daemon=True).start()
  return 'http://127.0.0.1:'+str(_relay.server_port)+'/'+p,_relay_token
