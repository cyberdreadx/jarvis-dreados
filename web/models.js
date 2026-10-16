let studioModels=[],studioSelected='',studioModelBusy=false;
function modelElement(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
async function refreshStudioModels(){
 $('models-status').textContent='Connecting to LM Studio…';
 try{const data=await api('/api/lm-studio',{action:'list'},15000);studioModels=data.models;studioSelected=data.selected;renderStudioModels();$('models-status').textContent=`Connected · ${studioModels.length} downloaded models · ${data.base_url}`;}
 catch(error){$('models-status').textContent=error.message;}
}
async function studioModelAction(action,model,extra={}){
 if(studioModelBusy)return;
 if(typeof buildAgentBusy!=='undefined'&&buildAgentBusy||typeof busy!=='undefined'&&busy){$('models-status').textContent='Stop the active AI request before changing models.';return;}
 if(action==='unload'&&!confirm('Unload '+model.display_name+' from memory? Any active requests using it may stop. The downloaded file stays on disk.'))return;
 studioModelBusy=true;renderStudioModels();$('models-status').textContent=action==='load'?'Loading model… this can take a few minutes.':'Updating model…';
 try{const result=await api('/api/lm-studio',{action,model:model.key,...extra},165000);if(action==='select'){applySettings(result);renderProvider();}await refreshStudioModels();$('models-status').textContent=action==='select'?'Selected for Assistant, Create, and the next OpenCode request.':action==='load'?'Model loaded. Choose Use model to select it.':'Model unloaded; downloaded files preserved.';}
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
  if(!instances.length){const controls=modelElement('div',undefined,'model-load-controls'),context=modelElement('input'),batch=modelElement('input');context.type='number';context.min='512';context.max=String(model.max_context_length);context.placeholder='LM Studio default';context.setAttribute('aria-label','Context length for '+model.display_name);batch.type='number';batch.min='32';batch.max='2048';batch.placeholder='Default';batch.setAttribute('aria-label','Batch size for '+model.display_name);const label=modelElement('label','Context length');label.append(context);controls.append(label);if(model.type==='llm'){const label=modelElement('label','Evaluation batch');label.append(batch);controls.append(label);}const load=modelElement('button','Load','primary');load.disabled=studioModelBusy;load.onclick=()=>studioModelAction('load',model,{...(context.value?{context_length:Number(context.value)}:{}),...(batch.value?{eval_batch_size:Number(batch.value)}:{})});controls.append(load);card.append(controls);}
  root.append(card);
 }
 if(!root.children.length)root.append(modelElement('p','No matching models.','micro'));
}
$('model-manager').onclick=()=>{$('models-dialog').showModal();refreshStudioModels();};
$('refresh-model-manager').onclick=()=>{if(!studioModelBusy)refreshStudioModels();};
$('model-filter').oninput=renderStudioModels;
