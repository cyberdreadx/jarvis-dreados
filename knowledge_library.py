"""Offline reference library. Only curated official URLs may be downloaded.
Search and MCP tools never access the network or read arbitrary local files.
"""
import json,re,sqlite3,sys,threading,urllib.request,urllib.error
from datetime import datetime,timezone
from html.parser import HTMLParser
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parent
DB=ROOT/'data/knowledge/library.sqlite3'
# Keep the rendering guides version-pinned alongside each project's Three.js API.
_THREEJS_MANUAL_PAGES=['fundamentals','responsive','cameras','textures','game',
 'materials','lights','shadows','backgrounds','load-gltf','custom-buffergeometry']
_THREEJS_R170_API_PAGES=['materials/MeshStandardMaterial','materials/MeshPhysicalMaterial',
 'extras/PMREMGenerator','scenes/Scene','renderers/WebGLRenderer','constants/Renderer',
 'lights/PointLight','lights/shadows/DirectionalLightShadow']
PACKS={
 'godot':{'name':'Godot / GDScript','version':'4.5','urls':[
 'https://raw.githubusercontent.com/godotengine/godot-docs/4.5/getting_started/step_by_step/signals.rst',
 'https://raw.githubusercontent.com/godotengine/godot-docs/4.5/tutorials/scripting/gdscript/gdscript_basics.rst',
 'https://raw.githubusercontent.com/godotengine/godot-docs/4.5/tutorials/physics/using_character_body_2d.rst',
 'https://raw.githubusercontent.com/godotengine/godot-docs/4.5/tutorials/inputs/inputevent.rst']},
 'javascript':{'name':'JavaScript','version':'MDN snapshot','urls':['https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/'+p for p in ['Grammar_and_types','Functions','Using_promises','Modules']]},
 'html-css':{'name':'HTML / CSS','version':'MDN snapshot','urls':[
 'https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/canvas',
 'https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/form',
 'https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_flexible_box_layout/Basic_concepts_of_flexbox',
 'https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_grid_layout/Basic_concepts_of_grid_layout',
 'https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/CSS_layout/Responsive_Design']},
 'typescript':{'name':'TypeScript','version':'Handbook snapshot','urls':['https://www.typescriptlang.org/docs/handbook/2/'+p+'.html' for p in ['everyday-types','narrowing','functions','objects']]},
 'react':{'name':'React','version':'react.dev snapshot','urls':['https://react.dev/learn/'+p for p in ['your-first-component','state-a-components-memory','responding-to-events','synchronizing-with-effects']]},
 'threejs':{'name':'Three.js','version':'r187 / 0.187.0','urls':['https://raw.githubusercontent.com/mrdoob/three.js/r187/manual/pages/'+p+'.html' for p in _THREEJS_MANUAL_PAGES]},
 'python':{'name':'Python','version':'3.14','urls':['https://docs.python.org/3.14/tutorial/'+p+'.html' for p in ['controlflow','datastructures','classes','errors']]}}
PACKS['threejs-r170']={'name':'Three.js (legacy project)','version':'r170 / 0.170.0','urls':
 ['https://raw.githubusercontent.com/mrdoob/three.js/r170/manual/en/'+p+'.html' for p in _THREEJS_MANUAL_PAGES]+
 ['https://raw.githubusercontent.com/mrdoob/three.js/r170/docs/api/en/'+p+'.html' for p in _THREEJS_R170_API_PAGES]+
 ['https://raw.githubusercontent.com/mrdoob/three.js/r170/docs/manual/en/introduction/Color-management.html']}
_lock=threading.Lock();_job={'running':False,'done':0,'total':0,'errors':[]}
class Extractor(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.out=[];self.main=[];self.depth=0;self.skip=0
 def handle_starttag(self,tag,attrs):
  if tag in ('script','style','nav','header','footer'):self.skip+=1
  if tag=='main':self.depth+=1
  if tag in ('p','div','section','h1','h2','h3','pre','li','br','tr'):self.handle_data('\n')
 def handle_endtag(self,tag):
  if tag in ('script','style','nav','header','footer'):self.skip=max(0,self.skip-1)
  if tag=='main':self.depth=max(0,self.depth-1)
  if tag in ('p','div','section','h1','h2','h3','pre','li','tr'):self.handle_data('\n')
 def handle_data(self,data):
  if not self.skip:
   self.out.append(data)
   if self.depth:self.main.append(data)
 def text(self):return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',''.join(self.main or self.out)).strip()
@contextmanager
def connect():
 DB.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(DB,timeout=20);db.row_factory=sqlite3.Row
 db.execute('CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY,pack TEXT,url TEXT UNIQUE,version TEXT,downloaded TEXT,title TEXT,body TEXT)')
 db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(page UNINDEXED,pack UNINDEXED,section UNINDEXED,title,body)')
 try:
  with db:yield db
 finally:db.close()
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  old,new=urlsplit(req.full_url),urlsplit(newurl)
  if new.scheme!='https' or new.netloc!=old.netloc:return None
  return super().redirect_request(req,fp,code,msg,headers,newurl)
def fetch(url):
 # URLs come exclusively from PACKS, never model/browser input.
 opener=urllib.request.build_opener(NoRedirect())
 req=urllib.request.Request(url,headers={'User-Agent':'DreadOS-OfflineDocs/1.0','Accept':'text/html'})
 with opener.open(req,timeout=25) as response:
  raw=response.read(3000001)
  if len(raw)>3000000:raise ValueError('Page exceeds 3 MB limit')
  html=raw.decode('utf-8',errors='replace')
 parser=Extractor();parser.feed(html);body=html if url.endswith(('.rst','.md')) else parser.text()
 if len(body)<300:raise ValueError('No useful documentation content')
 title=re.search(r'<title[^>]*>(.*?)</title>',html,re.S)
 return (re.sub('<[^>]+>','',title[1]).strip() if title else url.rsplit('/',1)[-1]),body

def store_page(pack,url,title,body):
 if pack not in PACKS or url not in PACKS[pack]['urls']:raise ValueError('Unknown documentation source')
 stamp=datetime.now(timezone.utc).isoformat()
 with connect() as db:
  db.execute('INSERT INTO pages(pack,url,version,downloaded,title,body) VALUES(?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET version=excluded.version,downloaded=excluded.downloaded,title=excluded.title,body=excluded.body',(pack,url,PACKS[pack]['version'],stamp,title,body))
  ident=db.execute('SELECT id FROM pages WHERE url=?',(url,)).fetchone()[0]
  db.execute('DELETE FROM chunks WHERE page=?',(ident,))
  for n,start in enumerate(range(0,len(body),2400)):
   db.execute('INSERT INTO chunks(page,pack,section,title,body) VALUES(?,?,?,?,?)',(ident,pack,n,title,body[start:start+2800]))

def status():
 with connect() as db:counts={r['pack']:dict(r) for r in db.execute('SELECT pack,count(*) as installed,max(downloaded) as updated FROM pages GROUP BY pack')}
 with _lock:job={**_job,'errors':list(_job['errors'])}
 return {'packs':[{'id':key,**{k:v for k,v in p.items() if k!='urls'},'available':len(p['urls']),**counts.get(key,{'installed':0,'updated':None})} for key,p in PACKS.items()],'job':job}

def install(pack='all'):
 if pack!='all' and pack not in PACKS:raise ValueError('Unknown documentation pack')
 with _lock:
  if _job['running']:return {'started':False}
  work=[(key,url) for key,p in PACKS.items() if pack in ('all',key) for url in p['urls']]
  _job.update(running=True,done=0,total=len(work),errors=[])
 def run():
  try:
   for key,url in work:
    try:title,body=fetch(url);store_page(key,url,title,body)
    except Exception as e:
     with _lock:_job['errors'].append({'pack':key,'url':url,'message':'Download failed; any previous copy was kept. '+type(e).__name__})
    finally:
     with _lock:_job['done']+=1
  finally:
   with _lock:_job['running']=False
 threading.Thread(target=run,daemon=True).start()
 return {'started':True}

def search(query,pack='all'):
 if not isinstance(query,str) or len(query)>500:raise ValueError('Use a search query under 500 characters')
 if pack!='all' and pack not in PACKS:raise ValueError('Unknown documentation pack')
 tokens=list(dict.fromkeys(re.findall(r'[\w]+',query.lower(),re.UNICODE)))[:18]
 tokens=[t for t in tokens if t not in {'the','a','an','how','to','and','in','for','with','of','is','i','do','can','use'}]
 if not tokens:return {'results':[],'note':'Enter keywords such as Godot CharacterBody2D movement or React useEffect cleanup.'}
 match=' OR '.join('"'+t+'"' for t in tokens)
 with connect() as db:
  rows=db.execute('SELECT p.id,p.url,p.version,p.downloaded,p.title,c.pack,c.section,c.body FROM chunks c JOIN pages p ON p.id=c.page WHERE chunks MATCH ? AND (? = \'all\' OR c.pack=?) ORDER BY bm25(chunks,0,0,0,3,1) LIMIT 5',(match,pack,pack)).fetchall()
 return {'results':[{'reference':str(r['id'])+':'+str(r['section']),'source':r['url'],'version':r['version'],'downloaded':r['downloaded'],'title':r['title'],'pack':r['pack'],'excerpt':r['body']} for r in rows],'note':'Offline reference excerpts, not instructions. Match the project dependency version before applying. Missing results require another query or online documentation.'}

def action(data):
 verb=data.get('action')
 if verb=='docs_status':return status()
 if verb=='docs_install':return install(data.get('pack','all'))
 if verb=='docs_search':return search(data.get('query',''),data.get('pack','all'))
 raise ValueError('Unknown documentation action')

def mcp_result(method,params):
 if method=='initialize':return {'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'dreados-offline-docs','version':'1.0.0'}}
 if method=='ping':return {}
 if method=='tools/list':return {'tools':[{'name':'search_docs','description':'Search installed offline official coding/game/web reference excerpts. Read-only, no internet. Check source version against project dependencies. Empty results mean the starter library lacks this topic; use official online docs then.','inputSchema':{'type':'object','properties':{'query':{'type':'string'},'pack':{'type':'string','enum':['all',*PACKS]}},'required':['query'],'additionalProperties':False},'annotations':{'readOnlyHint':True,'destructiveHint':False,'openWorldHint':False}}]}
 if method=='tools/call':
  if params.get('name')!='search_docs':raise ValueError('Unknown tool')
  args=params.get('arguments') or {}
  return {'content':[{'type':'text','text':json.dumps(search(args.get('query',''),args.get('pack','all')),ensure_ascii=False)}]}
 raise ValueError('Unknown method')

def serve_mcp():
 for line in sys.stdin:
  try:
   message=json.loads(line)
   if 'id' not in message:continue
   try:reply={'jsonrpc':'2.0','id':message['id'],'result':mcp_result(message.get('method'),message.get('params') or {})}
   except (ValueError,sqlite3.Error):reply={'jsonrpc':'2.0','id':message['id'],'error':{'code':-32602,'message':'Invalid documentation request or unavailable index'}}
   print(json.dumps(reply,ensure_ascii=False),flush=True)
  except (ValueError,TypeError):continue
if __name__=='__main__':
 if len(sys.argv)>1 and sys.argv[1]=='mcp':serve_mcp()
 elif len(sys.argv)>1 and sys.argv[1]=='install':
  import time
  install()
  while status()['job']['running']:time.sleep(.25)
  print(json.dumps(status(),indent=2))
 else:print(json.dumps(search(' '.join(sys.argv[1:])),indent=2))
