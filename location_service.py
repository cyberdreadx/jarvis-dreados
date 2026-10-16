"""Approximate city only; never persist IP addresses or coordinates."""
import json
import re
import time
import threading
import urllib.request
from pathlib import Path

PATH=Path(__file__).resolve().parent/'data'/'location.json'
LOCK=threading.Lock()
def status():
    try: return json.loads(PATH.read_text(encoding='utf-8'))
    except (OSError,ValueError): return {'mode':'auto','city':'','updated':0}

def configure(data):
    with LOCK:
        mode=data.get('mode')
        if mode not in ('auto','manual','off'): raise ValueError('Choose automatic, manual, or off.')
        previous=status()
        value={'mode':mode,'city':'','updated':time.time()}
        if mode=='manual':
            city=data.get('city','')
            if not isinstance(city,str) or not city.strip() or len(city)>160 or any(ord(c)<32 for c in city):
                raise ValueError('Enter a city or neighborhood under 160 characters.')
            value['city']=city.strip()
        elif mode=='auto':
            if previous.get('mode')=='auto' and time.time()-previous.get('updated',0)<86400:
                return previous
            try:
                request=urllib.request.Request('https://ipapi.co/json/',headers={'User-Agent':'JARVIS/1.0'})
                with urllib.request.urlopen(request,timeout=8) as response: result=json.load(response)
                if not result.get('error') and isinstance(result.get('city'),str) and result['city']:
                    value['city']=', '.join(result[k] for k in ('city','region','country_name') if isinstance(result.get(k),str))[:160]
                else: value['error']='Could not detect your city. Enter it manually.'
            except (OSError,ValueError,TypeError): value['error']='City detection unavailable. Enter your city manually.'
        PATH.parent.mkdir(parents=True,exist_ok=True)
        temporary=PATH.with_suffix('.tmp');temporary.write_text(json.dumps(value),encoding='utf-8');temporary.replace(PATH)
        return value

def nearby(message):
    return bool(re.search(r'\b(near me|nearby|around me|in my area|around here|close to me)\b',message,re.I))
