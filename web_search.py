"""Documented Brave Search API with explicit browser-search fallback."""
import html
import json
import os
import re
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit
_key=None

def resolve_followup(message, history):
    """Resolve short retry commands to the most recent substantive user request."""
    retry=r'(?:ok(?:ay)?[ ,]*)?(?:please[ ,]*)?(?:try(?: it| that| again| now)?|do (?:it|that)|go ahead|search(?: it| that)?|yes)[.!? ]*'
    if not re.fullmatch(retry,message.strip(),re.I): return message,False
    for item in reversed(history[-24:]):
        content=item.get('content','') if isinstance(item,dict) else ''
        if isinstance(item,dict) and item.get('role')=='user' and isinstance(content,str) and content.strip() and not re.fullmatch(retry,content.strip(),re.I):
            return content.split('\nAttached document excerpt:')[0][:600],True
    return '',True
_settings_path=Path(__file__).resolve().parent/'data'/'search.json'
try:
    _settings=json.loads(_settings_path.read_text())
except (OSError,ValueError):
    _settings={}

def local_endpoint(value):
    if not isinstance(value,str): raise ValueError('Enter a local SearXNG URL.')
    parsed=urlsplit(value)
    if parsed.scheme!='http' or parsed.hostname not in ('localhost','127.0.0.1','::1') or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Use a local SearXNG URL such as http://127.0.0.1:8088.')
    return value.rstrip('/')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def status():
    engine=_settings.get('engine','brave')
    return {'engine':engine,'url':_settings.get('url','http://127.0.0.1:8088'),'configured':engine=='searxng' or bool(os.environ.get('BRAVE_SEARCH_API_KEY','') if _key is None else _key)}

def configure(data):
    global _key
    key=data.get('key','') if isinstance(data,dict) else None
    if not isinstance(key,str) or len(key)>4096 or (key and not re.fullmatch(r'[!-~]+',key)):
        raise ValueError('Enter a valid Brave Search API key.')
    engine=data.get('engine',_settings.get('engine','brave'))
    if engine not in ('brave','searxng'): raise ValueError('Choose Brave or SearXNG.')
    endpoint=local_endpoint(data.get('url',_settings.get('url','http://127.0.0.1:8088')))
    _settings_path.parent.mkdir(parents=True,exist_ok=True)
    _settings_path.write_text(json.dumps({'engine':engine,'url':endpoint}))
    _settings.update(engine=engine,url=endpoint)
    if data.get('remove'): _key=''
    elif key: _key=key
    return status()

def browser_links(query):
    return [{'title':'Search Google','url':'https://www.google.com/search?'+urlencode({'q':query}),'snippet':'Open this query in your browser.'},
            {'title':'Search Brave','url':'https://search.brave.com/search?'+urlencode({'q':query}),'snippet':'Open this query in your browser.'}]

def search(query):
    if not isinstance(query,str) or not query.strip() or len(query)>600 or len(query.split())>75:
        raise ValueError('Use a search query under 600 characters and 75 words.')
    if _settings.get('engine')=='searxng':
        url=local_endpoint(_settings.get('url','http://127.0.0.1:8088'))+'/search?'+urlencode({'q':query,'format':'json','language':'en'})
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            with opener.open(url,timeout=25) as response: data=json.load(response)
            results=[]
            for item in data.get('results',[]):
                link=item.get('url','')
                if urlsplit(link).scheme not in ('http','https'): continue
                results.append({'title':html.unescape(item.get('title',''))[:300],'url':link,'snippet':html.unescape(re.sub('<[^>]+>','',item.get('content','')))[:700]})
            return results[:6]
        except urllib.error.HTTPError as error:
            code=error.code; error.close()
            if code==403: raise ValueError('Enable json in SearXNG search.formats, then retry.') from None
            raise ValueError('SearXNG returned an error. Check your local search server.') from None
        except (OSError,ValueError,TypeError,AttributeError):
            raise ValueError('Cannot reach local SearXNG. Start its Docker container, then retry.') from None
    key=os.environ.get('BRAVE_SEARCH_API_KEY','') if _key is None else _key
    if not key: raise ValueError('Add a Brave Search API key in Search settings for results inside JARVIS. You can search directly using the links below now.')
    url='https://api.search.brave.com/res/v1/web/search?'+urlencode({'q':query,'count':6,'search_lang':'en'})
    req=urllib.request.Request(url,headers={'Accept':'application/json','X-Subscription-Token':key})
    try:
        with urllib.request.urlopen(req,timeout=18) as response: data=json.load(response)
        results=[]
        for item in data.get('web',{}).get('results',[]):
            link=item.get('url','')
            if urlsplit(link).scheme not in ('http','https'):continue
            results.append({'title':html.unescape(item.get('title',''))[:300],'url':link,'snippet':html.unescape(re.sub('<[^>]+>','',item.get('description','')))[:700]})
        return results[:6]
    except urllib.error.HTTPError as error:
        code=error.code;error.close()
        if code in (401,403): raise ValueError('Brave rejected the key. Check your Search API key and plan in Search settings.') from None
        if code==429: raise ValueError('Brave Search quota or rate limit reached. Try later or check your plan.') from None
        raise ValueError('Search provider returned an error. Use the browser links or try again later.') from None
    except (OSError,ValueError,TypeError,AttributeError):
        raise ValueError('Could not retrieve search results. Use the browser links or try again later.') from None
