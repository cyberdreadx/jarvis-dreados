let studioModels=[],studioSelected='',studioModelBusy=false;
const modelDrafts=new Map(),modelPrevious=new Map(),modelAdvancedOpen=new Set();
function modelElement(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
async function refreshStudioModels(){
 $('models-status').textContent='Connecting to LM Studio…';
 try{const data=await api('/api/lm-studio',{action:'list'},15000);studioModels=data.models;studioSelected=data.selected;renderStudioModels();$('models-status').textContent=`Connected · ${studioModels.length} downloaded models · ${data.base_url}`;}
 catch(error){$('models-status').textContent=error.message;}
}
async function studioModelAction(action,model,extra={}){
 if(studioModelBusy)return;
 if(typeof buildAgentBusy!=='undefined'&&buildAgentBusy||typeof busy!=='undefined'&&busy){$('models-status').textContent='Stop the active AI request before changing models.';return;}
 if(action==='reload'&&!confirm('Apply settings and reload '+model.display_name+'? This unloads the model and interrupts any requests using it.'))return;
 if(action==='unload'&&!confirm('Unload '+model.display_name+' from memory? Any active requests using it may stop. The downloaded file stays on disk.'))return;
 studioModelBusy=true;renderStudioModels();$('models-status').textContent=action==='load'?'Loading model… this can take a few minutes.':'Updating model…';
 try{const result=await api('/api/lm-studio',{action,model:model.key,...extra},165000);if(action==='select'){applySettings(result);renderProvider();}if(action==='reload'||action==='load')modelDrafts.delete(model.key);await refreshStudioModels();refreshGpuMemory();const checks=result.verification||{},unverified=Object.entries(checks).filter(([,v])=>v!=='applied').map(([k,v])=>k+': '+v);$('models-status').textContent=action==='select'?'Selected for Assistant, Create, and the next OpenCode request.':action==='reload'?'Reload complete. '+(unverified.length?'Check applied settings: '+unverified.join(', '):'Requested settings verified.') :action==='load'?'Model loaded. Choose Use model to select it.':'Model unloaded; downloaded files preserved.';}
 catch(error){$('models-status').textContent=error.message;}
 finally{studioModelBusy=false;renderStudioModels();}
}
function renderStudioModels(){
 const root=$('model-cards'),filter=$('model-filter').value.toLowerCase();root.replaceChildren();
 for(const model of studioModels.filter(m=>(m.display_name+' '+m.key).toLowerCase().includes(filter))){
  const card=modelElement('section',undefined,'local-model-card'),instances=model.loaded_instances||[],selected=instances.some(i=>i.id===studioSelected),title=modelElement('div',undefined,'local-model-heading');
  title.append(modelElement('h3',model.display_name),modelElement('span',selected?'SELECTED':instances.length?'LOADED':'ON DISK',instances.length?'model-badge loaded':'model-badge'));card.append(title,modelElement('p',model.key,'model-id'));
  const caps=model.capabilities||{},meta=[model.type,model.params_string,model.quantization?.name,model.size_bytes? (model.size_bytes/1e9).toFixed(2)+' GB':null,caps.vision?'Vision':null,caps.trained_for_tool_use?'Tool use':null].filter(Boolean);
  card.append(modelElement('p',meta.join(' · '),'micro'));card.append(modelElement('p','Maximum context: '+Number(model.max_context_length||0).toLocaleString(),'micro'));
  for(const instance of instances){const config=instance.config||{};card.append(modelElement('p','Loaded context: '+Number(config.context_length||0).toLocaleString()+' · Batch: '+(config.eval_batch_size??'—')+' · Parallel: '+(config.parallel??'—'),'model-loaded-info'));const details=modelElement('details');details.append(modelElement('summary','Loaded configuration'),modelElement('pre',JSON.stringify(config,null,2)));card.append(details);const unload=modelElement('button','Unload','quiet');unload.disabled=studioModelBusy;unload.onclick=()=>studioModelAction('unload',model,{instance_id:instance.id});card.append(unload);}
  if(instances.length&&model.type==='llm'){const select=modelElement('button',selected?'Selected':'Use model','primary');select.disabled=studioModelBusy||selected;select.onclick=()=>studioModelAction('select',model);card.append(select);}
  if(model.type==='llm'&&!instances.length){const tune=modelElement('button','Auto-tune & load','primary');tune.title='Pick the largest context that fits your GPU, then load';tune.disabled=studioModelBusy;tune.onclick=()=>autoTuneModel(model,true);card.append(tune);}
  if(model.type==='llm')card.append(modelAdvancedControls(model));
  else if(!instances.length){const load=modelElement('button','Load','primary');load.disabled=studioModelBusy;load.onclick=()=>studioModelAction('load',model);card.append(load);}

  root.append(card);
 }
 if(!root.children.length)root.append(modelElement('p','No matching models.','micro'));
}
$('model-manager').onclick=()=>{$('models-dialog').showModal();refreshStudioModels();refreshGpuMemory();};
$('refresh-model-manager').onclick=()=>{if(!studioModelBusy)refreshStudioModels();};
$('model-filter').oninput=renderStudioModels;

function modelAdvancedControls(model){
 const instance=model.loaded_instances?.[0],config=instance?.config||{};
 let draft=modelDrafts.get(model.key);if(!draft){draft={};for(const key of ['context_length','eval_batch_size','flash_attention','offload_kv_cache_to_gpu'])if(key in config)draft[key]=config[key];modelDrafts.set(model.key,draft);}
 const details=modelElement('details'),summary=modelElement('summary','Advanced settings');details.append(summary);details.open=modelAdvancedOpen.has(model.key);details.ontoggle=()=>{if(details.open)modelAdvancedOpen.add(model.key);else modelAdvancedOpen.delete(model.key);};
 const grid=modelElement('div',undefined,'model-load-controls');
 for(const [key,title,help,min,max] of [
  ['context_length','Context length','Conversation capacity. Larger windows need more memory.',512,model.max_context_length],
  ['eval_batch_size','Evaluation batch','Tokens processed together. Smaller batches can reduce peak memory.',32,2048]]){
  const label=modelElement('label',title),input=modelElement('input');input.type='number';input.min=min;input.max=max;input.value=draft[key]??'';input.placeholder='LM Studio default';input.disabled=studioModelBusy;input.setAttribute('aria-label',title+' for '+model.display_name);
  input.oninput=()=>{if(input.value)draft[key]=Number(input.value);else delete draft[key];};label.append(input,modelElement('small',help));grid.append(label);
 }
 for(const [key,title,help] of [['flash_attention','Flash Attention','Efficient attention; usually keep enabled.'],['offload_kv_cache_to_gpu','Conversation cache on GPU','Fast GPU memory; turn off to use system RAM instead.']]){
  const label=modelElement('label',title),select=modelElement('select');select.setAttribute('aria-label',title+' for '+model.display_name);for(const [v,t] of [['','LM Studio default'],['true','On'],['false','Off']])select.add(new Option(t,v));select.value=key in draft?String(draft[key]):'';select.disabled=studioModelBusy;select.onchange=()=>{if(select.value)draft[key]=select.value==='true';else delete draft[key];};label.append(select,modelElement('small',help));grid.append(label);
 }
 details.append(grid);
 const current=modelElement('p','LM Studio only: Parallel '+(config.parallel??'not reported')+' · MTP '+(config.speculative_draft_mtp===undefined?'not reported':config.speculative_draft_mtp?'On':'Off')+' · GPU offload is managed in LM Studio.','micro');details.append(current);
 details.append(modelElement('p','These controls are not exposed by the supported REST API. For this PC, set Parallel to 1 in LM Studio.','micro'));
 const actions=modelElement('div',undefined,'model-controls');
 const preset=modelElement('button','Auto-tune for this PC','quiet');preset.title='Fill in the largest context that fits your GPU (not applied until you load or reload)';preset.disabled=studioModelBusy;preset.onclick=()=>autoTuneModel(model,false);
 const restore=modelElement('button','Restore previous values','quiet');restore.disabled=studioModelBusy||!modelPrevious.has(model.key);restore.onclick=()=>{modelDrafts.set(model.key,{...modelPrevious.get(model.key)});renderStudioModels();$('models-status').textContent='Previous values restored to the form. Apply & reload to use them.';};
 const apply=modelElement('button',instance?'Apply & reload':'Load with settings','primary');apply.disabled=studioModelBusy||model.loaded_instances?.length>1;apply.onclick=()=>{modelPrevious.set(model.key,Object.fromEntries(Object.entries(config).filter(([key])=>['context_length','eval_batch_size','flash_attention','offload_kv_cache_to_gpu'].includes(key))));studioModelAction(instance?'reload':'load',model,{...draft,...(instance?{instance_id:instance.id}:{})});};
 actions.append(preset,restore,apply);details.append(actions,modelElement('p','Reload interrupts active work. Actual applied values appear under Loaded configuration.','micro'));return details;
}
async function autoTuneModel(model,load){
 if(studioModelBusy)return;
 studioModelBusy=true;renderStudioModels();$('models-status').textContent='Measuring what fits on your GPU…';
 let tuned;
 try{tuned=await api('/api/lm-studio',{action:'recommend',model:model.key},90000);}
 catch(error){$('models-status').textContent=error.message;return;}
 finally{studioModelBusy=false;renderStudioModels();}
 const instance=model.loaded_instances?.[0];
 modelDrafts.set(model.key,{...(modelDrafts.get(model.key)||{}),...tuned.settings});modelAdvancedOpen.add(model.key);renderStudioModels();
 if(load){await studioModelAction('load',model,tuned.settings);$('models-status').textContent=tuned.note+' '+$('models-status').textContent;}
 else $('models-status').textContent=tuned.note+(instance?' Click Apply & reload to use it.':' Click Load with settings to use it.');
}
let gpuRefreshBusy=false;
async function refreshGpuMemory(){
 if(gpuRefreshBusy||!$('models-dialog').open)return;gpuRefreshBusy=true;
 try{const data=await api('/api/lm-studio',{action:'hardware'},7000);$('models-gpu').textContent=data.available?data.gpus.map(g=>g.name+' · '+(g.used_mb/1024).toFixed(1)+' / '+(g.total_mb/1024).toFixed(1)+' GB used · '+g.free_mb+' MB free').join(' | '):'GPU memory unavailable (NVIDIA monitoring required).';}
 catch{$('models-gpu').textContent='GPU memory could not be read.';}finally{gpuRefreshBusy=false;}
}
setInterval(()=>{if($('models-dialog').open)refreshGpuMemory();},5000);
