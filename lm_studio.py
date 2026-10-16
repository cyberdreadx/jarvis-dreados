"""Authenticated, loopback-only LM Studio model management."""
import json
import urllib.request
import urllib.error
import providers

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
    verb=data.get('action','list')
    if verb not in ('list','load','unload','select'):raise ValueError('Unknown model action.')
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
    if instances:raise ValueError('This model is already loaded. Unload it first to change its load settings.')
    payload={'model':model['key'],'echo_load_config':True}
    context=data.get('context_length')
    if context is not None:
        if type(context) is not int or not 512<=context<=model.get('max_context_length',512):raise ValueError('Choose a context length within this model’s supported range.')
        payload['context_length']=context
    batch=data.get('eval_batch_size')
    if batch is not None:
        if type(batch) is not int or not 32<=batch<=2048:raise ValueError('Batch size must be between 32 and 2048.')
        payload['eval_batch_size']=batch
    return call('models/load',payload)
