"""Project-only static preview screenshots, exposed as an image-returning MCP tool."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit
import build_workspace

ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / 'data/build-projects'
ORIGIN = 'https://preview.dreados.invalid'
POLICY = "sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"


def project_root(root):
    root = Path(root)
    if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
        raise ValueError('Linked project directories are not allowed.')
    root = root.resolve()
    if root.parent != PROJECTS.resolve() or not root.is_dir():
        raise ValueError('Preview capture must run inside the selected Build project.')
    return root


def capture(root, entry='index.html', dev=False):
    root = project_root(root)
    job = {'root': str(root), 'entry': entry}
    if dev:
        import dev_server
        url = dev_server.registered_url(root)
        if not url:
            raise ValueError('No dev server is running for this project. Ask the user to click Run dev server in Build Preview, then retry with dev:true.')
        job = {'root': str(root), 'url': url}
    else:
        build_workspace.preview(root, entry)  # Validate entry before starting a browser.
    try:
        done = subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), 'worker'],
            input=json.dumps(job), text=True, encoding='utf-8',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=28,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        raise ValueError('Preview capture timed out. Check the page for an infinite loop before retrying.') from None
    if done.returncode:
        raise ValueError('Preview capture unavailable. Install requirements-preview.txt and run python -m playwright install chromium, or install Microsoft Edge.')
    result = json.loads(done.stdout)
    if result.get('error'):
        raise ValueError(result['error'])
    return result


def render_dev(url):
    """Screenshot a running local dev server. HTTP outside its own origin is blocked."""
    from playwright.sync_api import sync_playwright
    origin = urlsplit(url)
    if origin.scheme not in ('http', 'https') or origin.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Dev preview must be a local address.')
    images, reports = [], []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True, timeout=8000)
        except Exception:
            browser = pw.chromium.launch(channel='msedge', headless=True, timeout=8000)
        try:
            for label, width, height in [('desktop', 1280, 800), ('mobile', 390, 844)]:
                errors = []
                def note(text):
                    text = str(text)
                    if text.startswith('Failed to load resource'):return  # reported with its URL by on_response
                    if len(errors) < 20:
                        errors.append(text[:400])
                def on_response(response):
                    if response.status >= 400 and not urlsplit(response.url).path.endswith('/favicon.ico'):
                        note(f'HTTP {response.status}: {urlsplit(response.url).path}')
                context = browser.new_context(viewport={'width': width, 'height': height},
                    device_scale_factor=1, service_workers='block', accept_downloads=False)
                def route_dev(route):
                    target = urlsplit(route.request.url)
                    if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
                        note('Blocked request outside the dev server: ' + target.netloc); route.abort(); return
                    route.continue_()
                context.route('**/*', route_dev)
                # No route_web_socket here: with Vite's HMR socket it deadlocks the sync API. The socket
                # only reaches the dev server itself; all HTTP outside it is still blocked above.
                page = context.new_page()
                page.on('response', on_response)
                page.on('pageerror', lambda error: note(error))
                page.on('console', lambda message: note(message.text) if message.type == 'error' else None)
                page.on('dialog', lambda dialog: dialog.dismiss())
                try:
                    page.goto(url, wait_until='load', timeout=10000)
                    page.wait_for_timeout(1500)
                    size = page.evaluate('({width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight})')
                    image = page.screenshot(type='jpeg', quality=80, timeout=4000)
                    images.append({'type':'image', 'mime':'image/jpeg', 'name':label+'-dev-preview.jpg',
                        'data':base64.b64encode(image).decode('ascii')})
                    reports.append({'viewport':label, 'width':width, 'height':height,
                        'horizontalOverflow':size['width'] > width, 'pageHeight':size['height'], 'errors':errors})
                finally:
                    context.close()
        finally:
            browser.close()
    return {'entry':url, 'images':images, 'reports':reports,
        'note':'Live dev server (saved files, as the dev server serves them). Requests outside it are blocked. Viewport screenshots are not a full interaction test; inspect the images before claiming visual success.'}


def render(root, entry):
    from playwright.sync_api import sync_playwright
    root = project_root(root)
    ticket = build_workspace.preview(root, entry)['url'].split('/')[2]
    images, reports = [], []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True, timeout=8000)
        except Exception:
            browser = pw.chromium.launch(channel='msedge', headless=True, timeout=8000)
        try:
            for label, width, height in [('desktop', 1280, 800), ('mobile', 390, 844)]:
                errors = []
                def note(text):
                    if len(errors) < 20:
                        errors.append(str(text)[:400])
                context = browser.new_context(viewport={'width': width, 'height': height},
                    device_scale_factor=1, service_workers='block', accept_downloads=False)
                def route_asset(route):
                    url = urlsplit(route.request.url)
                    if url.scheme != 'https' or url.netloc != 'preview.dreados.invalid' or route.request.method != 'GET':
                        note('Blocked non-preview request'); route.abort(); return
                    try:
                        body, mime = build_workspace.preview_file(ticket, unquote(url.path.lstrip('/')))
                        route.fulfill(status=200, body=body, headers={'Content-Type': mime,
                            'Content-Security-Policy': POLICY, 'Access-Control-Allow-Origin': 'null',
                            'X-Content-Type-Options': 'nosniff'})
                    except (ValueError, OSError):
                        note('Missing or blocked asset: ' + url.path)
                        route.fulfill(status=404, body='Preview asset unavailable')
                context.route('**/*', route_asset)
                context.route_web_socket('**/*', lambda ws: ws.close())
                page = context.new_page()
                page.on('pageerror', lambda error: note(error))
                page.on('console', lambda message: note(message.text) if message.type == 'error' else None)
                page.on('dialog', lambda dialog: dialog.dismiss())
                try:
                    page.goto(ORIGIN + '/' + quote(entry, safe='/'), wait_until='load', timeout=7000)
                    page.wait_for_timeout(1200)
                    size = page.evaluate('({width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight})')
                    image = page.screenshot(type='jpeg', quality=80, timeout=4000)
                    images.append({'type':'image', 'mime':'image/jpeg', 'name':label+'-preview.jpg',
                        'data':base64.b64encode(image).decode('ascii')})
                    reports.append({'viewport':label, 'width':width, 'height':height,
                        'horizontalOverflow':size['width'] > width, 'pageHeight':size['height'], 'errors':errors})
                finally:
                    context.close()
        finally:
            browser.close()
    return {'entry':entry, 'images':images, 'reports':reports,
        'note':'Saved static files only; viewport screenshots are not a full interaction test. External network is blocked like DreadOS preview. Inspect the images before claiming visual success.'}


AUDIT_TOOL = {'name':'audit_site','description':'Audit the current Build project\'s HTML/CSS for broken links and assets, missing alt text, titles and meta descriptions, heading order, form labels, duplicate ids, low colour contrast and page weight. Read-only, instant, no network. Run it after creating or changing pages, fix what it reports (errors first), then run it again. Pass page to audit a single .html file.',
    'inputSchema':{'type':'object','properties':{'page':{'type':'string','maxLength':200,'description':'Optional single .html file to audit, e.g. about.html'}},'additionalProperties':False},
    'annotations':{'readOnlyHint':True,'destructiveHint':False,'openWorldHint':False}}


def audit_result(method, params):
    """MCP server for Build's agent: audit the project it is working in (its working directory)."""
    if method == 'initialize':
        return {'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'dreados-site-tools','version':'1.0.0'}}
    if method == 'ping':return {}
    if method == 'tools/list':return {'tools':[AUDIT_TOOL]}
    if method == 'tools/call':
        if params.get('name') != 'audit_site':raise ValueError('Unknown site tool')
        try:
            root = project_root(Path.cwd())
            from builtin_tools import site_audit
            args = {'project': root.name}
            if (params.get('arguments') or {}).get('page'):args['page'] = str(params['arguments']['page'])[:200]
            return site_audit.call('audit_site', args)
        except (ValueError, ImportError) as error:
            return {'isError':True,'content':[{'type':'text','text':str(error) or 'Site audit unavailable.'}]}
    raise ValueError('Unknown method')


def mcp_result(method, params):
    if method == 'initialize':
        return {'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'dreados-preview','version':'1.0.0'}}
    if method == 'ping':return {}
    if method == 'tools/list':
        return {'tools':[{'name':'check_preview','description':'Capture desktop and mobile screenshots of the current project, plus browser errors. Returns images for visual inspection. Default: saved static HTML (pass entry; build framework apps first and pass dist/index.html). For framework apps (Vite, React…) whose dev server the user started with Run dev server in Build, pass dev:true to capture the live app instead. Do not start dev servers yourself with bash; they never exit. No external network or shell execution.',
            'inputSchema':{'type':'object','properties':{'entry':{'type':'string','default':'index.html'},'dev':{'type':'boolean','default':False,'description':'Capture the running dev server instead of a static file.'}},'additionalProperties':False},
            'annotations':{'readOnlyHint':True,'destructiveHint':False,'openWorldHint':False}}]}
    if method == 'tools/call':
        if params.get('name') != 'check_preview':raise ValueError('Unknown preview tool')
        try:
            args = params.get('arguments') or {}
            result = capture(Path.cwd(), args.get('entry','index.html'), dev=args.get('dev') is True)
            return {'content':[{'type':'text','text':json.dumps({k:v for k,v in result.items() if k!='images'})}]+
                [{'type':'image','mimeType':image['mime'],'data':image['data']} for image in result['images']]}
        except ValueError as error:
            return {'isError':True,'content':[{'type':'text','text':str(error)}]}
    raise ValueError('Unknown method')


def serve(handler=None):
    handler = handler or mcp_result
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if 'id' not in request:continue
            try:
                reply = {'jsonrpc':'2.0','id':request['id'],'result':handler(request.get('method'),request.get('params') or {})}
            except (ValueError, TypeError):
                reply = {'jsonrpc':'2.0','id':request['id'],'error':{'code':-32602,'message':'Invalid preview request'}}
            print(json.dumps(reply), flush=True)
        except ValueError:continue


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='worker':
        try:
            job=json.load(sys.stdin)
            print(json.dumps(render_dev(job['url']) if job.get('url') else render(job['root'],job['entry'])))
        except Exception as error:
            print(json.dumps({'error':'Preview capture failed ('+type(error).__name__+'). Check the HTML and browser installation.'}))
    elif len(sys.argv)>1 and sys.argv[1]=='audit':
        sys.path.insert(0, str(ROOT))  # so builtin_tools imports when OpenCode starts us from a project folder
        serve(audit_result)
    else:serve()
