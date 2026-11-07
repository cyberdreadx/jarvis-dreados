"""Authenticated, loopback-only LM Studio model management."""
import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
import providers
import subprocess
import threading

_model_lock=threading.Lock()
_estimate_lock=threading.Lock()
LMS=Path.home()/'.lmstudio'/'bin'/('lms.exe' if os.name=='nt' else 'lms')
# LM Studio's estimates run ~1 GB above real usage on a 24 GB card, so a small margin is enough.
VRAM_MARGIN_GIB=0.4

def estimate_gpu_gib(key,context):
    """LM Studio's own memory estimate for loading `key` fully on GPU at `context` tokens."""
    if not LMS.exists():return None
    try:
        out=subprocess.run([str(LMS),'load',key,'--estimate-only','-c',str(context),'--gpu','max','-y'],
                           capture_output=True,text=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.SubprocessError):return None
    found=re.search(r'Estimated GPU Memory:\s*([\d.]+)\s*(GiB|MiB)',out.stdout+out.stderr)
    if not found:return None
    value=float(found.group(1));return value/1024 if found.group(2)=='MiB' else value

def recommend(key):
    """Largest context (in 4K steps) that LM Studio estimates fits entirely on this GPU."""
    model=next((m for m in call('models').get('models',[]) if m.get('key')==key),None)
    if not model:raise ValueError('Model not found. Refresh the model list.')
    if model.get('type')!='llm':raise ValueError('Only chat models can be auto-tuned.')
    top=max(4096,int(model.get('max_context_length') or 4096))
    settings={'flash_attention':True,'offload_kv_cache_to_gpu':True}
    gpu=gpu_memory()
    if not gpu.get('available'):
        settings['context_length']=min(32768,top)
        return {'settings':settings,'note':'GPU memory could not be read, so the safe 32K default was chosen.'}
    card=max(gpu['gpus'],key=lambda g:g['total_mb']);total=card['total_mb']/1024;budget=total-VRAM_MARGIN_GIB
    with _estimate_lock:
        steps=list(range(4096,top+1,4096)) or [top]
        if steps[-1]!=top:steps.append(top)
        first=estimate_gpu_gib(key,steps[0])
        lo,hi,best,best_gib=0,len(steps)-1,steps[0],first
        if first is None:
            settings['context_length']=min(32768,top)
            return {'settings':settings,'note':'LM Studio could not estimate memory (lms CLI missing), so the safe 32K default was chosen.'}
        if first>budget:
            settings['context_length']=steps[0]
            return {'settings':settings,'estimated_gib':round(first,2),'gpu':card['name'],'gpu_total_gib':round(total,1),'fits_gpu':False,
                    'note':f"This model is too large to fit entirely on the {card['name']}; part of it will run from system RAM, which is slower."}
        while lo<=hi:  # estimates grow with context, so binary search
            mid=(lo+hi)//2;gib=first if mid==0 else estimate_gpu_gib(key,steps[mid])
            if gib is not None and gib<=budget:best,best_gib,lo=steps[mid],gib,mid+1
            else:hi=mid-1
    settings['context_length']=best
    return {'settings':settings,'estimated_gib':round(best_gib,2),'gpu':card['name'],'gpu_total_gib':round(total,1),'fits_gpu':True,
            'note':f"Largest context that fits fully on the {card['name']} ({total:.1f} GB): {best:,} tokens, about {best_gib:.1f} GB."}

def reasoning_effort(model_id):
    """OpenCode reasoningEffort for a loaded model, matched to what LM Studio says it supports."""
    try:models=call('models').get('models',[])
    except ValueError:return None
    model=next((m for m in models if any(i.get('id')==model_id for i in m.get('loaded_instances',[])) or m.get('key')==model_id),None)
    options=((model or {}).get('capabilities') or {}).get('reasoning') or {}
    allowed=options.get('allowed_options') or []
    if 'low' in allowed:return 'low'          # graded thinking: keep it light for a small local context
    return None                                # on/off models (default on) or no reasoning: leave the model default

def gpu_memory():
    """Read this DreadOS host's NVIDIA usage; never execute user-provided commands."""
    try:
        result=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,memory.used,memory.free','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=4,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:return {'available':False}
        rows=[]
        for line in result.stdout.splitlines():
            name,total,used,free=[v.strip() for v in line.split(',')]
            rows.append({'name':name,'total_mb':int(total),'used_mb':int(used),'free_mb':int(free)})
        return {'available':bool(rows),'gpus':rows}
    except (OSError,ValueError,subprocess.TimeoutExpired):return {'available':False}

def call(path,payload=None):
    _,cfg=providers.config('local')
    base=providers.local_url(cfg['base_url'])[:-3]
    headers={'Content-Type':'application/json'}
    if cfg['key']:headers['Authorization']='Bearer '+cfg['key']
    req=urllib.request.Request(base+'/api/v1/'+path,data=None if payload is None else json.dumps(payload).encode(),headers=headers)
    try:
        with providers.local_open(req,timeout=150 if payload is not None else 10) as response:return json.load(response)
    except urllib.error.HTTPError as e:
        code=e.code;e.close()
        raise ValueError(f'LM Studio returned HTTP {code}. Check its server, API permissions, and model settings.') from None
    except (OSError,ValueError):raise ValueError('LM Studio did not respond. Check its local server. After a load timeout, Refresh before retrying.') from None

def action(data):
    if not isinstance(data,dict):raise ValueError('Invalid model request.')
    if data.get('action')=='hardware':return gpu_memory()
    if data.get('action')=='recommend':return recommend(data.get('model'))
    if data.get('action','list')=='list':return _action(data)
    if not _model_lock.acquire(blocking=False):raise ValueError('A model change is already running. Wait, then Refresh.')
    try:return _action(data)
    finally:_model_lock.release()

def _action(data):
    verb=data.get('action','list')
    if verb not in ('list','load','reload','unload','select'):raise ValueError('Unknown model action.')
    models=call('models').get('models',[])
    _,cfg=providers.config('local')
    if verb=='list':return {'models':models,'selected':cfg['model'],'base_url':cfg['base_url']}
    model=next((m for m in models if m.get('key')==data.get('model')),None)
    if not model:raise ValueError('Model not found. Refresh the model list.')
    instances=model.get('loaded_instances',[])
    if verb=='select':
        if model.get('type')!='llm':raise ValueError('Embedding models cannot be used for chat.')
        if not instances:raise ValueError('Load this model before selecting it.')
        return providers.configure({'provider':'local','model':instances[0]['id'],'base_url':cfg['base_url']})
    if verb=='unload':
        ident=data.get('instance_id')
        if not any(i['id']==ident for i in instances):raise ValueError('That instance is no longer loaded.')
        return call('models/unload',{'instance_id':ident})
    if verb=='reload':
        if len(instances)!=1 or instances[0]['id']!=data.get('instance_id'):raise ValueError('Refresh Models and choose the currently loaded instance.')
    elif instances:raise ValueError('This model is already loaded. Unload it first to change its load settings.')
    payload={'model':model['key'],'echo_load_config':True}
    context=data.get('context_length')
    if context is not None:
        if type(context) is not int or not 512<=context<=model.get('max_context_length',512):raise ValueError('Choose a context length within this model’s supported range.')
        payload['context_length']=context
    batch=data.get('eval_batch_size')
    if batch is not None:
        if type(batch) is not int or not 32<=batch<=2048:raise ValueError('Batch size must be between 32 and 2048.')
        payload['eval_batch_size']=batch
    for key in ('flash_attention','offload_kv_cache_to_gpu'):
        if key in data:
            if type(data[key]) is not bool:raise ValueError(key+' must be true or false.')
            payload[key]=data[key]
    if verb=='reload':
        # Validate all input before unloading; preserve supported settings not edited.
        for key in ('context_length','eval_batch_size','flash_attention','offload_kv_cache_to_gpu'):
            if key not in payload and key in instances[0].get('config',{}):payload[key]=instances[0]['config'][key]
        call('models/unload',{'instance_id':instances[0]['id']})
    try:result=call('models/load',payload)
    except ValueError as error:
        raise ValueError(str(error)+' Refresh Models before retrying; the previous model may now be unloaded.') from None
    if verb=='reload' and cfg['model']==instances[0]['id'] and result.get('instance_id'):
        providers.configure({'provider':'local','model':result['instance_id'],'base_url':cfg['base_url']})
    observed=result.get('load_config',{})
    result['verification']={key:('applied' if observed[key]==value else 'different') if key in observed else 'unreported'
                            for key,value in payload.items() if key not in ('model','echo_load_config')}
    return result
