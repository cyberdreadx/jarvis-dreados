"""Project-scoped editor storage and isolated static preview tickets."""
import hashlib
import mimetypes
import os
import re
import secrets
import threading
import time
from pathlib import Path

LIMIT=500_000
SKIP={'.git','node_modules','.venv','venv','__pycache__','.next','.opencode','.ssh','.aws','.codex','.dreados-history'}
_lock=threading.Lock()
_previews={}

def safe_path(root,name):
    if not isinstance(name,str) or not name or len(name)>240:raise ValueError('Choose a project-relative file path.')
    parts=name.replace('\\','/').split('/')
    if any(not re.fullmatch(r'[A-Za-z0-9_. -]+',p) or p in ('.','..') or p.lower() in SKIP or p.lower().startswith('.env') or p.endswith((' ','.')) or p.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]} for p in parts):
        raise ValueError('This file path is not allowed.')
    root=root.resolve();path=root
    for part in parts:
        path=path/part
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):raise ValueError('Linked files are not editable here.')
    if not path.resolve().is_relative_to(root):raise ValueError('File must stay inside the selected project.')
    return path

def revision(raw):return hashlib.sha256(raw).hexdigest()

def read(root,name):
    path=safe_path(root,name)
    if not path.is_file():raise ValueError('File not found.')
    if path.stat().st_size>LIMIT:raise ValueError('Open files smaller than 500 KB in this editor.')
    raw=path.read_bytes()
    try:content=raw.decode('utf-8')
    except UnicodeDecodeError:raise ValueError('This file is binary; choose a UTF-8 text file.') from None
    if '\x00' in content:raise ValueError('This file is binary; choose a text file.')
    return {'path':name,'content':content,'revision':revision(raw)}

def tree(root):
    files=[];truncated=False
    for folder,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=sorted(d for d in dirs if d.lower() not in SKIP and not d.startswith('.') and not (Path(folder)/d).is_symlink() and not (hasattr(Path(folder)/d,'is_junction') and (Path(folder)/d).is_junction()))
        for name in sorted(names):
            relative=(Path(folder)/name).relative_to(root).as_posix()
            try:path=safe_path(root,relative)
            except ValueError:continue
            if path.is_file():files.append({'path':relative,'size':path.stat().st_size})
            if len(files)>=1200:truncated=True;break
        if truncated:break
    return {'files':files,'truncated':truncated}

def save(root,name,content,expected,create=False):
    if not isinstance(content,str) or len(content.encode('utf-8'))>LIMIT:raise ValueError('Keep files under 500 KB.')
    with _lock:
        path=safe_path(root,name)
        if create:
            if path.exists():raise ValueError('That file already exists. Open it from the file tree.')
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x',encoding='utf-8',newline='') as f:f.write(content)
        else:
            current=read(root,name)
            if expected!=current['revision']:raise ValueError('This file changed on disk, possibly through OpenCode. Your draft is preserved. Reload the file before saving again.')
            # Retain a recovery copy before replacing a file; useful if an agent edits concurrently.
            backup=root/'.dreados-history'/revision(current['content'].encode())
            if backup.parent.is_symlink() or (hasattr(backup.parent,'is_junction') and backup.parent.is_junction()):raise ValueError('Invalid recovery directory.')
            backup.parent.mkdir(exist_ok=True)
            if not backup.exists():backup.write_text(current['content'],encoding='utf-8')
            temporary=path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp')
            try:
                temporary.write_text(content,encoding='utf-8',newline='')
                if revision(path.read_bytes())!=expected:raise ValueError('File changed while saving. Your draft is preserved; reload before retrying.')
                temporary.replace(path)
            finally:temporary.unlink(missing_ok=True)
        return read(root,name)

def preview(root,name,drafts=None):
    drafts=drafts or {}
    if not isinstance(drafts,dict) or len(drafts)>40:raise ValueError('Too many preview drafts.')
    total=0
    for file,content in drafts.items():
        draft_path=safe_path(root,file)
        if draft_path.suffix.lower() not in ('.html','.htm','.css','.js') or not isinstance(content,str):raise ValueError('Invalid preview draft.')
        total+=len(content.encode('utf-8'))
    if total>2_000_000:raise ValueError('Preview drafts exceed 2 MB.')
    path=safe_path(root,name)
    if path.suffix.lower() not in ('.html','.htm') or not path.is_file():raise ValueError('Select a saved HTML file for static preview. Framework projects need their build output first.')
    with _lock:
        now=time.monotonic()
        for ticket in list(_previews):
            if _previews[ticket][1]<now:del _previews[ticket]
        if len(_previews)>=40:_previews.pop(next(iter(_previews)))
        ticket=secrets.token_urlsafe(24);_previews[ticket]=(root,now+900,dict(drafts))
    from urllib.parse import quote
    return {'url':'/preview/'+ticket+'/'+quote(name,safe='/')}

def preview_file(ticket,name):
    with _lock:entry=_previews.get(ticket)
    if not entry or entry[1]<time.monotonic():raise ValueError('Preview expired. Refresh the preview.')
    path=safe_path(entry[0],name)
    allowed={'.html': 'text/html; charset=utf-8','.htm':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif','.svg':'image/svg+xml','.woff2':'font/woff2'}
    if path.suffix.lower() not in allowed or not path.is_file() or path.stat().st_size>5_000_000:raise ValueError('Preview asset unavailable.')
    content=entry[2].get(name)
    return (content.encode('utf-8') if content is not None else path.read_bytes()),allowed[path.suffix.lower()]
