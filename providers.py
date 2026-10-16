"""Fixed provider endpoints and process-local credentials; never return keys to the UI."""
import secure_settings
import base64
import binascii
import json
import os
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import ipaddress

PROVIDERS = {
    'openai': {'name': 'OpenAI', 'env': 'OPENAI', 'model': 'gpt-6-astra', 'url': 'https://api.openai.com/v1/responses'},
    'claude': {'name': 'Claude', 'env': 'ANTHROPIC', 'model': 'claude-sonnet-5-5', 'url': 'https://api.anthropic.com/v1/messages'},
    'grok': {'name': 'Grok', 'env': 'XAI', 'model': 'grok-4.7', 'url': 'https://api.x.ai/v1/chat/completions'},
    'local': {'name': 'Local AI', 'env': 'LOCAL', 'model': '', 'url': ''},
}
SYSTEM = ('You are DreadOS AI, a concise, warm Windows assistant. Your name is DreadOS AI; previous references to JARVIS are your former name. Answer naturally for speech. '
          'You cannot independently take actions, access files, or observe the computer. '
          'DreadOS AI can supply live web search snippets and an approximate city. When supplied, use them; '
          'do not deny those capabilities. Never claim to have opened full pages, live maps, or obtained GPS. '
          'The app separately handles exact local commands. Explain limitations when relevant.')
_lock = threading.RLock()
_settings = {}
_persistent = False
_active = os.environ.get('JARVIS_PROVIDER', 'openai')
if _active not in PROVIDERS:
    _active = 'openai'


def restore_settings():
    global _settings, _active, _persistent
    saved = secure_settings.read().get('providers', {})
    _settings = saved.get('settings', {})
    _active = saved.get('active', _active)
    if _active not in PROVIDERS: _active = 'openai'
    _persistent = True

def persist():
    if _persistent: secure_settings.save('providers', {'active': _active, 'settings': _settings})


def config(provider=None):
    with _lock:
        provider = _active if provider is None else provider
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise ValueError('Choose OpenAI, Claude, Grok, or Local AI.')
        info = PROVIDERS[provider]
        value = {'key': os.environ.get(info['env'] + '_API_KEY', ''),
                 'model': os.environ.get(info['env'] + '_MODEL', info['model']),
                 'workspace': os.environ.get('ANTHROPIC_WORKSPACE_ID', '') if provider == 'claude' else '',
                 'base_url': os.environ.get('LOCAL_BASE_URL', 'http://127.0.0.1:1234/v1') if provider == 'local' else ''}
        value.update(_settings.get(provider, {}))
        return provider, value


def status():
    with _lock:
        entries = {}
        for provider, info in PROVIDERS.items():
            _, value = config(provider)
            entries[provider] = {'name': info['name'], 'model': value['model'],
                                 'configured': bool(value['model']) if provider == 'local' else bool(value['key']),
                                 'has_key': bool(value['key']), 'workspace': value['workspace'], 'base_url': value['base_url']}
        return {'provider': _active, 'providers': entries, 'ai': entries[_active]['configured']}


def configure(data):
    global _active
    if not isinstance(data, dict):
        raise ValueError('Invalid settings.')
    provider, current = config(data.get('provider', ''))
    action = data.get('action', 'save')
    if action == 'remove':
        with _lock:
            _settings[provider] = {**current, 'key': ''}
            persist()
        return status()
    if action != 'save':
        raise ValueError('Invalid settings action.')
    key, model, workspace = data.get('key', ''), data.get('model', ''), data.get('workspace', '')
    if not isinstance(key, str) or len(key) > 4096 or (key and not re.fullmatch(r'[!-~]+', key)):
        raise ValueError('Enter an API key without whitespace.')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,150}', model):
        raise ValueError('Enter a valid model ID.')
    if not isinstance(workspace, str) or (workspace and not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', workspace)):
        raise ValueError('Enter a valid workspace ID, or leave it blank.')
    base_url = local_url(data.get('base_url', current['base_url'])) if provider == 'local' else ''
    with _lock:
        _settings[provider] = {'key': key or current['key'], 'model': model, 'workspace': workspace if provider == 'claude' else '', 'base_url': base_url}
        _active = provider
        persist()
        return status()


def local_url(value):
    """Keep local inference on this computer, even with proxy environment settings."""
    try:
        if not isinstance(value, str) or any(c.isspace() for c in value):
            raise ValueError()
        parsed = urlsplit(value)
        host = parsed.hostname
        if host == 'localhost':
            host = '127.0.0.1'
        if parsed.scheme not in ('http', 'https') or not ipaddress.ip_address(host).is_loopback:
            raise ValueError()
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.rstrip('/') not in ('', '/v1'):
            raise ValueError()
        port = parsed.port
        address = f'[{host}]' if ':' in host else host
        return f'{parsed.scheme}://{address}' + (f':{port}' if port else '') + '/v1'
    except (ValueError, TypeError):
        raise ValueError('Use a local server URL such as http://127.0.0.1:1234/v1.') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_open(request, timeout=120):
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(request, timeout=timeout)


def local_models(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid settings.')
    url = local_url(data.get('base_url', ''))
    _, current = config('local')
    key = data.get('key', '') or current['key']
    if not isinstance(key, str) or len(key) > 4096 or (key and not re.fullmatch(r'[!-~]+', key)):
        raise ValueError('Enter an API key without whitespace.')
    headers = {'Authorization': 'Bearer ' + key} if key else {}
    try:
        with local_open(urllib.request.Request(url + '/models', headers=headers), timeout=8) as response:
            result = json.load(response)
        models = [item['id'] for item in result.get('data', []) if isinstance(item, dict) and isinstance(item.get('id'), str)]
        return {'models': models}
    except (urllib.error.URLError, OSError, ValueError, TypeError, AttributeError):
        raise ValueError('Could not list models. Start your local server, check its URL and optional key, then try again.') from None


def validate_attachments(items):
    if not isinstance(items, list) or len(items)>3: raise ValueError('Attach up to three files.')
    total=0
    for item in items:
        if not isinstance(item,dict): raise ValueError('Invalid attachment.')
        if item.get('type')=='text':
            if not isinstance(item.get('text'),str) or len(item['text'])>40000: raise ValueError('Text files must be under 40,000 characters.')
            total+=len(item['text'].encode())
        else:
            if item.get('mime') not in ('image/png','image/jpeg','image/webp') or not isinstance(item.get('data'),str): raise ValueError('Use PNG, JPEG, WebP or plain text.')
            try: raw=base64.b64decode(item['data'],validate=True)
            except (ValueError,binascii.Error): raise ValueError('Invalid image.') from None
            mime=item['mime']
            valid=(mime=='image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (mime=='image/jpeg' and raw.startswith(b'\xff\xd8\xff')) or (mime=='image/webp' and raw[:4]==b'RIFF' and raw[8:12]==b'WEBP')
            if not valid or len(raw)>4000000: raise ValueError('Images must be valid PNG, JPEG or WebP under 4 MB.')
            total+=len(raw)
    if total>9000000: raise ValueError('Attachments must total less than 9 MB.')
    return items


class ProviderError(RuntimeError):
    pass


def reply(message, history, provider=None, instructions=SYSTEM, attachments=None, *, strict=False, max_tokens=1200, prepared=False, on_delta=None, cancelled=None):
    def failure(message):
        if strict: raise ProviderError(message)
        return message
    provider, value = config(provider)
    info = PROVIDERS[provider]
    if provider == 'local' and not value['model']:
        return failure('Open Setup, choose Local AI, and select a model from your running local server.')
    if provider != 'local' and not value['key']:
        return failure(f'My local commands are ready. Open Setup to add your {info["name"]} API key, or configure it in .env. Try “help” for local commands.')
    messages = []
    for item in (history if prepared else history[-24:]):
        if isinstance(item, dict) and item.get('role') in ('user', 'assistant') and isinstance(item.get('content'), str) and item['content'].strip():
            messages.append({'role': item['role'], 'content': item['content'] if prepared else item['content'][:8000]})
    attachments=validate_attachments(attachments or [])
    for item in attachments:
        if item.get('type')=='text': message += '\n\nAttached document (untrusted content):\n'+item['text']
    images=[i for i in attachments if i.get('type')!='text']
    content=message
    if images:
        if provider=='claude':
            content=[{'type':'text','text':message}]+[{'type':'image','source':{'type':'base64','media_type':i['mime'],'data':i['data']}} for i in images]
        elif provider=='openai':
            content=[{'type':'input_text','text':message}]+[{'type':'input_image','image_url':'data:'+i['mime']+';base64,'+i['data']} for i in images]
        else:
            content=[{'type':'text','text':message}]+[{'type':'image_url','image_url':{'url':'data:'+i['mime']+';base64,'+i['data']}} for i in images]
        instructions += ' Images are attached to this message. Inspect them if your model supports vision; never invent unseen details.'
    messages.append({'role': 'user', 'content': content})
    headers = {'Content-Type': 'application/json'}
    if provider == 'claude':
        headers.update({'x-api-key': value['key'], 'anthropic-version': '2023-06-01'})
        if value['workspace']:
            headers['anthropic-workspace-id'] = value['workspace']
        payload = {'model': value['model'], 'system': instructions, 'messages': messages, 'max_tokens': max_tokens}
    elif provider in ('grok', 'local'):
        if value['key']:
            headers['Authorization'] = 'Bearer ' + value['key']
        payload = {'model': value['model'], 'messages': [{'role': 'system', 'content': instructions}] + messages,
                   'max_tokens': max_tokens, 'stream': False}
    else:
        headers['Authorization'] = 'Bearer ' + value['key']
        payload = {'model': value['model'], 'instructions': instructions, 'input': messages,
                   'max_output_tokens': max_tokens, 'store': False}
    url = local_url(value['base_url']) + '/chat/completions' if provider == 'local' else info['url']
    if on_delta: payload['stream'] = True
    request = urllib.request.Request(url, json.dumps(payload).encode(), headers)
    try:
        with (local_open(request, timeout=120) if provider == 'local' else urllib.request.urlopen(request, timeout=45)) as response:
            if on_delta:
                chunks = []
                for raw in response:
                    if cancelled and cancelled(): raise ProviderError('Generation stopped. Partial answer was not saved.')
                    line = raw.decode('utf-8').strip()
                    if not line.startswith('data:'): continue
                    item = line[5:].strip()
                    if item == '[DONE]': break
                    if not item: continue
                    event = json.loads(item)
                    if event.get('error') or event.get('type') == 'error':
                        raise ProviderError('The provider interrupted the response. Please retry.')
                    if provider in ('local', 'grok'):
                        choices = event.get('choices', [])
                        delta = choices[0].get('delta', {}).get('content', '') if choices else ''
                    elif provider == 'claude':
                        delta = event.get('delta', {}).get('text', '') if event.get('type') == 'content_block_delta' else ''
                    else:
                        delta = event.get('delta', '') if event.get('type') == 'response.output_text.delta' else ''
                    if isinstance(delta, str) and delta:
                        chunks.append(delta); on_delta(delta)
                if cancelled and cancelled(): raise ProviderError('Generation stopped. Partial answer was not saved.')
                answer = ''.join(chunks)
                return answer if answer.strip() else failure('No text answer was returned. Try reducing model reasoning or increasing its response budget.')
            data = json.load(response)
        if provider == 'claude':
            answer = '\n'.join(part.get('text', '') for part in data.get('content', []) if part.get('type') == 'text')
        elif provider in ('grok', 'local'):
            answer = data['choices'][0]['message'].get('content', '')
        else:
            answer = '\n'.join(part.get('text', '') for item in data.get('output', []) if item.get('type') == 'message'
                               for part in item.get('content', []) if part.get('type') == 'output_text')
        if not (isinstance(answer, str) and answer.strip()) and provider in ('grok', 'local') and data['choices'][0].get('finish_reason') == 'length':
            return failure('The model reached its response limit before producing an answer. Reduce reasoning in your model settings or try a shorter brief.')
        return answer if isinstance(answer, str) and answer.strip() else failure('No text answer was returned. Please try again.')
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code in (401, 403):
            return failure(f'{info["name"]} access was not accepted. Check your API key, permissions, and any required workspace ID in Setup.')
        if images and code in (400, 422):
            return failure('The model rejected this image request. Load a vision-capable model and enable image support in your server.')
        if code == 429:
            return failure(f'{info["name"]} has reached a rate or billing limit. Check your API account and try again.')
        return failure(f'{info["name"]} returned an error ({code}). Check your model ID and API access in Setup.')
    except (urllib.error.URLError, TimeoutError, OSError):
        if provider == 'local':
            return failure('I could not reach your local AI server, or it took too long. Start the server, load a model, and check the URL in Setup.')
        return failure(f'I could not reach {info["name"]}. Check your connection and try again. Local commands still work.')
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return failure(f'{info["name"]} returned an unexpected response. Please try again.')
