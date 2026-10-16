"""Shared creative records and explicitly approved GLTCH jobs.

Remote assets remain provider URLs; no server-side URL fetching or automatic retries.
"""
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from contextlib import contextmanager
import mcp_client

DB = Path(__file__).resolve().parent / 'data' / 'media.sqlite3'
MEDIA_TOOLS = {'generate_image', 'edit_image', 'generate_video', 'check_job'}
_quotes = {}
_lock = threading.RLock()

@contextmanager
def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=15)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, created REAL, payload TEXT)')
        with conn:
            yield conn
    finally:
        conn.close()

def put(item):
    with db() as conn:
        conn.execute('INSERT OR REPLACE INTO items VALUES (?,?,?)', (item['id'], item['created'], json.dumps(item)))
    return item

def get(ident):
    if not isinstance(ident, str): raise ValueError('Invalid item ID.')
    with db() as conn:
        row = conn.execute('SELECT payload FROM items WHERE id=?', (ident,)).fetchone()
    if not row: raise ValueError('Media item not found.')
    return json.loads(row[0])

def listing():
    with db() as conn:
        rows = conn.execute('SELECT payload FROM items ORDER BY created DESC LIMIT 500').fetchall()
    return {'items': [json.loads(row[0]) for row in rows]}

def recover():
    # Never repeat a paid submission after a process restart.
    with db() as conn:
        for ident, payload in conn.execute('SELECT id,payload FROM items').fetchall():
            item = json.loads(payload)
            if item['status'] in ('queued', 'running'):
                item.update(status='unknown', detail='Server restarted during generation. Check GLTCH before submitting again; the job may have completed.')
                conn.execute('UPDATE items SET payload=? WHERE id=?', (json.dumps(item), ident))

def safe_url(value):
    try:
        p = urlsplit(value)
        return p.scheme == 'https' and bool(p.hostname) and not p.username and not p.password
    except ValueError: return False

def result_fields(output, tool):
    texts, assets = [], []
    kind = 'video' if tool == 'generate_video' else 'image'
    for block in output.get('content', []):
        if block.get('type') == 'text':
            text = block.get('text', '')
            texts.append(text[:24000])
            # The pinned GLTCH adapter returns a finished asset URL on its own line.
            for line in text.splitlines():
                value = line.strip()
                if safe_url(value) and not any(c.isspace() for c in value):
                    assets.append({'url': value, 'kind': 'video' if re.search(r'\.(mp4|webm)(?:\?|$)', value, re.I) else kind})
        elif block.get('type') == 'resource_link' and safe_url(block.get('uri', '')):
            assets.append({'url': block['uri'], 'kind': 'video' if block.get('mimeType', '').startswith('video/') else kind})
        elif block.get('type') == 'image' and block.get('mimeType') in ('image/png', 'image/jpeg', 'image/webp'):
            value = block.get('data', '')
            if len(value) <= 8_000_000 and re.fullmatch(r'[A-Za-z0-9+/=\s]+', value):
                assets.append({'url': 'data:' + block['mimeType'] + ';base64,' + value, 'kind': 'image'})
    return {'detail': '\n'.join(texts)[:24000], 'assets': assets[:12]}

def capture(call, response):
    if call.get('tool') not in MEDIA_TOOLS: return None
    output = response['result']
    fields = result_fields(output, call['tool'])
    return put({'id': str(uuid.uuid4()), 'created': time.time(), 'kind': 'video' if call['tool'] == 'generate_video' else 'image',
        'status': 'failed' if output.get('isError') else ('complete' if fields['assets'] else 'needs_check'),
        'prompt': str(call.get('arguments', {}).get('prompt', 'Media tool result'))[:8000],
        'arguments': call.get('arguments', {}), 'service': response['connection'], 'tool': call['tool'], **fields})

def catalog():
    conn = next((c for c in mcp_client.public_connections() if c['url'] == 'https://api.gltch.app' and c['status'] == 'connected'), None)
    if not conn: raise ValueError('Connect GLTCH Runner in Connections first.')
    response = mcp_client.call({'id': conn['id'], 'tool': 'list_models', 'arguments': {}})['result']
    if response.get('isError'): raise ValueError('GLTCH could not load model prices. Check your connection and try again.')
    try: raw = json.loads(next(b['text'] for b in response['content'] if b['type'] == 'text'))
    except (ValueError, KeyError, StopIteration): raise ValueError('GLTCH returned an unreadable model catalog.') from None
    choices = []
    for engine in raw.get('engines', []):
        for model in engine.get('models', []):
            cost = model.get('credits_per_unit')
            if not isinstance(cost, (int, float)) or cost < 0: continue
            if model.get('id') == 'comfy-zimage':
                choices.append({'id': 'zimage', 'label': 'Z-Image Turbo', 'credits': cost, 'arguments': {'workflow': 'zimage'}})
            if model.get('id') == 'comfy-txt2img':
                for checkpoint in engine.get('checkpoints', []):
                    if isinstance(checkpoint, str): choices.append({'id': 'txt2img:' + checkpoint, 'label': checkpoint.removesuffix('.safetensors'), 'credits': cost, 'arguments': {'workflow': 'txt2img', 'checkpoint': checkpoint}})
    if not choices: raise ValueError('No supported image models with current prices were returned.')
    ticket = str(uuid.uuid4())
    with _lock:
        for key in list(_quotes):
            if time.time() - _quotes[key]['created'] > 600: del _quotes[key]
        if len(_quotes) >= 100: raise ValueError('Too many open image reviews. Try again later.')
        _quotes[ticket] = {'created': time.time(), 'connection': conn['id'], 'models': choices}
    return {'ticket': ticket, 'models': choices, 'expires_in': 600}

def submit(data):
    if data.get('approved') is not True: raise ValueError('Review and approve the image before generating.')
    ident = str(data.get('request_id', ''))
    try: uuid.UUID(ident)
    except ValueError: raise ValueError('Invalid request ID.') from None
    prompt = data.get('prompt')
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 8000: raise ValueError('Enter a prompt (up to 8,000 characters).')
    size = {'square': (1024, 1024), 'portrait': (832, 1216), 'landscape': (1216, 832)}.get(data.get('shape'))
    if not size: raise ValueError('Choose an image shape.')
    with _lock:
        with db() as conn:
            old = conn.execute('SELECT payload FROM items WHERE id=?', (ident,)).fetchone()
        if old: return json.loads(old[0])  # Network retries never spend twice.
        quote = _quotes.get(str(data.get('ticket', '')))
        if not quote or time.time() - quote['created'] > 600: raise ValueError('Prices expired. Reopen the image review to refresh them.')
        model = next((m for m in quote['models'] if m['id'] == data.get('model')), None)
        if not model: raise ValueError('Choose a model from the current catalog.')
        args = {**model['arguments'], 'prompt': prompt.strip(), 'width': size[0], 'height': size[1]}
        item = put({'id': ident, 'created': time.time(), 'kind': 'image', 'status': 'queued', 'prompt': prompt.strip(),
            'model': model['label'], 'credits': model['credits'], 'arguments': args, 'service': 'GLTCH Runner', 'assets': [], 'detail': 'Waiting for GLTCH…'})
        threading.Thread(target=_run, args=(ident, quote['connection']), daemon=True).start()
        return item

def _run(ident, connection):
    item = get(ident)
    try:
        item.update(status='running', detail='Generating on GLTCH. You can leave this page.'); put(item)
        output = mcp_client.call({'id': connection, 'tool': 'generate_image', 'arguments': item['arguments']})['result']
        item.update(result_fields(output, 'generate_image'))
        item['status'] = 'failed' if output.get('isError') else ('complete' if item['assets'] else 'needs_check')
    except Exception:
        item.update(status='unknown', detail='Connection interrupted. Check GLTCH before generating again; this request may still finish there.')
    put(item)

def action(data):
    if not isinstance(data, dict): raise ValueError('Invalid media request.')
    op = data.get('action')
    if op == 'list': return listing()
    if op == 'catalog': return catalog()
    if op == 'generate': return {'item': submit(data)}
    if op == 'get': return {'item': get(data.get('id'))}
    if op == 'draft':
        text = data.get('text')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 100000: raise ValueError('Draft must contain 1–100,000 characters.')
        return {'item': put({'id': str(uuid.uuid4()), 'created': time.time(), 'kind': 'draft', 'status': 'complete', 'text': text,
            'prompt': str(data.get('brief', ''))[:8000], 'format': data.get('format') if data.get('format') in ('post', 'art', 'video') else 'post', 'assets': []})}
    raise ValueError('Unknown media action.')
