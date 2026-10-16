// Upgrade early chat text once the optional rich-text/editor bundle is ready.
if (window.renderBuildMarkdown) document.querySelectorAll('[data-pending-markdown]').forEach(node => node.replaceWith(renderBuildMarkdown(node.dataset.pendingMarkdown)));
let buildAgentBusy=false,buildProgressKey='',buildProgressAt=Date.now();
function buildOrbState(data){
 if(data.permissions?.length)return 'approval';
 const messages=data.messages||[],lastUser=messages.findLastIndex(m=>m.info.role==='user');
 const latest=messages.slice(lastUser+1).findLast(m=>m.info.role==='assistant');
 if(data.status?.type==='retry')return 'retry';
 if(latest?.info.error)return latest.info.error.name==='MessageAbortedError'?'stopped':'error';
 if(data.status?.type==='idle')return 'idle';
 const active=(latest?.parts||[]).findLast(p=>p.type==='tool'&&['running','pending'].includes(p.state?.status));
 if(active){const tool=active.tool.toLowerCase();if(/edit|write|patch/.test(tool))return 'coding';if(/bash|shell|command/.test(tool))return 'running';if(/web|search/.test(tool))return 'searching';if(/read|glob|grep|list/.test(tool))return 'reading';return 'working';}
 if(latest?.parts?.some(p=>p.type==='text'&&p.text))return 'responding';
 return 'thinking';
}
function setBuildOrb(state){
 const states={offline:['Offline','Connect to start building'],connecting:['Connecting','Starting the coding engine'],idle:['Ready','Your next idea starts here'],thinking:['Thinking','Working on your request'],reading:['Reading files','Exploring project context'],coding:['Coding','Editing project files'],running:['Running commands','Executing a project task'],searching:['Searching','Looking for information'],approval:['Approval needed','Review the requested action below'],responding:['Responding','Writing a reply'],working:['Using tools','Working on your project'],retry:['Retrying','Waiting to try again'],error:['Needs attention','Check the error in chat'],stopped:['Stopped','Task cancelled'],stalled:['No recent progress','Use Stop, then retry or start a new session']};
 const [label,detail]=states[state]||states.working;
 if($('build-presence').dataset.state===state)return;
 $('build-presence').dataset.state=state;$('build-orb-label').textContent=label;$('build-orb-detail').textContent=detail;
}
let buildView='editor',buildLiveTimer=null;
const buildClosedFolders=new Set();
let buildMessagesSnapshot='',buildPermissionsSnapshot='';
let buildTimer=null,buildPolling=false,buildProject='',buildFiles=[],buildFile='',buildBuffers=new Map(),buildEpoch=0,buildBusy=false;
async function buildRequest(action,extra={}){return api('/api/build',{action,project:$('build-project').value,session:$('build-session').value,...extra},30000);}
function setBuildConnected(connected){if(!connected)setBuildOrb('offline');else if(['offline','connecting'].includes($('build-presence').dataset.state))setBuildOrb('idle');$('connect-build').textContent=connected?'● Connected':'Reconnect OpenCode';$('connect-build').classList.toggle('is-connected',connected);}
async function buildAction(fn){try{await fn();}catch(error){$('build-status').textContent=error.message;if($('build-presence').dataset.state!=='offline')setBuildOrb('error');}}
function buildDirty(){return [...buildBuffers.values()].some(b=>b.content!==b.saved);}
window.addEventListener('beforeunload',e=>{if(buildDirty()){e.preventDefault();e.returnValue='';}});
function editorPosition(){const e=$('build-editor'),before=e.value.slice(0,e.selectionStart);$('build-cursor').textContent=`Ln ${before.split('\n').length}, Col ${before.length-before.lastIndexOf('\n')}`;}
function renderBuildTabs(){
 $('build-file-tabs').replaceChildren();
 for(const [path,buffer] of buildBuffers){const tab=document.createElement('div');tab.className='ide-tab-group';const b=document.createElement('button');b.className='ide-file-tab';b.textContent=path.split('/').pop()+(buffer.content!==buffer.saved?' •':'');b.setAttribute('aria-current',String(path===buildFile));b.onclick=()=>buildAction(()=>openBuildFile(path));const close=document.createElement('button');close.className='ide-tab-close';close.textContent='×';close.setAttribute('aria-label','Close '+path);close.onclick=()=>{if(buffer.content!==buffer.saved&&!confirm('Discard unsaved changes to '+path+'?'))return;buildBuffers.delete(path);if(buildFile===path){buildFile=[...buildBuffers.keys()].pop()||'';displayBuildFile();}else renderBuildTabs();};tab.append(b,close);$('build-file-tabs').append(tab);}
 $('save-build-file').disabled=!buildFile||buildBuffers.get(buildFile)?.content===buildBuffers.get(buildFile)?.saved;
}
function displayBuildFile(){const buffer=buildBuffers.get(buildFile);$('build-editor').disabled=!buffer;$('build-editor').value=buffer?.content||'';$('build-file-label').textContent=buildFile||'No file selected';$('build-context-label').textContent=buildFile||'Project context';$('build-line-numbers').textContent=Array.from({length:Math.max(1,$('build-editor').value.split('\n').length)},(_,i)=>i+1).join('\n');renderBuildTabs();renderBuildFiles();editorPosition();syncCodeEditor();}
function renderBuildFiles(){
 const query=$('build-file-filter').value.toLowerCase();$('build-file-tree').replaceChildren();
 const root={dirs:new Map(),files:[]};
 for(const file of buildFiles.filter(f=>f.path.toLowerCase().includes(query))){let node=root;const parts=file.path.split('/');for(const segment of parts.slice(0,-1)){if(!node.dirs.has(segment))node.dirs.set(segment,{dirs:new Map(),files:[]});node=node.dirs.get(segment);}node.files.push(file);}
 function draw(node,parent,prefix=""){for(const [name,child] of node.dirs){const folder=document.createElement('details');folder.className='ide-folder';const key=prefix+name;folder.open=query?true:!buildClosedFolders.has(key);folder.ontoggle=()=>{if(folder.open)buildClosedFolders.delete(key);else buildClosedFolders.add(key);};const label=document.createElement('summary');label.textContent=name;folder.append(label);draw(child,folder,key+"/");parent.append(folder);}for(const file of node.files){const b=document.createElement('button');b.className='ide-file';b.textContent=file.path.split('/').pop();b.dataset.ext=file.path.split('.').pop();b.title=file.path;b.setAttribute('aria-current',String(file.path===buildFile));b.onclick=()=>buildAction(()=>openBuildFile(file.path));parent.append(b);}}
 draw(root,$('build-file-tree'));
 if(!$('build-file-tree').children.length){const p=document.createElement('p');p.className='ide-empty';p.textContent=buildProject?'No matching files. Create one below or ask OpenCode to build.':'Choose a project to explore its files.';$('build-file-tree').append(p);}
}
async function refreshBuildFiles(){if(!$('build-project').value)return;const epoch=buildEpoch,data=await buildRequest('files');if(epoch!==buildEpoch)return;if(JSON.stringify(buildFiles)!==JSON.stringify(data.files)){buildFiles=data.files;renderBuildFiles();}if(data.truncated)$('build-file-status').textContent='Showing first 1,200 files.';}
async function openBuildFile(path,reload=false){
 if(reload&&buildBuffers.get(path)?.content!==buildBuffers.get(path)?.saved&&!confirm('Discard the unsaved draft and reload this file from disk?'))return;
 const epoch=buildEpoch;
 if(!buildBuffers.has(path)||reload){const data=await buildRequest('read',{path});if(epoch!==buildEpoch)return;buildBuffers.set(path,{...data,saved:data.content});}
 buildFile=path;displayBuildFile();if(buildView!=='split')setIdeView('editor');else scheduleBuildPreview();$('build-file-status').textContent='Loaded from disk · UTF-8';
}
$('build-editor').oninput=()=>{const b=buildBuffers.get(buildFile);if(!b)return;b.content=$('build-editor').value;$('build-line-numbers').textContent=Array.from({length:b.content.split('\n').length},(_,i)=>i+1).join('\n');$('build-file-status').textContent=b.content===b.saved?'Saved · UTF-8':'Unsaved draft';renderBuildTabs();editorPosition();syncCodeEditor();scheduleBuildPreview();};
$('build-editor').onscroll=()=>{$('build-line-numbers').scrollTop=$('build-editor').scrollTop;};
$('build-editor').onkeyup=editorPosition;$('build-editor').onclick=editorPosition;
$('build-editor').onkeydown=e=>{if(e.key==='Tab'){e.preventDefault();const el=e.currentTarget;el.setRangeText('  ',el.selectionStart,el.selectionEnd,'end');el.dispatchEvent(new Event('input'));}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();buildAction(saveBuildFile);}};
async function saveBuildFile(){
 if($('build-format-save').checked&&buildParsers[buildFile.split('.').pop().toLowerCase()])await formatBuildFile();
 const path=buildFile,b=buildBuffers.get(path),epoch=buildEpoch;if(!b)return;const content=b.content;
 const data=await buildRequest('save',{path,content,revision:b.revision});if(epoch!==buildEpoch)return;
 b.saved=content;b.revision=data.revision;renderBuildTabs();$('build-file-status').textContent=b.content===content?'Saved · UTF-8':'Saved earlier revision · draft has newer edits';await refreshBuildFiles();
}
$('save-build-file').onclick=()=>buildAction(saveBuildFile);
$('reload-build-file').onclick=()=>buildAction(async()=>{if(buildFile)await openBuildFile(buildFile,true);});
$('refresh-build-files').onclick=()=>buildAction(refreshBuildFiles);$('build-file-filter').oninput=renderBuildFiles;
$('new-build-file').onclick=()=>buildAction(async()=>{const path=$('build-file-name').value.trim();await buildRequest('new_file',{path,content:''});$('build-file-name').value='';await refreshBuildFiles();await openBuildFile(path);});
function setIdeView(view){buildView=view;document.querySelector('.ide-workbench').classList.toggle('ide-split',view==='split');for(const name of ['editor','preview','changes'])$('ide-'+name+'-panel').hidden=!(name===view||(view==='split'&&name!=='changes'));document.querySelectorAll('[data-ide-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.ideView===view)));}
function scheduleBuildPreview(){clearTimeout(buildLiveTimer);if(buildView==='split'||buildView==='preview')buildLiveTimer=setTimeout(refreshBuildPreview,250);}
document.querySelectorAll('[data-ide-view]').forEach(b=>b.onclick=()=>{setIdeView(b.dataset.ideView);if(['preview','split'].includes(b.dataset.ideView))refreshBuildPreview();});
let buildPreviewRequest=0;
async function refreshBuildPreview(){
 const request=++buildPreviewRequest,epoch=buildEpoch,status=$('build-preview-status');
 $('refresh-build-preview').disabled=true;
 try{
  if(!buildProject)throw Error('Choose a project first.');

  status.textContent='Loading preview…';
  const data=await buildRequest('preview',{path:$('build-preview-entry').value.trim(),drafts:Object.fromEntries([...buildBuffers].filter(([path])=>/\.(html?|css|js)$/i.test(path)).map(([path,b])=>[path,b.content]))});
  if(epoch!==buildEpoch||request!==buildPreviewRequest)return;
  $('build-preview').src=data.url;
  status.textContent=(buildDirty()?'Live draft · ':'Live · ')+$('build-preview-entry').value.trim();
 }catch(error){if(epoch===buildEpoch&&request===buildPreviewRequest)status.textContent=error.message;}
 finally{if(request===buildPreviewRequest)$('refresh-build-preview').disabled=false;}
}
$('refresh-build-preview').onclick=refreshBuildPreview;
$('build-preview-entry').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();refreshBuildPreview();}};

async function refreshBuildProjects(){return buildAction(async()=>{const data=await buildRequest('projects'),previous=$('build-project').value;$('build-project').replaceChildren(new Option('Choose a project',''));for(const name of data.projects)$('build-project').add(new Option(name,name));$('build-project').value=previous;});}
let buildPollFailures=0;
function beginBuildPolling(){clearInterval(buildTimer);buildPollFailures=0;buildTimer=setInterval(()=>{if(buildPolling)return;return pollBuild().then(()=>{buildPollFailures=0;}).catch(error=>{buildPollFailures++;if(buildPollFailures<3){$('build-status').textContent='Connection interrupted · retrying…';return;}$('build-status').textContent=error.message;setBuildConnected(false);clearInterval(buildTimer);});},1800);}
async function loadBuildSessions(){const epoch=buildEpoch,sessions=await buildRequest('sessions');if(epoch!==buildEpoch)return;$('build-session').replaceChildren(new Option('Choose a session',''));for(const session of sessions)$('build-session').add(new Option(session.title,session.id));if(sessions.length)$('build-session').value=sessions[0].id;beginBuildPolling();await pollBuild();}
async function switchBuildProject(name){
 if(name!==buildProject&&buildDirty()&&!confirm('Discard unsaved drafts and switch projects?')){$('build-project').value=buildProject;return;}
 buildEpoch++;buildMessagesSnapshot='';buildPermissionsSnapshot='';clearInterval(buildTimer);buildProject=name;buildFiles=[];buildBuffers.clear();buildFile='';displayBuildFile();clearTimeout(buildLiveTimer);buildPreviewRequest++;$('build-preview').removeAttribute('src');$('build-preview-status').textContent='Choose Preview to load this project.';$('build-output').replaceChildren();$('build-permissions').replaceChildren();$('build-diff').textContent='No changes loaded.';$('build-session').replaceChildren(new Option('Choose a session',''));
 if(name){await refreshBuildFiles();if(!$('ide-preview-panel').hidden)await refreshBuildPreview();await loadBuildSessions();}
}
$('connect-build').onclick=()=>buildAction(async()=>{setBuildOrb('connecting');$('build-status').textContent='Starting OpenCode…';$('connect-build').textContent='Connecting…';let data;try{data=await buildRequest('connect');setBuildConnected(true);}catch(error){setBuildConnected(false);throw error;}$('build-status').textContent='OpenCode '+data.version+' connected · local model';await refreshBuildProjects();if(buildProject)await loadBuildSessions();});
$('create-build-project').onclick=()=>buildAction(async()=>{if(buildDirty())throw Error('Save your drafts before creating another project.');const name=$('build-project-name').value.trim();const session=await buildRequest('create',{project:name});await refreshBuildProjects();$('build-project').value=name;await switchBuildProject(name);$('build-session').value=session.id;$('build-project-name').value='';$('build-status').textContent='Project ready: '+name;});
$('build-project').onchange=()=>buildAction(()=>switchBuildProject($('build-project').value));
$('build-session').onchange=()=>buildAction(async()=>{buildEpoch++;beginBuildPolling();await pollBuild();});
$('new-build-session').onclick=()=>buildAction(async()=>{const session=await buildRequest('new_session');await loadBuildSessions();$('build-session').value=session.id;await pollBuild();});
$('send-build').onclick=()=>buildAction(async()=>{
 if(buildBusy||buildAgentBusy)throw Error('OpenCode is already working. Stop the current task before sending another request.');if(buildDirty())throw Error('Save your draft before asking OpenCode to edit the project.');
 buildBusy=true;setBuildOrb('thinking');$('send-build').disabled=true;
 try{await buildRequest('send',{prompt:$('build-prompt').value,file:buildFile});$('build-prompt').value='';$('build-status').textContent='OpenCode is working…';beginBuildPolling();await pollBuild();}
 finally{buildBusy=false;$('send-build').disabled=buildAgentBusy;}
});
$('stop-build').onclick=()=>buildAction(async()=>{await buildRequest('abort');await pollBuild();$('build-status').textContent='Task stopped.';setBuildOrb('stopped');});
async function pollBuild(){
 if(buildPolling||!$('build-session').value)return;buildPolling=true;
 const epoch=buildEpoch,session=$('build-session').value;
 try{
 const data=await buildRequest('poll');setBuildConnected(true);if(epoch!==buildEpoch||session!==$('build-session').value)return;
 const output=$('build-output'),atBottom=output.scrollHeight-output.scrollTop-output.clientHeight<80,scroll=output.scrollTop;
 const messagesSnapshot=JSON.stringify(data.messages);
 if(messagesSnapshot!==buildMessagesSnapshot){
 buildMessagesSnapshot=messagesSnapshot;
 const expanded=new Set([...output.querySelectorAll('details[open]')].map(el=>el.dataset.part));
 output.replaceChildren();
 for(const message of data.messages){
   const article=document.createElement('article');article.className='message';article.dataset.role=message.info.role;const title=document.createElement('div');title.className='eyebrow';title.textContent=message.info.role==='assistant'?'DreadOS AI':message.info.role==='user'?'You':message.info.role;article.append(title);
   if(message.info.error){const p=document.createElement('p');const raw=message.info.error.data?.message||message.info.error.name;p.textContent=/failed to decode|Engine protocol predict/i.test(raw)?'The local model failed while generating. Stop any active request. Retry once; if it repeats, reload the model in LM Studio. Your files and chat are preserved.':raw;article.append(p);}
   for(const part of message.parts){if(part.type==='text'){if(message.info.role==='assistant'&&window.renderBuildMarkdown)article.append(renderBuildMarkdown(part.text));else{const p=document.createElement('p');p.textContent=part.text;article.append(p);}}else if(part.type==='tool'){const details=document.createElement('details');details.className='ide-tool';details.dataset.part=part.id;details.open=expanded.has(part.id);const label=document.createElement('summary');label.textContent=part.tool+' · '+(part.state.status==='pending'?'generating arguments — not saved yet':part.state.status);const pre=document.createElement('pre');pre.textContent=part.state.output||part.state.error||JSON.stringify(part.state.input||{},null,2);details.append(label,pre);article.append(details);}}
   output.append(article);
 }
 if(!data.messages.length){const p=document.createElement('p');p.className='ide-empty';p.textContent='Ask OpenCode to create, explain, or improve your project.';output.append(p);}
 output.scrollTop=atBottom?output.scrollHeight:scroll;
 }
 const permissionsSnapshot=JSON.stringify(data.permissions);
 if(permissionsSnapshot!==buildPermissionsSnapshot){
 buildPermissionsSnapshot=permissionsSnapshot;
 $('build-permissions').replaceChildren();
 for(const pending of data.permissions){const box=document.createElement('div');box.className='search-result';const p=document.createElement('p');p.textContent='Permission: '+pending.permission+'\n'+pending.patterns.join('\n');box.append(p);
 for(const [label,reply] of [['Allow once','once'],['Reject','reject']]){const button=document.createElement('button');button.className='quiet';button.textContent=label;button.onclick=()=>buildAction(async()=>{if(epoch!==buildEpoch)return;await buildRequest('permission',{permission:pending.id,reply});await pollBuild();});box.append(button);}$('build-permissions').append(box);}
 }
 const diffText=data.diff.map(f=>f.file+'\n'+(f.diff||('Before:\n'+f.before+'\nAfter:\n'+f.after))).join('\n\n')||'No recorded file changes yet.';
 if($('build-diff').textContent!==diffText)$('build-diff').textContent=diffText;
 buildAgentBusy=data.status.type!=='idle';
 $('send-build').disabled=buildBusy||buildAgentBusy;
 const progressKey=JSON.stringify([data.messages,data.permissions,data.status]);
 if(progressKey!==buildProgressKey){buildProgressKey=progressKey;buildProgressAt=Date.now();}
 const generatingTool=data.messages.at(-1)?.parts?.some(p=>p.type==='tool'&&p.state?.status==='pending');
 const stalled=buildAgentBusy&&!data.permissions.length&&Date.now()-buildProgressAt>60000;
 setBuildOrb(stalled&&!generatingTool?'stalled':buildOrbState(data));
 const statusText=generatingTool?'Generating tool arguments · file is not saved yet · '+Math.floor((Date.now()-(data.messages.at(-1)?.info.time?.created||Date.now()))/1000)+'s elapsed. Partial progress is unavailable.':stalled?'No new progress for over a minute. Stop to cancel, then retry.':data.permissions.length?'OpenCode needs your approval.':'OpenCode · '+data.status.type;
 if($('build-status').textContent!==statusText)$('build-status').textContent=statusText;
 if(data.status.type==='idle'){
   await refreshBuildFiles();
   if(buildFile){const path=buildFile,b=buildBuffers.get(path);try{const disk=await buildRequest('read',{path});if(epoch!==buildEpoch||buildFile!==path)return;if(disk.revision!==b.revision){if(b.content===b.saved){buildBuffers.set(path,{...disk,saved:disk.content});displayBuildFile();$('build-file-status').textContent='Updated from disk';scheduleBuildPreview();}else $('build-file-status').textContent='File changed on disk · your draft is preserved. Reload to review.';}}catch(error){$('build-file-status').textContent=error.message;}}
 }
 }finally{buildPolling=false;}
}

$('ide-toggle-files').onclick=()=>{const hidden=$('build-view').classList.toggle('ide-hide-files');$('ide-toggle-files').setAttribute('aria-pressed',String(!hidden));};
$('ide-toggle-agent').onclick=()=>{const hidden=$('build-view').classList.toggle('ide-hide-agent');$('ide-toggle-agent').setAttribute('aria-pressed',String(!hidden));};
$('ide-find').onclick=()=>{$('build-view').classList.remove('ide-hide-files');$('ide-toggle-files').setAttribute('aria-pressed','true');$('build-file-filter').focus();};

const splitDivider=$('ide-split-divider'),splitWorkbench=document.querySelector('.ide-workbench');
function resizeBuildSplit(value){value=Math.max(20,Math.min(80,value));splitWorkbench.style.setProperty('--code-share',value+'%');splitDivider.setAttribute('aria-valuenow',String(Math.round(value)));}
splitDivider.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();splitDivider.setPointerCapture(e.pointerId);splitWorkbench.classList.add('ide-resizing');};
splitDivider.onpointermove=e=>{if(!splitDivider.hasPointerCapture(e.pointerId))return;const rect=splitWorkbench.getBoundingClientRect();resizeBuildSplit((e.clientX-rect.left)/rect.width*100);};
function endBuildResize(){splitWorkbench.classList.remove('ide-resizing');}
splitDivider.onpointerup=endBuildResize;splitDivider.onpointercancel=endBuildResize;splitDivider.onlostpointercapture=endBuildResize;
splitDivider.ondblclick=()=>resizeBuildSplit(50);
splitDivider.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home'].includes(e.key)){e.preventDefault();resizeBuildSplit(e.key==='Home'?50:Number(splitDivider.getAttribute('aria-valuenow'))+(e.key==='ArrowLeft'?-5:5));}};
let codeEditor=null;
let editorWrap=localStorage.getItem('dread-code-wrap');editorWrap=editorWrap===null?matchMedia('(max-width:900px)').matches:editorWrap==='true';
function applyEditorWrap(){ $('build-editor').wrap=editorWrap?'soft':'off';$('build-editor').classList.toggle('code-wrap',editorWrap);$('build-wrap').setAttribute('aria-pressed',String(editorWrap));$('build-line-numbers').hidden=editorWrap||!!codeEditor;codeEditor?.setWrap(editorWrap); }
$('build-wrap').onclick=()=>{editorWrap=!editorWrap;localStorage.setItem('dread-code-wrap',String(editorWrap));applyEditorWrap();};
applyEditorWrap();
$('build-format-save').checked=localStorage.getItem('dread-format-save')==='true';
$('build-format-save').onchange=()=>localStorage.setItem('dread-format-save',String($('build-format-save').checked));
const buildParsers={html:'html',htm:'html',css:'css',scss:'scss',less:'less',js:'babel',jsx:'babel',mjs:'babel',cjs:'babel',ts:'typescript',tsx:'typescript',json:'json',md:'markdown'};
async function formatBuildFile(){
 const path=buildFile,b=buildBuffers.get(path),epoch=buildEpoch;if(!b)return;
 const parser=buildParsers[path.split('.').pop().toLowerCase()];if(!parser)throw Error('Formatting supports HTML, CSS, JavaScript, TypeScript, JSON, and Markdown.');
 if(!window.prettier)throw Error('Formatter is unavailable. Reload the page.');
 const before=b.content,formatted=await prettier.format(before,{parser,plugins:Object.values(prettierPlugins),tabWidth:2,printWidth:80});
 if(epoch!==buildEpoch||buildFile!==path||b.content!==before)throw Error('Draft changed during formatting. Try Format again.');
 $('build-editor').value=formatted;$('build-editor').dispatchEvent(new Event('input'));$('build-file-status').textContent='Formatted · save to write changes';
}
$('build-format').onclick=()=>buildAction(formatBuildFile);
$('build-editor').addEventListener('keydown',e=>{if(e.altKey&&e.key.toLowerCase()==='z'){e.preventDefault();$('build-wrap').click();}if(e.altKey&&e.shiftKey&&e.key.toLowerCase()==='f'){e.preventDefault();buildAction(formatBuildFile);}});

// Keep the existing buffer/save/preview pipeline as the single source of truth.
function syncCodeEditor(){
 if(!codeEditor)return;
 const b=buildBuffers.get(buildFile);
 const language=codeEditor.setDocument(b?buildProject+'/'+buildFile:'',buildFile,b?.content||'',!!b);
 $('build-language').textContent=language;
}
if(window.createDreadEditor){
 const host=document.createElement('div');host.id='build-code-editor';
 $('build-editor').parentElement.append(host);
 const language=document.createElement('span');language.id='build-language';language.textContent='Plain text';
 $('build-cursor').before(language);
 codeEditor=createDreadEditor({parent:host,
  onChange:content=>{$('build-editor').value=content;$('build-editor').dispatchEvent(new Event('input'));},
  onCursor:(line,col)=>{$('build-cursor').textContent=`Ln ${line}, Col ${col}`;},
  onSave:()=>buildAction(saveBuildFile),onFormat:()=>buildAction(formatBuildFile),onWrap:()=>$('build-wrap').click()
 });
 $('build-editor').hidden=true;$('build-line-numbers').hidden=true;
 applyEditorWrap();syncCodeEditor();
}
