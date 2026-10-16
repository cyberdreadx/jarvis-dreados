"""User-triggered, cached place lookup for the local map panel."""
import json
import os
import time
import threading
import urllib.request
from urllib.parse import urlencode
from pathlib import Path
CACHE=Path(__file__).resolve().parent/'data'/'map-cache.json'
LOCK=threading.Lock()
LAST=0

def lookup(data):
    global LAST
    query=data.get('query','')
    if not isinstance(query,str) or not query.strip() or len(query)>200: raise ValueError('Enter a city or named place under 200 characters.')
    query=query.strip()
    with LOCK:
        try: cache=json.loads(CACHE.read_text(encoding='utf-8'))
        except (OSError,ValueError): cache={}
        if query in cache and time.time()-cache[query]['time']<604800: return cache[query]['result']
        if time.monotonic()-LAST<1.1: raise ValueError('Please wait a moment before another map lookup.')
        LAST=time.monotonic()
        endpoint=os.environ.get('DREADOS_GEOCODER_URL','https://nominatim.openstreetmap.org/search')
        req=urllib.request.Request(endpoint+'?'+urlencode({'q':query,'format':'jsonv2','limit':5}),headers={'User-Agent':'DreadOS-AI-Local/0.1 (personal desktop map viewer)','Accept':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=15) as response: rows=json.load(response)
            places=[]
            for row in rows:
                lat,lon=float(row['lat']),float(row['lon'])
                if not (-90<=lat<=90 and -180<=lon<=180): continue
                places.append({'name':row['display_name'],'lat':lat,'lon':lon})
            result={'places':places,'attribution':'© OpenStreetMap contributors'}
        except (OSError,ValueError,TypeError,KeyError): raise ValueError('Map lookup unavailable. Try another place or retry later.') from None
        if len(cache)>100: cache={}
        cache[query]={'time':time.time(),'result':result};CACHE.parent.mkdir(parents=True,exist_ok=True);CACHE.write_text(json.dumps(cache),encoding='utf-8')
        return result
