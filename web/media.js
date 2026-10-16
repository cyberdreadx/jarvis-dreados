let imageCatalog=null, imageRequest=null, imageOrigin=null, mediaItems=[], mediaLoading=false;
const mediaWatches=new Map();
async function openImageReview(prompt='') {
  if(!token)return;
  imageOrigin=currentChat?.id || null;
  imageCatalog=null;imageRequest=crypto.randomUUID();
  $('image-prompt').value=prompt;$('image-model').replaceChildren();
  $('image-generate').disabled=true;$('image-status').textContent='Checking models and current prices…';$('image-price').textContent='';
  if(!$('image-dialog').open)$('image-dialog').showModal();
  const request=imageRequest;
  try {
    const value=await api('/api/media',{action:'catalog'},45000);
    if(request!==imageRequest)return;
    imageCatalog=value;
    for(const model of value.models)$('image-model').append(new Option(model.label,model.id));
    updateImagePrice();$('image-status').textContent='Ready to review.';$('image-generate').disabled=false;
  }catch(error){$('image-status').textContent=error.message;}
}
function updateImagePrice(){
  const model=imageCatalog?.models.find(m=>m.id===$('image-model').value);
  $('image-price').textContent=model?`${model.credits} credits · one image · GLTCH Runner`:'';
}
$('image-model').onchange=updateImagePrice;
$('image-close').onclick=()=>{$('image-dialog').close();};
$('chat-image').onclick=()=>openImageReview($('input').value);
$('library-image').onclick=()=>openImageReview();
$('image-form').onsubmit=async event=>{
  event.preventDefault();if(!imageCatalog)return;
  $('image-generate').disabled=true;$('image-status').textContent='Submitting your approved image…';
  try {
    const {item}=await api('/api/media',{action:'generate',approved:true,request_id:imageRequest,ticket:imageCatalog.ticket,model:$('image-model').value,prompt:$('image-prompt').value,shape:$('image-shape').value},15000);
    $('image-dialog').close();
    if(imageOrigin===currentChat?.id && !$('assistant-view').hidden){
      const article=addMessage('assistant','Your image is generating. It will also appear in Library.','GLTCH');
      article.append(mediaCard(item));
    } else {showView('media');}
    watchMedia(item.id);loadMedia();
  }catch(error){$('image-status').textContent=error.message+' You can retry this submission safely; it keeps the same request ID.';}
  finally{$('image-generate').disabled=false;}
};
function mediaCard(item){
  const card=element('article',undefined,'media-card');card.dataset.mediaId=item.id;
  const stage={queued:'Queued',running:'Generating',complete:'Ready',failed:'Failed',unknown:'Check service',needs_check:'Check job'}[item.status]||item.status;
  const head=element('div',undefined,'media-card-heading');head.append(element('span',item.kind.toUpperCase(),'eyebrow'),element('span',stage,'media-stage'));card.append(head);
  for(const asset of item.assets||[]){
    if(!/^https:\/\//.test(asset.url)&&!/^data:image\/(png|jpeg|webp);base64,/.test(asset.url))continue;
    const media=document.createElement(asset.kind==='video'?'video':'img');
    if(asset.kind==='video'){media.controls=true;media.preload='metadata';}else {media.alt=item.prompt||'Generated image';media.loading='lazy';}
    media.src=asset.url;media.referrerPolicy='no-referrer';
    media.onerror=()=>{media.hidden=true;const message=element('p','Preview unavailable. Open the original result below.','micro');media.after(message);};
    card.append(media);
    const link=element('a','Open / download ↗','quiet');link.href=asset.url;link.target='_blank';link.rel='noopener noreferrer';if(asset.url.startsWith('data:'))link.download='dreados-image';card.append(link);
  }
  card.append(element('p',(item.prompt||item.text||'Saved result').slice(0,260),'media-prompt'));
  card.append(element('small',`${item.model||item.service||'Draft'} · ${new Date(item.created*1000).toLocaleString()}`,'micro'));
  if(['running','queued'].includes(item.status))card.append(element('p','Generating on GLTCH. You can leave this page.','media-progress'));
  if(item.detail){const details=element('details');details.append(element('summary','Job details'),element('pre',item.detail));card.append(details);}
  if(item.kind==='draft'){
    const open=element('button','Edit draft ↗','quiet');open.onclick=()=>{showView('create');setKind(item.format||'post');$('draft-output').value=item.text;$('creative-brief').value=item.prompt||'';$('output-title').textContent='Your saved draft.';$('draft-meta').textContent='Shared Library';outputChanged();};card.append(open);
    const download=element('button','Download text','quiet');download.onclick=()=>{const url=URL.createObjectURL(new Blob([item.text],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='dreados-draft.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};card.append(download);
  }else{
    const reuse=element('button','Reuse prompt','quiet');reuse.onclick=()=>openImageReview(item.prompt);card.append(reuse);
  }
  return card;
}
function renderMedia(){
  const query=$('media-search').value.toLowerCase(),filter=$('media-filter').value;
  const items=mediaItems.filter(i=>(filter==='all'||i.kind===filter)&&`${i.prompt||''} ${i.text||''} ${i.model||''}`.toLowerCase().includes(query));
  $('media-grid').replaceChildren(...items.map(mediaCard));
  if(!items.length){const empty=element('div',undefined,'media-empty');empty.append(element('span','✳'),element('h2',mediaItems.length?'No matches yet.':'Your next idea belongs here.'),element('p',mediaItems.length?'Try a different search or filter.':'Generate an image from chat, or save a draft from Create. It will be waiting on every device.'));$('media-grid').append(empty);}
}
async function loadMedia(){
  if(!token||mediaLoading)return;mediaLoading=true;
  try{const result=await api('/api/media',{action:'list'},15000);mediaItems=result.items;renderMedia();$('media-status').textContent=`${mediaItems.length} saved items · shared through your PC`;for(const item of mediaItems)if(['running','queued'].includes(item.status))watchMedia(item.id);}
  catch(error){$('media-status').textContent=error.message;}
  finally{mediaLoading=false;}
}
function watchMedia(id){
  if(mediaWatches.has(id))return;
  mediaWatches.set(id,true);
  const poll=async()=>{
    try{
      const {item}=await api('/api/media',{action:'get',id},15000);
      // Update only this card. Other previews and controls keep their state.
      document.querySelectorAll('[data-media-id]').forEach(card=>{if(card.dataset.mediaId===id)card.replaceWith(mediaCard(item));});
      mediaItems=mediaItems.map(old=>old.id===id?item:old);
      if(!['running','queued'].includes(item.status)){mediaWatches.delete(id);return;}
    }catch{ $('media-status').textContent='Connection interrupted. Jobs remain saved; reconnect to check progress.'; }
    setTimeout(poll,4000);
  };setTimeout(poll,1500);
}
$('media-refresh').onclick=loadMedia;$('media-search').oninput=renderMedia;$('media-filter').onchange=renderMedia;
$('media-import').onclick=async()=>{
  const button=$('media-import');button.disabled=true;
  try{
    // Remove each imported legacy draft only after its shared save succeeds.
    for(const draft of drafts()){
      await api('/api/media',{action:'draft',text:draft.text,brief:draft.brief||'',format:draft.kind});
      localStorage.setItem(draftKey,JSON.stringify(drafts().filter(d=>d.id!==draft.id)));
    }
    await loadMedia();renderLibrary();$('media-status').textContent='Browser drafts imported into shared Library.';
  }catch(error){$('media-status').textContent=error.message;}
  finally{button.disabled=false;}
};
