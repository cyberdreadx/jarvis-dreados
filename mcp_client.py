"""Small Streamable HTTP MCP client with explicit user-triggered tool calls.

Credentials and OAuth state live in memory. No tools run during discovery.
"""
import secure_settings
import gltch_runner
import base64
import hashlib
import http.client
import ipaddress
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from providers import NoRedirect

PRESETS = [
    {'name':'GLTCH Runner','url':gltch_runner.URL,'category':'Images & video','description':'Generate images, edit artwork, and animate stills. Uses GLTCH credits.','docs':'https://grokrunner.gltch.app/api-docs'},
    {'name': 'Higgsfield', 'url': 'https://mcp.higgsfield.ai/mcp', 'category': 'Images & video', 'description': 'Generate artwork, motion, and creative assets.', 'docs': 'https://higgsfield.ai/mcp'},
    {'name': 'Canva', 'url': 'https://mcp.canva.com/mcp', 'category': 'Design', 'description': 'Work with designs and branded visual content.', 'docs': 'https://www.canva.dev/docs/apps/mcp/verify-app/'},
    {'name': 'Exa', 'url': 'https://mcp.exa.ai/mcp', 'category': 'Research', 'description': 'Find sources, references, and ideas on the web.', 'docs': 'https://exa.ai/mcp'},
]
_connections = {}
_persistent = False
_pending = {}
_lock = threading.RLock()
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
MAX_RESPONSE = 16 * 1024 * 1024


class MCPError(ValueError):
    pass


def endpoint(value):
    try:
        if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
            raise ValueError()
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname
        if not host or parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ValueError()
        local = host == 'localhost'
        try:
            address = ipaddress.ip_address(host)
            local = address.is_loopback
            if not local and not address.is_global:
                raise ValueError()
        except ValueError:
            if ':' in host or host.replace('.', '').isdigit():
                raise
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and local):
            raise ValueError()
        parsed.port  # Validate the port, including out-of-range values.
        return value.rstrip('/')
    except (ValueError, TypeError):
        raise MCPError('Use an HTTPS MCP URL, or an HTTP server on localhost. Keep credentials out of the URL.') from None


def _json_request(url, data=None, headers=None, form=False):
    url = endpoint(url)
    headers = dict(headers or {})
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    else:
        body = None
    try:
        with _opener.open(urllib.request.Request(url, body, headers), timeout=25) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise MCPError('The server response is too large.')
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        raise MCPError(f'The service returned HTTP {code}. It may require a registered client or different account permissions.') from None
    except (urllib.error.URLError, OSError, http.client.HTTPException, json.JSONDecodeError):
        raise MCPError('Could not contact the service. Check the endpoint and try again.') from None


def persist():
    if _persistent:
        secure_settings.save('connections', [{k:c[k] for k in ('id','name','url','token')} for c in _connections.values()])

def restore_settings():
    global _persistent
    saved = secure_settings.read().get('connections', [])
    for item in saved:
        endpoint(item['url'])
        _connections[item['id']] = dict(item, status='not_connected', error='', tools=[], session='',
            protocol='2025-11-25', auth_metadata='', rpc_lock=threading.RLock())
    _persistent = True
    def reconnect():
        for ident in list(_connections):
            try: connect(ident)
            except (ValueError, OSError): pass
    threading.Thread(target=reconnect, daemon=True).start()


def public_connections():
    with _lock:
        return [{k: value[k] for k in ('id', 'name', 'url', 'status', 'tools', 'error')} for value in _connections.values()]


def add(data):
    if not isinstance(data, dict):
        raise MCPError('Invalid connection.')
    name = data.get('name', '')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise MCPError('Enter a connection name.')
    url = endpoint(data.get('url'))
    token = data.get('token', '')
    if not isinstance(token, str) or len(token) > 8192 or any(c.isspace() for c in token):
        raise MCPError('Enter a valid token, or leave it blank to sign in.')
    if url == gltch_runner.URL and (not token.startswith('gltch_sk_') or token.endswith('...')):
        raise MCPError('Enter your GLTCH API key from GLTCH Settings → API Keys.')
    with _lock:
        if len(_connections) >= 20:
            raise MCPError('A maximum of 20 connections can be added.')
        ident = secrets.token_urlsafe(12)
        _connections[ident] = {'id': ident, 'name': name.strip(), 'url': url, 'token': token,
                               'status': 'not_connected', 'error': '', 'tools': [], 'session': '',
                               'protocol': '2025-11-25', 'auth_metadata': '', 'rpc_lock': threading.RLock()}
    persist()
    return connect(ident)


def _get(ident):
    with _lock:
        if not isinstance(ident, str) or ident not in _connections:
            raise MCPError('Connection not found. Add it again.')
        return _connections[ident]


def _rpc(conn, method, params=None, notification=False):
    ident = secrets.token_hex(8)
    if conn['url'] == gltch_runner.URL:
        try:
            if method == 'initialize':
                if conn.get('runner'): conn['runner'].close()
                conn['runner'] = gltch_runner.Runner(conn['token'])
            value = conn['runner'].rpc(method, params or {}, ident, notification)
            return {} if notification else _result(value)
        except ValueError as error:
            raise MCPError(str(error)) from None
    params = dict(params or {})
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': conn['protocol'], 'Mcp-Method': method}
    if method == 'tools/call':
        name = params['name']
        headers['Mcp-Name'] = name if name.isascii() else 'base64:' + base64.b64encode(name.encode()).decode()
    if conn['protocol'] == '2026-07-28':
        params['_meta'] = {'io.modelcontextprotocol/protocolVersion': conn['protocol'],
                           'io.modelcontextprotocol/clientInfo': {'name': 'jarvis', 'version': '0.2.0'},
                           'io.modelcontextprotocol/clientCapabilities': {}}
    if conn['token']:
        headers['Authorization'] = 'Bearer ' + conn['token']
    if conn['session']:
        headers['Mcp-Session-Id'] = conn['session']
    body = {'jsonrpc': '2.0', 'method': method, 'params': params}
    if not notification:
        body['id'] = ident
    request = urllib.request.Request(conn['url'], json.dumps(body).encode(), headers)
    try:
        with _opener.open(request, timeout=120 if method == 'tools/call' else 25) as response:
            if response.headers.get('Mcp-Session-Id'):
                conn['session'] = response.headers['Mcp-Session-Id']
            if notification or response.status == 202:
                return {}
            if 'text/event-stream' in response.headers.get('Content-Type', ''):
                chunks, size = [], 0
                for line in response:
                    size += len(line)
                    if size > MAX_RESPONSE:
                        raise MCPError('The tool result is too large to display.')
                    text = line.decode('utf-8').rstrip('\r\n')
                    if text.startswith('data:'):
                        chunks.append(text[5:].lstrip())
                    elif not text and chunks:
                        value = json.loads('\n'.join(chunks))
                        chunks = []
                        if value.get('id') == ident and ('result' in value or 'error' in value):
                            return _result(value)
                raise MCPError('The MCP stream ended without a tool response.')
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise MCPError('The tool result is too large to display.')
            value = json.loads(raw)
            if value.get('id') != ident:
                raise MCPError('The MCP server returned an unrelated response.')
            return _result(value)
    except urllib.error.HTTPError as error:
        code = error.code
        challenge = error.headers.get('WWW-Authenticate', '')
        if code in (401, 403):
            import re
            metadata = re.search(r'resource_metadata="([^"]+)"', challenge)
            conn['auth_metadata'] = metadata.group(1) if metadata else ''
            conn['status'] = 'sign_in_required'
        error.close()
        if code in (401, 403):
            raise MCPError('Sign in to this service, or reconnect using an access token.') from None
        raise MCPError(f'MCP server returned HTTP {code}. Check its URL and supported transport.') from None
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        raise MCPError('The MCP server could not be reached or timed out. For a timed-out action, check the service before retrying.') from None
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        raise MCPError('The server did not return a supported MCP response.') from None


def _result(value):
    if 'error' in value:
        error = value['error']
        if error.get('code') == -32601:
            raise MCPError('method_not_found')
        raise MCPError('The MCP server rejected this request. Check required fields and account access.')
    return value.get('result', {})


def connect(ident):
    conn = _get(ident)
    with conn['rpc_lock']:
        conn.update(session='', tools=[], error='', status='not_connected', protocol='2025-11-25')
        try:
            try:
                result = _rpc(conn, 'initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'jarvis', 'version': '0.2.0'}})
                version = result.get('protocolVersion')
                if version not in ('2025-03-26', '2025-06-18', '2025-11-25'):
                    raise MCPError('This server negotiated an unsupported MCP version.')
                conn['protocol'] = version
                _rpc(conn, 'notifications/initialized', notification=True)
            except MCPError as error:
                if str(error) != 'method_not_found':
                    raise
                conn['protocol'] = '2026-07-28'
            cursor = None
            for page in range(30):
                result = _rpc(conn, 'tools/list', {'cursor': cursor} if cursor else {})
                tools = result.get('tools', [])
                if not isinstance(tools, list):
                    raise MCPError('The server returned an invalid tool list.')
                conn['tools'].extend(tool for tool in tools if isinstance(tool, dict) and isinstance(tool.get('name'), str))
                cursor = result.get('nextCursor')
                if not cursor:
                    break
            else:
                raise MCPError('This server has too many tool pages.')
            conn['status'] = 'connected'
        except MCPError as error:
            conn['error'] = str(error)
            conn['tools'] = []
    return {'connections': public_connections()}


def call(data):
    conn = _get(data.get('id'))
    name = data.get('tool')
    args = data.get('arguments')
    if conn['status'] != 'connected':
        raise MCPError('Connect this service before running a tool.')
    if not isinstance(args, dict) or name not in [tool['name'] for tool in conn['tools']]:
        raise MCPError('Choose an available tool and enter its fields.')
    with conn['rpc_lock']:
        result = _rpc(conn, 'tools/call', {'name': name, 'arguments': args})
    return {'result': result, 'connection': conn['name'], 'tool': name}


def remove(ident):
    with _lock:
        conn = _connections.pop(ident, None)
        if conn and conn.get('runner'): conn['runner'].close()
        for key in list(_pending):
            if _pending[key]['id'] == ident:
                del _pending[key]
    persist()
    return {'connections': public_connections()}


def authorize(ident, redirect_uri):
    """Discover OAuth and use dynamic public-client registration + PKCE."""
    conn = _get(ident)
    if conn['url'] == gltch_runner.URL:
        raise MCPError('GLTCH uses an API key. Disconnect and add it again with your key.')
    origin = urllib.parse.urlsplit(conn['url'])
    resource_url = conn['auth_metadata'] or f'{origin.scheme}://{origin.netloc}/.well-known/oauth-protected-resource{origin.path}'
    try:
        resource = _json_request(resource_url)
    except MCPError:
        resource = _json_request(f'{origin.scheme}://{origin.netloc}/.well-known/oauth-protected-resource')
    servers = resource.get('authorization_servers', [])
    if not servers:
        raise MCPError('This server does not advertise browser sign-in. Use a supported server or access token.')
    issuer = endpoint(servers[0])
    issuer_url = urllib.parse.urlsplit(issuer)
    metadata_url = f'{issuer_url.scheme}://{issuer_url.netloc}/.well-known/oauth-authorization-server{issuer_url.path}'
    metadata = _json_request(metadata_url)
    if metadata.get('issuer', '').rstrip('/') != issuer.rstrip('/'):
        raise MCPError('The sign-in service returned mismatched issuer information.')
    if not metadata.get('registration_endpoint'):
        raise MCPError('This service requires a separately registered OAuth client. Use its supported local MCP bridge or an access token for now.')
    if 'S256' not in metadata.get('code_challenge_methods_supported', []):
        raise MCPError('This service does not advertise PKCE sign-in support.')
    auth_url = endpoint(metadata['authorization_endpoint'])
    token_url = endpoint(metadata['token_endpoint'])
    try:
        registration = _json_request(metadata['registration_endpoint'], {
            'client_name': 'JARVIS Local', 'redirect_uris': [redirect_uri], 'grant_types': ['authorization_code'],
            'response_types': ['code'], 'token_endpoint_auth_method': 'none'})
    except MCPError:
        conn['error'] = 'This service declined automatic OAuth client registration. Use a provider-approved MCP bridge or a service-issued access token.'
        raise MCPError(conn['error']) from None
    client_id = registration.get('client_id')
    if not client_id or registration.get('token_endpoint_auth_method', 'none') != 'none':
        raise MCPError('This service did not accept public-client registration.')
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(32)
    with _lock:
        now = time.time()
        for old in list(_pending):
            if now - _pending[old]['created'] > 600:
                del _pending[old]
        _pending[state] = {'id': ident, 'created': now, 'verifier': verifier, 'client_id': client_id,
                           'redirect_uri': redirect_uri, 'token_url': token_url, 'resource': conn['url']}
    params = {'response_type': 'code', 'client_id': client_id, 'redirect_uri': redirect_uri,
              'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': state, 'resource': conn['url']}
    scopes = resource.get('scopes_supported', [])
    if scopes:
        params['scope'] = ' '.join(scopes)
    return {'authorization_url': auth_url + '?' + urllib.parse.urlencode(params)}


def callback(query):
    with _lock:
        pending = _pending.pop(query.get('state', [''])[0], None)
    if not pending or time.time() - pending['created'] > 600:
        raise MCPError('This sign-in expired. Return to Connections and try again.')
    if query.get('error') or not query.get('code'):
        raise MCPError('Sign-in was not completed. Return to Connections to try again.')
    conn = _get(pending['id'])
    result = _json_request(pending['token_url'], {
        'grant_type': 'authorization_code', 'code': query['code'][0], 'client_id': pending['client_id'],
        'redirect_uri': pending['redirect_uri'], 'code_verifier': pending['verifier'], 'resource': pending['resource']}, form=True)
    token = result.get('access_token')
    if not isinstance(token, str) or not token or any(c.isspace() for c in token):
        raise MCPError('The service did not return a usable access token.')
    conn['token'] = token
    persist()
    return connect(conn['id'])
