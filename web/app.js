const $ = (id) => document.getElementById(id);
let providerSettings = null, activeProvider = 'openai';
let attachments = [], systemPrompt = '';
try { systemPrompt = localStorage.getItem('jarvis-personality') || ''; } catch {}
let token = '', busy = false, listening = false, history = [], recognition;
const speech = window.speechSynthesis;
// Voice is optional: chat and saved conversations must work before it loads.
function stopAssistantVoice() {
  if (typeof window.stopVoice === 'function') return window.stopVoice();
  window.speechSynthesis?.cancel();
}
function speakAssistantReply(text) {
  if (typeof window.say === 'function') return window.say(text);
  if ($('speak').checked) $('voice-note').textContent = 'Voice is still loading. Your reply is available in chat.';
}
let activeRequestId=null;
let headlineState='idle';
function activity(text, mode = '') {
  $('activity').textContent = text; $('core').className = `core ${mode}`;
  const state=text==='CONNECTION UNAVAILABLE'?'offline':text==='PREPARING VOICE'?'voice':mode||'idle';
  const headlines={
    idle:['Ready when','you are.','Bring a question, an idea, or something to explore.'],
    compacting:['Keeping the','thread.','Summarizing earlier discussion while preserving the originals.'],
    thinking:['Working on','your answer.','Processing your message and the available context.'],
    searching:['Searching','the web.','Looking for sources relevant to your question.'],
    reading:['Reading','the sources.','Using the search results to prepare your answer.'],
    analyzing:['Taking a','closer look.','Processing the attachments you shared.'],
    listening:['Go ahead.','I’m listening.','Your microphone is active. Say what’s on your mind.'],
    speaking:['Let’s talk','it through.','Playing your spoken reply.'],
    transcribing:['Catching','your words.','Transcribing your microphone locally.'],
    voice:['Giving words','a voice.','Generating speech locally on your computer.'],
    offline:['Connection','interrupted.','Start the local server, then refresh to reconnect.']
  };
  if(state===headlineState)return;
  headlineState=state;
  const copy=headlines[state]||headlines.thinking;
  $('headline-lead').textContent=copy[0];$('headline-accent').textContent=copy[1];$('headline-detail').textContent=copy[2];
  const heading=$('live-headline');
  heading.getAnimations?.().forEach(animation=>animation.cancel());
  if(!matchMedia('(prefers-reduced-motion: reduce)').matches)heading.animate?.([{opacity:.3,transform:'translateY(7px)'},{opacity:1,transform:'translateY(0)'}],{duration:320,easing:'ease-out'});
}
function addMessage(role, text, source = '') {
  const article = document.createElement('article'); article.className = `message ${role}`;
  const label = document.createElement('div'); label.className = 'message-label'; label.textContent = role === 'user' ? 'YOU' : 'DreadOS AI';
  const badge = document.createElement('span'); badge.textContent = source.toUpperCase(); label.append(badge);
  const rich = role === 'assistant' && text && window.renderBuildMarkdown;
  const body = rich ? renderBuildMarkdown(text) : document.createElement('p');
  if (!rich) { body.textContent = text; if(role === 'assistant' && text) body.dataset.pendingMarkdown = text; } article.append(label, body); $('messages').append(article);
  $('messages').scrollTop = $('messages').scrollHeight; return article;
}
function setBusy(value) { busy = value; $('send').disabled = value || !token; $('attach').disabled = value; $('web-search').disabled = value; $('personality').disabled = value; $('mic').disabled = value || !recognition || !token; $('clear').disabled = value; $('setup').disabled = value || !token; document.querySelectorAll('[data-command]').forEach(b => b.disabled = value || !token); }
function browserSay(text) {
  if (!speech || !$('speak').checked) return;
  speech.cancel(); const utterance = new SpeechSynthesisUtterance(text); utterance.rate = 1; utterance.pitch = .9;
  const voices = speech.getVoices(); const voice = voices.find(v => v.lang === 'en-GB') || voices.find(v => v.lang.startsWith('en')); if (voice) utterance.voice = voice;
  utterance.onstart = () => { if (!busy && !listening) activity('SPEAKING', 'speaking'); };
  utterance.onend = utterance.onerror = () => { if (!busy && !listening) activity('SYSTEM READY'); };
  speech.speak(utterance);
}
function showPendingReply(){
  const node=addMessage('assistant','','working');node.classList.add('pending-reply');node.setAttribute('role','status');
  const line=node.querySelector('p');line.className='pending-line';
  const dots=document.createElement('span');dots.className='thinking-dots';dots.setAttribute('aria-hidden','true');
  for(let i=0;i<3;i++)dots.append(document.createElement('i'));
  const label=document.createElement('span');label.textContent='Preparing…';line.append(dots,label);
  return {node,update(stage){const labels={preparing:'Preparing…',thinking:'Thinking…',compacting:'Updating conversation memory…',searching:'Searching the web…',reading:'Reading sources & composing an answer…',analyzing:'Analyzing attachments…',complete:'Finishing up…'};label.textContent=labels[stage]||labels.thinking;activity(label.textContent.toUpperCase(),['searching','reading','analyzing','compacting'].includes(stage)?stage:'thinking');}};
}
async function send(text) {
  text = text.trim(); if (!text || busy || !token) return;
  if (!attachments.length && /^(?:please\s+)?(?:generate|create|draw|make)\s+(?:me\s+)?(?:an?\s+)?(?:image|picture|illustration|artwork)\b/i.test(text) && typeof openImageReview === 'function') { openImageReview(text); return; }
  try { await ensureConversation(); if(currentChat.archived)throw Error('Restore this chat in Chats before sending.'); } catch(error) { addMessage('assistant',error.message,'storage'); return; }
  stopAssistantVoice(); if (listening) recognition.abort();
  addMessage('user', text + (attachments.length ? '\nAttached: ' + attachments.map(a => a.name).join(', ') : '')); $('input').value = ''; setBusy(true); activity('THINKING', 'thinking');
  const requestId=crypto.randomUUID(),pending=showPendingReply();activeRequestId=requestId;let polling=false;
  const progressTimer=setInterval(async()=>{if(polling)return;polling=true;try{const r=await fetch('/api/chat-progress?id='+requestId,{headers:{'X-Jarvis-Token':token},signal:AbortSignal.timeout(3000)});if(r.ok){const progress=await r.json();if(pending.node.isConnected){pending.update(progress.stage);if(progress.text){let partial=pending.node.querySelector('.stream-text');if(!partial){partial=document.createElement('p');partial.className='stream-text';pending.node.append(partial);}partial.textContent=progress.text;}}}}catch{}finally{polling=false;}},700);
  try {
    const response = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json','X-Jarvis-Token':token},body:JSON.stringify({request_id:requestId,stream:true,message:text,chat_id:currentChat.id,version:currentChat.version,history:[],provider:activeProvider,attachments,system_prompt:systemPrompt,web_search:$('web-search').checked,use_tools:$('chat-tools').checked}),signal:AbortSignal.timeout(900000)});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Unable to complete the request.');
    pending.node.remove();
    const article = addMessage('assistant', data.reply, data.source);
    renderSavedResults(article,data.results);
    if(data.tool_proposal)renderToolProposal(article,data.tool_proposal);
    if(data.context?.compacted_messages){const note=document.createElement('small');note.className='context-note';note.textContent=`Memory includes ${data.context.compacted_messages} earlier messages${data.context.retrieved?' · original excerpts recalled':''}. Originals stay saved.`;article.append(note);}
    if(data.version!==undefined){currentChat.version=data.version;if(currentChat.title==='New chat')currentChat.title=text.slice(0,80);$('conversation-title').textContent=currentChat.title;}
    attachments=[]; renderAttachments(); history.push({role:'user',content:text},{role:'assistant',content:data.reply}); history = history.slice(-12); speakAssistantReply(data.reply); refreshLibrary().catch(()=>{});
  } catch (error) { addMessage('assistant', error.name === 'TimeoutError' ? 'The request timed out. Please try again.' : (error.message === 'Failed to fetch' ? 'Connection lost. Make sure DreadOS AI is running, then refresh this page.' : error.message), 'connection'); }
  finally { activeRequestId=null;clearInterval(progressTimer);pending.node.remove();setBusy(false); activity('SYSTEM READY'); $('input').focus(); }
}
$('chat').addEventListener('submit', event => { event.preventDefault(); send($('input').value); });
document.querySelectorAll('[data-command]').forEach(button => button.addEventListener('click', () => send(button.dataset.command)));
$('setup').onclick = () => { $('provider').value = activeProvider; renderProvider(); $('settings-feedback').textContent = ''; $('setup-dialog').showModal(); };
$('setup-dialog').addEventListener('close', () => { $('api-key').value = ''; });
$('clear').onclick = () => newConversation().catch(error=>addMessage('assistant',error.message,'storage'));
$('stop').onclick = () => { if(activeRequestId)api('/api/chat-cancel',{request_id:activeRequestId}).catch(()=>{}); stopAssistantVoice(); if (listening) recognition.abort(); if (!busy) activity('SYSTEM READY'); };
$('speak').onchange = () => { if (!$('speak').checked) stopAssistantVoice(); };

function tick() { $('clock').textContent = new Date().toLocaleString([], {weekday:'short',hour:'2-digit',minute:'2-digit'}).toUpperCase(); } tick(); setInterval(tick, 1000);
setBusy(false);
let connectingAssistant = false;
async function connectAssistant() {
  if (connectingAssistant) return;
  connectingAssistant = true;
  const status = $('connection');
  status.textContent = 'CONNECTING';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch('/api/status', {signal: controller.signal, cache: 'no-store'});
    if (!response.ok) throw new Error('Connection rejected (' + response.status + ')');
    const data = await response.json();
    token = data.token; applySettings(data); setBusy(false); checkStartup();
    activity('SYSTEM READY');
    restoreCurrentChat().catch(() => { $('sidebar-status').textContent = 'Chat history could not load. Tap the connection indicator to retry.'; });
    initLocation(data.location);
  } catch (error) {
    token = ''; setBusy(false);
    status.textContent = 'RETRY CONNECTION';
    status.title = error.name === 'AbortError' ? 'Connection timed out. Tap to retry.' : error.message;
    activity('CONNECTION UNAVAILABLE');
    $('headline-detail').textContent = 'Keep Tailscale connected, then tap Retry connection above.';
  } finally { clearTimeout(timer); connectingAssistant = false; }
}
$('connection').setAttribute('role', 'button');
$('connection').tabIndex = 0;
$('connection').onclick = connectAssistant;
$('connection').onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); connectAssistant(); } };

function applySettings(data) {
  providerSettings = data.providers; activeProvider = data.provider;
  const current = providerSettings[activeProvider];
  $('connection').textContent = current.configured ? `${current.name.toUpperCase()} CONFIGURED` : 'LOCAL MODE';
}
function renderProvider() {
  const id = $('provider').value, current = providerSettings[id];
  $('api-key').value = ''; $('model').value = current.model; $('workspace-id').value = current.workspace || '';
  $('workspace-field').hidden = id !== 'claude';
  $('local-fields').hidden = id !== 'local'; $('base-url').value = current.base_url || '';
  $('key-label').textContent = id === 'local' ? 'Server API key (optional)' : 'API key';
  $('provider-state').textContent = current.configured ? `${current.name} · key configured on this server` : `${current.name} · add a key to enable AI conversation`;
  $('api-key').placeholder = current.configured ? 'Leave blank to keep the configured key' : 'Paste your provider API key';
  $('remove-key').disabled = !current.has_key;
  if (id === 'local') { $('provider-state').textContent = 'LM Studio or another local OpenAI-compatible server'; $('api-key').placeholder = current.has_key ? 'Leave blank to keep the server key' : 'Leave blank if your server does not require a key'; }
  $('model-options').replaceChildren();
  for (const model of [...new Set([current.model, ...({openai:['gpt-6-astra'],claude:['claude-sonnet-5-5','claude-opus-5-5'],grok:['grok-4.7'],local:[]}[id])])]) {
    const option = document.createElement('option'); option.value = model; $('model-options').append(option);
  }
}
$('provider').onchange = () => { renderProvider(); $('settings-feedback').textContent = ''; };
async function saveProvider(action) {
  const previous = activeProvider;
  const payload = {action,provider:$('provider').value,key:$('api-key').value.trim(),model:$('model').value.trim(),workspace:$('workspace-id').value.trim(),base_url:$('base-url').value.trim()};
  $('provider-fields').disabled = true; $('settings-feedback').textContent = 'Updating local settings…';
  try {
    const response = await fetch('/api/settings', {method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Token':token},body:JSON.stringify(payload),signal:AbortSignal.timeout(10000)});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Could not update settings.');
    applySettings(data);
    if (previous !== activeProvider) {
      addMessage('assistant', `Provider changed to ${providerSettings[activeProvider].name}. This chat keeps its saved context.`);
    }
    renderProvider();
    $('settings-feedback').textContent = action === 'remove' ? 'Saved key removed.' : (data.ai ? `${providerSettings[activeProvider].name} configured. Send a message to try it.` : 'Provider selected. Add its API key to enable AI conversation.');
  } catch (error) { $('settings-feedback').textContent = error.name === 'TimeoutError' ? 'Settings request timed out. Refresh and try again.' : error.message; }
  finally { $('provider-fields').disabled = false; }
}
$('provider-form').addEventListener('submit', event => { event.preventDefault(); saveProvider('save'); });
$('remove-key').onclick = () => saveProvider('remove');

$('find-models').onclick = async () => {
  $('provider-fields').disabled = true; $('settings-feedback').textContent = 'Looking for local models…';
  try {
    const response = await fetch('/api/local-models', {method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Token':token},body:JSON.stringify({base_url:$('base-url').value.trim(),key:$('api-key').value.trim()}),signal:AbortSignal.timeout(12000)});
    const data = await response.json(); if (!response.ok) throw new Error(data.error);
    $('model-options').replaceChildren();
    for (const model of data.models) { const option = document.createElement('option'); option.value = model; $('model-options').append(option); }
    if (data.models.length && !data.models.includes($('model').value)) $('model').value = data.models[0];
    $('settings-feedback').textContent = data.models.length ? `Found ${data.models.length} model(s). Choose a Model ID, then use this provider.` : 'No models found. Download and load a chat model in your local server.';
  } catch (error) { $('settings-feedback').textContent = error.message; }
  finally { $('provider-fields').disabled = false; }
};

// Attachments stay in memory and are sent only with the current message.
function renderAttachments() {
  $('attachments').replaceChildren();
  attachments.forEach((item,index) => {
    const chip=document.createElement('div'); chip.className='attachment-chip';
    if(item.type==='image') { const img=document.createElement('img'); img.src='data:'+item.mime+';base64,'+item.data; img.alt=item.name; chip.append(img); }
    const name=document.createElement('span');name.textContent=item.name;
    const remove=document.createElement('button');remove.type='button';remove.className='quiet';remove.textContent='×';remove.setAttribute('aria-label','Remove '+item.name);
    remove.onclick=()=>{if(!busy){attachments.splice(index,1);renderAttachments();}};
    chip.append(name,remove);$('attachments').append(chip);
  });
}
async function attachFiles(files) {
  if(busy)return;
  $('attachment-status').textContent='';
  for(const file of files) {
    if(attachments.length>=3){$('attachment-status').textContent='Up to three files per message.';break;}
    try {
      if(['image/png','image/jpeg','image/webp'].includes(file.type)) {
        if(file.size>4000000)throw Error('Each image must be under 4 MB.');
        if(attachments.reduce((n,a)=>n+(a.data?a.data.length*.75:a.text.length),0)+file.size>9000000)throw Error('Total attachments must be under 9 MB.');
        const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('Could not read file.'));reader.readAsDataURL(file);});
        attachments.push({type:'image',name:file.name,mime:file.type,data});
      } else {
        if(!/\.(txt|md|csv|json|py|js|html|css)$/i.test(file.name))throw Error('Use PNG, JPEG, WebP, or text/code files. PDF and video are not supported yet.');
        if(file.size>160000)throw Error('Text files must be under 40,000 characters.');
        const text=await file.text();if(text.length>40000)throw Error('Text files must be under 40,000 characters.');
        attachments.push({type:'text',name:file.name,text});
      }
    } catch(error){$('attachment-status').textContent=error.message;}
  }
  renderAttachments();$('files').value='';
}
$('attach').onclick=()=>$('files').click();
$('files').onchange=()=>attachFiles($('files').files);
$('input').addEventListener('paste',event=>{const images=[...event.clipboardData.files].filter(f=>f.type.startsWith('image/'));if(images.length){event.preventDefault();attachFiles(images);}});
const personalityPresets={
  jarvis:'Be DreadOS AI: composed, resourceful, concise, and subtly witty. Address me naturally. Give the useful answer first, then suggest a practical next step when appropriate.',
  cyberpunk:'Be a cyberpunk creative partner: sharp, resourceful, independent, and dryly witty. Use a restrained neon-noir voice with occasional street-tech imagery, while keeping answers clear and useful. Explore futuristic cities, digital identity, privacy, DIY technology, and the human cost of power. For creative work, suggest vivid atmosphere, bold visual contrasts, and original stories. Avoid forced slang and never let roleplay obscure facts or your actual capabilities.',
  solarpunk:'Be a solarpunk collaborator: hopeful, grounded, inventive, and community-minded. Combine ecological imagination with practical engineering, repair, accessibility, and shared prosperity. For creative work, draw on living architecture, warm sunlight, lush greenery, handmade materials, and technology that serves people and nature. Offer achievable steps and honest tradeoffs; avoid greenwashing, vague utopian promises, or unsupported sustainability claims.',
  musician:'Be a versatile musician, songwriter, and production collaborator. Help develop original lyrics, melodies described through notes or scale degrees, chord progressions, rhythms, arrangements, sound palettes, and recording or mixing plans. Adapt to my genre, skill level, instruments, and available tools. Give concrete musical examples with key, tempo, meter, and song structure when useful. Explain why choices work, preserve my creative voice, and offer practical alternatives. Distinguish musical suggestions from audio you have actually heard; never claim to listen to or render audio without the necessary tools.',
  creative:'Be an imaginative creative partner. Offer distinctive ideas, strong hooks, and concrete examples. Avoid generic marketing language. Help me turn rough concepts into polished content.',
  technical:'Be a precise technical collaborator. Explain tradeoffs, state assumptions, and provide practical working examples. Flag uncertainty and never invent test results.',
  coach:'Be a patient, encouraging coach. Break complex tasks into manageable steps. Ask focused questions when needed and help me learn without overwhelming me.',custom:''
};
$('personality').onclick=()=>{
  $('system-prompt').value=systemPrompt || personalityPresets.jarvis;
  $('personality-preset').value=Object.keys(personalityPresets).find(k=>personalityPresets[k]===$('system-prompt').value)||'custom';
  $('personality-status').textContent='';$('personality-dialog').showModal();
};
$('personality-preset').onchange=()=>{if($('personality-preset').value!=='custom')$('system-prompt').value=personalityPresets[$('personality-preset').value];};
$('system-prompt').oninput=()=>{$('personality-preset').value='custom';};
$('close-personality').onclick=()=>$('personality-dialog').close();
$('save-personality').onclick=async ()=>{
  const nextPrompt=$('system-prompt').value.trim();
  try { if(currentChat){await libraryRequest({action:'update',id:currentChat.id,version:currentChat.version,personality:nextPrompt});currentChat=await fetchConversation(currentChat.id);} } catch(error){$('personality-status').textContent=error.message;return;}
  systemPrompt=nextPrompt;
  try{localStorage.setItem('jarvis-personality',systemPrompt);$('personality-dialog').close();}
  catch{$('personality-status').textContent='Applied for this tab; browser storage is unavailable.';}
};

let customPresets=[];
try { const stored=JSON.parse(localStorage.getItem('jarvis-custom-presets')||'[]'); if(Array.isArray(stored))customPresets=stored.filter(p=>p && typeof p.name==='string' && typeof p.prompt==='string').slice(0,20); } catch {}
function renderCustomPresets(){
  $('personality-preset').querySelectorAll('[data-custom]').forEach(o=>o.remove());
  customPresets.forEach((p,i)=>{const option=document.createElement('option');option.value='saved-'+i;option.dataset.custom='true';option.textContent=p.name;$('personality-preset').append(option);});
}
renderCustomPresets();
$('personality-preset').onchange=()=>{
  const selected=$('personality-preset').value;
  if(selected.startsWith('saved-'))$('system-prompt').value=customPresets[Number(selected.slice(6))].prompt;
  else if(selected!=='custom')$('system-prompt').value=personalityPresets[selected];
};
$('save-preset').onclick=()=>{
  const name=$('preset-name').value.trim(),prompt=$('system-prompt').value.trim();
  if(!name || !prompt){$('personality-status').textContent='Enter a preset name and prompt first.';return;}
  const found=customPresets.findIndex(p=>p.name.toLowerCase()===name.toLowerCase());
  if(found<0 && customPresets.length>=20){$('personality-status').textContent='20 presets saved. Use an existing name to update it.';return;}
  const next=[...customPresets];if(found<0)next.push({name,prompt});else next[found]={name,prompt};
  try{localStorage.setItem('jarvis-custom-presets',JSON.stringify(next));customPresets=next;renderCustomPresets();$('personality-preset').value='saved-'+(found<0?next.length-1:found);$('personality-status').textContent='Preset saved. Choose Save personality to apply it.';}
  catch{$('personality-status').textContent='Browser storage is unavailable; preset was not saved.';}
};

let searchLocation={mode:'auto',city:''};
function showLocation(value){searchLocation=value;$('location-settings').textContent=value.mode==='off'?'Location off · Change':value.city?`Using location: ${value.city} · Change`:'Location unavailable · Set city';}
async function initLocation(value){showLocation(value||searchLocation);if(searchLocation.mode==='auto'){try{showLocation(await api('/api/location',{mode:'auto'},15000));}catch{$('location-settings').textContent='Location unavailable · Set city';}}}
$('location-settings').onclick=()=>{$('location-mode').value=searchLocation.mode;$('location-city').value=searchLocation.city||'';$('location-city').disabled=searchLocation.mode!=='manual';$('location-feedback').textContent=searchLocation.error||'';$('location-dialog').showModal();};
$('location-mode').onchange=()=>{$('location-city').disabled=$('location-mode').value!=='manual';};
$('close-location').onclick=()=>$('location-dialog').close();
$('location-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{const value=await api('/api/location',{mode:$('location-mode').value,city:$('location-city').value},15000);showLocation(value);$('location-feedback').textContent=value.error||'Saved.';if(!value.error)$('location-dialog').close();}catch(error){$('location-feedback').textContent=error.message;}finally{button.disabled=false;}};

function renderToolProposal(article, proposal) {
  const box=document.createElement('section');box.className='tool-approval';
  const heading=document.createElement('strong');heading.textContent=proposal.service+' · '+proposal.tool;
  const details=document.createElement('pre');details.textContent=JSON.stringify(proposal.arguments,null,2);
  const notice=document.createElement('p');notice.textContent='These inputs will be sent to this service. Generation may spend service credits; other tools may change external data. Review before running.';
  const approve=document.createElement('button');approve.className='primary';approve.textContent='Approve & run';
  const cancel=document.createElement('button');cancel.className='quiet';cancel.textContent='Dismiss';
  cancel.onclick=()=>{approve.disabled=true;cancel.disabled=true;notice.textContent='Dismissed. No tool was run.';};
  approve.onclick=async()=>{
    approve.disabled=true;cancel.disabled=true;notice.textContent='Running '+proposal.tool+'…';
    const approvedChat=currentChat?.id;
    try {
      const result=await api('/api/chat-tool-run',{proposal_id:proposal.id},700000);
      if(currentChat?.id!==approvedChat){notice.textContent='Tool finished in its original chat. Reopen that chat to see the result.';return;}
      const output=addMessage('assistant',result.reply,result.source);
      if(result.media_item)output.append(mediaCard(result.media_item));
      for(const part of result.result?.content||[]) {
        if(part.type==='image'&&['image/png','image/jpeg','image/webp'].includes(part.mimeType)){
          const img=document.createElement('img');img.className='saved-image';img.alt='Tool result';img.src='data:'+part.mimeType+';base64,'+part.data;output.append(img);
        }
        const urls=part.type==='resource_link'?[part.uri]:(part.text||'').match(/https:\/\/[^\s<>"')]+/g)||[];
        for(const url of urls)if(/^https:\/\//.test(url)){const a=document.createElement('a');a.href=url;a.textContent='Open result ↗';a.target='_blank';a.rel='noopener noreferrer';output.append(a);}
      }
      if(result.version!==undefined && currentChat) currentChat.version=result.version;
      notice.textContent=result.warning||'Tool finished.';
    }catch(error){notice.textContent=error.message+' Check the service before retrying to avoid duplicate actions.';}
  };
  box.append(heading,details,notice,approve,cancel);article.append(box);
}
async function checkStartup() {
  try {
    const r=await fetch('/api/startup'); const state=await r.json();
    if(state.stage==='starting'){$('connection').textContent=state.message;setTimeout(checkStartup,2500);}
    else if(state.stage==='attention'){$('connection').textContent='AI NEEDS ATTENTION';$('headline-detail').textContent=state.message;}
    else if(providerSettings)applySettings({providers:providerSettings,provider:activeProvider});
  }catch{}
}
