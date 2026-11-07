// Upgrade early chat text once the optional rich-text/editor bundle is ready.
if (window.renderBuildMarkdown) document.querySelectorAll('[data-pending-markdown]').forEach(node => node.replaceWith(renderBuildMarkdown(node.dataset.pendingMarkdown)));
let buildPreviewCapturing=false;
let buildAgentBusy=false,buildProgressKey='',buildProgressAt=Date.now();
let buildTask={start:0,end:0},buildTaskTicker=null;
function formatBuildDuration(ms){if(!Number.isFinite(ms))return 'unknown';const s=Math.max(0,Math.floor(ms/1000)),h=Math.floor(s/3600),m=Math.floor(s/60)%60;return (h?h+'h ':'')+(h||m?m+'m ':'')+s%60+'s';}
function renderBuildTaskTimer(){
 const el=$('build-task-timer');if(!buildTask.start){el.hidden=true;el.textContent='';return;}el.hidden=false;
 if(buildTask.incomplete){el.textContent=buildTask.end>buildTask.start?'Task ended · at least '+formatBuildDuration(buildTask.end-buildTask.start):'Task ended · duration unavailable';return;}
 const label=buildTask.end?'Task took ':buildTask.disconnected?'Task elapsed · connection lost · ':buildTask.waiting?'Task elapsed · awaiting approval · ':'Task elapsed · ';
 el.textContent=label+formatBuildDuration((buildTask.end||Date.now())-buildTask.start);
}
// The current task spans the latest user message until the session goes idle.
function updateBuildTaskTimer(data){
 const messages=data.messages||[],lastUser=messages.findLastIndex(m=>m.info?.role==='user'&&!m.info?.summary&&!(m.parts?.length&&m.parts.every(p=>p.synthetic||p.type==='compaction')));
 const stamp=value=>Number.isFinite(value)&&value>0?value:0;
 const start=lastUser<0?0:stamp(messages[lastUser].info.time?.created);
 const replies=messages.slice(lastUser+1).filter(m=>m.info?.role==='assistant'),last=replies.at(-1);
 const finished=data.status?.type==='idle',completed=stamp(last?.info?.time?.completed);
 const evidence=[start,...replies.flatMap(m=>[stamp(m.info?.time?.created),stamp(m.info?.time?.completed),...(m.parts||[]).flatMap(p=>[stamp(p.time?.end),stamp(p.state?.time?.end)])])];
 const end=start&&finished?Math.max(...evidence):0;
 buildTask={start,end,incomplete:finished&&!completed,waiting:!!(data.permissions?.length||data.permission_error)};renderBuildTaskTimer();
 clearInterval(buildTaskTicker);buildTaskTicker=start&&!end?setInterval(renderBuildTaskTimer,1000):null;
}
function resetBuildTaskTimer(){clearInterval(buildTaskTicker);buildTaskTicker=null;buildTask={start:0,end:0};renderBuildTaskTimer();}
function renderBuildReasoning(part,expanded,existing){
 const details=document.createElement('details');details.className='ide-tool build-thinking';details.dataset.part=part.id;
 details.open=existing.has(part.id)?expanded.has(part.id):!part.time?.end;
 const label=document.createElement('summary'),duration=part.time?.end-part.time?.start;
 label.textContent=part.time?.end?(Number.isFinite(duration)?'Thought for '+formatBuildDuration(duration):'Model reasoning'):'Thinking…';
 const pre=document.createElement('pre');pre.textContent=part.text.trim();details.append(label,pre);return details;
}
function isOfflineDocsTool(part){return part?.type==='tool'&&/^offline_docs[_.:]search_docs$/.test(part.tool||'');}
function buildToolLabel(part){
 if(part.tool==='preview_check_preview')return ({pending:'Preparing preview check',running:'Checking preview',completed:'Preview captured · desktop + mobile',error:'Preview capture failed'}[part.state?.status]||'Preview check');
 if(part.tool==='site_tools_audit_site')return ({pending:'Preparing site audit',running:'Auditing site',completed:'Site audit complete',error:'Site audit failed'}[part.state?.status]||'Site audit');
 if(isOfflineDocsTool(part)){
  const status=part.state?.status;
  const label=status==='completed'?'Checked offline docs':status==='error'?'Offline docs search failed':status==='pending'?'Preparing offline docs search':'Checking offline docs';
  const query=part.state?.input?.query;
  return label+(typeof query==='string'&&query.trim()?' · '+query.trim().slice(0,160):'');
 }
 return part.tool+' · '+(part.tool==='invalid'?'failed — no changes saved':part.state.status==='pending'?'generating arguments — not saved yet':part.state.status);
}
function buildOrbState(data){
 if(data.permission_error||data.permissions?.length)return 'approval';
 const messages=data.messages||[],lastUser=messages.findLastIndex(m=>m.info.role==='user');
 const latest=messages.slice(lastUser+1).findLast(m=>m.info.role==='assistant');
 if(data.status?.type==='retry')return 'retry';
 if(latest?.parts?.some(p=>p.type==='tool'&&p.tool==='invalid'))return 'error';
 if(latest?.info.error)return latest.info.error.name==='MessageAbortedError'?'stopped':'error';
 if(data.status?.type==='idle')return 'idle';
 const active=(latest?.parts||[]).findLast(p=>p.type==='tool'&&['running','pending'].includes(p.state?.status));
 if(active){if(active.tool==='preview_check_preview')return 'preview-check';if(isOfflineDocsTool(active))return 'offline-docs';const tool=active.tool.toLowerCase();if(/edit|write|patch/.test(tool))return 'coding';if(/bash|shell|command/.test(tool))return 'running';if(/web|search/.test(tool))return 'searching';if(/read|glob|grep|list/.test(tool))return 'reading';return 'working';}
 if(latest?.parts?.some(p=>p.type==='text'&&p.text))return 'responding';
 return 'thinking';
}
function setBuildOrb(state){
 const states={'preview-check':['Checking preview','Capturing desktop and mobile views'],offline:['Offline','Connect to start building'],connecting:['Connecting','Starting the coding engine'],idle:['Ready','Your next idea starts here'],thinking:['Thinking','Working on your request'],'offline-docs':['Checking offline docs','Searching the local reference library'],reading:['Reading files','Exploring project context'],coding:['Coding','Editing project files'],running:['Running commands','Executing a project task'],searching:['Searching','Looking for information'],approval:['Approval needed','Review the requested action below'],responding:['Responding','Writing a reply'],working:['Using tools','Working on your project'],retry:['Retrying','Waiting to try again'],error:['Needs attention','Check the error in chat'],stopped:['Stopped','Task cancelled'],stalled:['No recent progress','Use Stop, then retry or start a new session']};
 const [label,detail]=states[state]||states.working;
 if($('build-presence').dataset.state===state)return;
 $('build-presence').dataset.state=state;$('build-orb-label').textContent=label;$('build-orb-detail').textContent=detail;
}
let buildView='editor',buildLiveTimer=null;
const buildClosedFolders=new Set();
let buildMessagesSnapshot='',buildPermissionsSnapshot='';
let buildTimer=null,buildPolling=false,buildProject='',buildFiles=[],buildFile='',buildBuffers=new Map(),buildEpoch=0,buildBusy=false;
async function buildRequest(action,extra={}){return api('/api/build',{action,project:$('build-project').value,session:$('build-session').value,auto_edits:$('build-auto-edits').checked,auto_checks:$('build-auto-checks').checked,auto_bash:buildTerminalEnabled(),...extra},30000);}
function setBuildConnected(connected){buildTask.disconnected=!connected;renderBuildTaskTimer();if(!connected)setBuildOrb('offline');else if(['offline','connecting'].includes($('build-presence').dataset.state))setBuildOrb('idle');$('connect-build').textContent=connected?'● Connected':'Reconnect OpenCode';$('connect-build').classList.toggle('is-connected',connected);}
async function buildAction(fn){try{await fn();}catch(error){$('build-status').textContent=error.message;if($('build-presence').dataset.state!=='offline')setBuildOrb('error');}}
function buildDirty(){return [...buildBuffers.values()].some(b=>b.content!==b.saved);}
window.addEventListener('beforeunload',e=>{if(buildDirty()){e.preventDefault();e.returnValue='';}});
function editorPosition(){const e=$('build-editor'),before=e.value.slice(0,e.selectionStart);$('build-cursor').textContent=`Ln ${before.split('\n').length}, Col ${before.length-before.lastIndexOf('\n')}`;}
function renderBuildTabs(){
 $('build-file-tabs').replaceChildren();
 for(const [path,buffer] of buildBuffers){const tab=document.createElement('div');tab.className='ide-tab-group';const b=document.createElement('button');b.className='ide-file-tab';b.textContent=path.split('/').pop()+(buffer.content!==buffer.saved?' •':'');b.setAttribute('aria-current',String(path===buildFile));b.onclick=()=>buildAction(()=>openBuildFile(path));const close=document.createElement('button');close.className='ide-tab-close';close.textContent='×';close.setAttribute('aria-label','Close '+path);close.onclick=()=>{if(buffer.content!==buffer.saved&&!confirm('Discard unsaved changes to '+path+'?'))return;buildBuffers.delete(path);if(buildFile===path){buildFile=[...buildBuffers.keys()].pop()||'';displayBuildFile();}else renderBuildTabs();};tab.append(b,close);$('build-file-tabs').append(tab);}
 $('save-build-file').disabled=!buildFile||!!buildBuffers.get(buildFile)?.readonly||buildBuffers.get(buildFile)?.content===buildBuffers.get(buildFile)?.saved;
}
function displayBuildFile(){const buffer=buildBuffers.get(buildFile);$('build-editor').disabled=!buffer;$('build-editor').readOnly=!!buffer?.readonly;$('build-format').disabled=!buffer||!!buffer.readonly;$('build-editor').value=buffer?.content||'';$('build-file-label').textContent=buildFile||'No file selected';$('build-context-label').textContent=buildFile||'Project context';$('build-line-numbers').textContent=Array.from({length:Math.max(1,$('build-editor').value.split('\n').length)},(_,i)=>i+1).join('\n');renderBuildTabs();renderBuildFiles();editorPosition();syncCodeEditor();}
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
 buildFile=path;displayBuildFile();if(buildView!=='split')setIdeView('editor');else scheduleBuildPreview();$('build-file-status').textContent=buildBuffers.get(path)?.readonly?'Large file · read-only · '+(buildBuffers.get(path).size/1000000).toFixed(2)+' MB':'Loaded from disk · UTF-8';
}
$('build-editor').oninput=()=>{const b=buildBuffers.get(buildFile);if(!b)return;b.content=$('build-editor').value;$('build-line-numbers').textContent=Array.from({length:b.content.split('\n').length},(_,i)=>i+1).join('\n');$('build-file-status').textContent=b.content===b.saved?'Saved · UTF-8':'Unsaved draft';renderBuildTabs();editorPosition();syncCodeEditor();scheduleBuildPreview();};
$('build-editor').onscroll=()=>{$('build-line-numbers').scrollTop=$('build-editor').scrollTop;};
$('build-editor').onkeyup=editorPosition;$('build-editor').onclick=editorPosition;
$('build-editor').onkeydown=e=>{if(e.key==='Tab'){e.preventDefault();const el=e.currentTarget;el.setRangeText('  ',el.selectionStart,el.selectionEnd,'end');el.dispatchEvent(new Event('input'));}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();buildAction(saveBuildFile);}};
async function saveBuildFile(){
 if(buildBuffers.get(buildFile)?.readonly)throw Error('Large files open read-only. Files up to 500 KB can be edited.');
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
document.querySelectorAll('[data-ide-view]').forEach(b=>b.onclick=()=>{setIdeView(b.dataset.ideView);if(['preview','split'].includes(b.dataset.ideView)){refreshBuildPreview();refreshBuildDev();}});

// ---- Managed dev server (npm run dev) shown live in Preview ----
let buildDev=null,buildDevTimer=null,buildDevLogOpen=false;
const devActive=d=>d&&d.project===$('build-project').value&&['installing','starting','running'].includes(d.status);
const devLive=d=>devActive(d)&&d.status==='running'&&d.url;
const devFrameUrl=u=>String(u||'').replace('://[::1]:','://localhost:');
function renderBuildDev(info){
 buildDev=info;const bar=$('build-dev-bar'),status=$('build-dev-status'),toggle=$('build-dev-toggle'),frame=$('build-dev-preview'),log=$('build-dev-log');
 const here=info&&info.project===$('build-project').value,can=!!(info&&info.script_available);
 bar.hidden=!info||(!can&&!here);
 const live=devLive(info),active=devActive(info);
 frame.hidden=!live;$('build-preview').hidden=!!live;
 if(live&&frame.dataset.url!==info.url){frame.dataset.url=info.url;frame.src=devFrameUrl(info.url);}
 if(!live&&frame.dataset.url){delete frame.dataset.url;frame.removeAttribute('src');}
 $('build-dev-open').hidden=!live;if(live)$('build-dev-open').href=devFrameUrl(info.url);
 toggle.textContent=active?'■ Stop dev server':'▶ Run dev server';toggle.disabled=!active&&!can;
 toggle.title=can?'Runs npm run '+info.script_available+' in this project':info?.why_not||'';
 const other=info&&info.project&&!here&&['installing','starting','running'].includes(info.status);
 status.dataset.state=here?info.status:'';
 status.textContent=!info?'':live?'● Live · npm run '+info.script+' · '+devFrameUrl(info.url)+' · save files to hot-reload':
  here&&info.status==='installing'?'Installing packages (npm install)… first run can take a minute':
  here&&info.status==='starting'?'Starting npm run '+info.script+'…':
  here&&info.status==='crashed'?info.error:
  other?'A dev server is running for '+info.project+'. Running one here stops it.':
  can?'Framework app? Run its dev server to preview it live.':'';
 const showLog=here&&(info.status!=='stopped');$('build-dev-log-toggle').hidden=!showLog;
 log.hidden=!(showLog&&(buildDevLogOpen||info.status==='crashed'||info.status==='installing'));log.textContent=here?info.log||'':'';log.scrollTop=log.scrollHeight;
 $('build-dev-log-toggle').textContent=log.hidden?'Show log':'Hide log';
 clearTimeout(buildDevTimer);
 if(here&&['installing','starting','running'].includes(info.status)&&!$('ide-preview-panel').hidden)buildDevTimer=setTimeout(refreshBuildDev,info.status==='running'?5000:1500);
}
async function refreshBuildDev(){
 if(!$('build-project').value){renderBuildDev(null);return;}
 const project=$('build-project').value;
 try{const info=await buildRequest('dev_status');if(project===$('build-project').value)renderBuildDev(info);}catch{renderBuildDev(null);}
}
$('build-dev-toggle').onclick=()=>buildAction(async()=>{
 if(!requireBuildProject())return;
 if(devActive(buildDev)){renderBuildDev(await buildRequest('dev_stop'));return;}
 const key='dreados-dev-ok:'+$('build-project').value;let ok=false;try{ok=localStorage.getItem(key)==='1';}catch{}
 if(!ok){
  if(!confirm('Run this project\'s dev server?\n\nDreadOS will run "npm run '+(buildDev?.script_available||'dev')+'" (and "npm install" first if needed) inside this project. Project scripts run with your normal Windows permissions, like any terminal command.\n\nOnly run projects you trust.'))return;
  try{localStorage.setItem(key,'1');}catch{}
 }
 buildDevLogOpen=false;renderBuildDev(await buildRequest('dev_start'));
});
$('build-dev-log-toggle').onclick=()=>{buildDevLogOpen=$('build-dev-log').hidden;renderBuildDev(buildDev);};
let buildPreviewRequest=0;
async function refreshBuildPreview(){
 const request=++buildPreviewRequest,epoch=buildEpoch,status=$('build-preview-status');
 $('refresh-build-preview').disabled=true;
 try{
  if(!buildProject)throw Error('Choose a project first.');

  status.textContent='Loading preview…';
  const data=await buildRequest('preview',{path:$('build-preview-entry').value.trim(),drafts:Object.fromEntries([...buildBuffers].filter(([path,b])=>!b.readonly&&b.content!==b.saved&&/\.(html?|css|js)$/i.test(path)).map(([path,b])=>[path,b.content]))});
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
function beginBuildPolling(){clearInterval(buildTimer);buildPollFailures=0;buildTimer=setInterval(()=>{if(buildPolling)return;const epoch=buildEpoch;return pollBuild().then(()=>{if(epoch===buildEpoch)buildPollFailures=0;}).catch(error=>{if(epoch!==buildEpoch)return;buildPollFailures++;if(buildPollFailures<3){$('build-status').textContent='Connection interrupted · retrying…';return;}$('build-status').textContent=error.message;setBuildConnected(false);clearInterval(buildTimer);});},1800);}
async function loadBuildSessions(){const epoch=buildEpoch,previous=$('build-session').value,sessions=await buildRequest('sessions');if(epoch!==buildEpoch)return;$('build-session').replaceChildren(new Option('Choose a session',''));for(const session of sessions)$('build-session').add(new Option(session.title,session.id));if(sessions.length)$('build-session').value=sessions.some(s=>s.id===previous)?previous:sessions[0].id;beginBuildPolling();await pollBuild();}
async function switchBuildProject(name){
 if(name!==buildProject&&buildDirty()&&!confirm('Discard unsaved drafts and switch projects?')){$('build-project').value=buildProject;return;}
 resetBuildTerminalApproval();
 if(window.showContextMeter)showContextMeter('build-context-meter',null);
 buildEpoch++;buildPolling=false;buildMessagesSnapshot='';buildPermissionsSnapshot='';clearInterval(buildTimer);resetBuildTaskTimer();buildProject=name;buildImages=[];renderBuildImages();buildFiles=[];buildBuffers.clear();buildFile='';displayBuildFile();clearTimeout(buildLiveTimer);buildPreviewRequest++;$('build-preview').removeAttribute('src');$('build-preview-status').textContent='Choose Preview to load this project.';$('build-output').replaceChildren();$('build-permissions').replaceChildren();$('build-recovery').hidden=true;$('build-diff').textContent='No changes loaded.';$('build-session').replaceChildren(new Option('Choose a session',''));
 renderBuildDev(null);
 if(name){await refreshBuildFiles();if(!$('ide-preview-panel').hidden)await refreshBuildPreview();await loadBuildSessions();refreshBuildDev();}
}
let buildConnecting=false;
$('connect-build').onclick=()=>buildAction(async()=>{
 if(buildConnecting)return;
 buildConnecting=true;clearInterval(buildTimer);buildEpoch++;buildPolling=false;
 const epoch=buildEpoch,button=$('connect-build');button.disabled=true;
 setBuildOrb('connecting');$('build-status').textContent='Reconnecting OpenCode…';button.textContent='Connecting…';
 try{
  // A DreadOS restart rotates the token. Refresh it without reloading or losing drafts.
  const response=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(12000)});
  if(!response.ok)throw Error('DreadOS connection rejected ('+response.status+').');
  const status=await response.json();if(!status.token)throw Error('DreadOS did not return a connection token.');
  token=status.token;
  const data=await buildRequest('connect');if(epoch!==buildEpoch)return;
  setBuildConnected(true);buildAgentBusy=false;buildPollFailures=0;buildProgressKey='';buildProgressAt=Date.now();
  $('build-status').textContent='OpenCode '+data.version+' connected';
  await refreshBuildProjects();if(buildProject)await loadBuildSessions();
 }catch(error){if(epoch===buildEpoch){setBuildConnected(false);$('send-build').disabled=true;}throw error;}
 finally{buildConnecting=false;button.disabled=false;}
});
$('create-build-project').onclick=()=>buildAction(async()=>{if(buildDirty())throw Error('Save your drafts before creating another project.');const name=$('build-project-name').value.trim().toLowerCase().replace(/\s+/g,'-');if(!/^[a-z0-9][a-z0-9-]{0,49}$/.test(name)){$('build-status').textContent='Enter a project name, for example my-website, then click + Project.';$('build-project-name').focus();return;}const session=await buildRequest('create',{project:name});await refreshBuildProjects();$('build-project').value=name;await switchBuildProject(name);$('build-session').value=session.id;$('build-project-name').value='';$('build-status').textContent='Project ready: '+name;});
$('build-project').onchange=()=>buildAction(()=>switchBuildProject($('build-project').value));
$('build-session').onchange=()=>buildAction(async()=>{resetBuildTerminalApproval();resetBuildTaskTimer();buildEpoch++;buildPolling=false;beginBuildPolling();await pollBuild();});
$('new-build-session').onclick=()=>buildAction(async()=>{if(!requireBuildProject())return;resetBuildTerminalApproval();const epoch=buildEpoch,project=$('build-project').value;const session=await buildRequest('new_session');if(epoch!==buildEpoch||project!==$('build-project').value)return;resetBuildTaskTimer();await loadBuildSessions();if(epoch!==buildEpoch||project!==$('build-project').value)return;$('build-session').value=session.id;resetBuildTaskTimer();await pollBuild();});
function requireBuildProject(){
 if($('build-project').value)return true;
 $('build-status').textContent='Choose a project at the top left, or enter a name and click + Project. Your message is still here.';
 $('build-project').focus();setBuildOrb('idle');
 resetBuildTerminalApproval();
 if(window.showContextMeter)showContextMeter('build-context-meter',null);
 return false;
}
$('send-build').onclick=()=>buildAction(async()=>{
 if(!requireBuildProject())return;
 if(!$('build-prompt').value.trim()){$('build-prompt').focus();$('build-status').textContent='Describe what you want to build first.';return;}
 if(buildBusy||buildAgentBusy)throw Error('OpenCode is already working. Stop the current task before sending another request.');if(buildDirty())throw Error('Save your draft before asking OpenCode to edit the project.');
 buildBusy=true;setBuildOrb('thinking');$('send-build').disabled=true;
 try{
 if(!$('build-session').value){
   const project=$('build-project').value,epoch=buildEpoch;
   const session=await buildRequest('new_session');
   if(project!==$('build-project').value||epoch!==buildEpoch)throw Error('Project changed. Your message has not been sent.');
   $('build-session').add(new Option(session.title,session.id));$('build-session').value=session.id;
   buildEpoch++;buildMessagesSnapshot='';$('build-output').replaceChildren();
   resetBuildTerminalApproval();
 if(window.showContextMeter)showContextMeter('build-context-meter',null);
 }
 await buildRequest('send',{prompt:$('build-prompt').value,file:buildFile,attachments:buildImages});buildImages=[];renderBuildImages();$('build-prompt').value='';$('build-status').textContent='OpenCode is working…';beginBuildPolling();await pollBuild();}
 finally{buildBusy=false;$('send-build').disabled=buildAgentBusy;}
});
$('stop-build').onclick=()=>buildAction(async()=>{if(!requireBuildProject()||!$('build-session').value)return;await buildRequest('abort');await pollBuild();$('build-status').textContent='Task stopped.';setBuildOrb('stopped');});
function renderBuildPermissions(permissions,epoch,project,session){
 const snapshot=JSON.stringify([epoch,project,session,permissions]);
 if(snapshot===buildPermissionsSnapshot)return;
 buildPermissionsSnapshot=snapshot;$('build-permissions').replaceChildren();
 const current=()=>epoch===buildEpoch&&project===$('build-project').value&&session===$('build-session').value;
 const replies=renderBuildPermissions.pendingReplies??=new Map(),keyFor=pending=>JSON.stringify([project,session,pending.id]),keys=new Set(permissions.map(keyFor));
 for(const [key,state] of replies)if(!keys.has(key)&&!state.submitting)replies.delete(key);
 for(const pending of permissions){
  const box=document.createElement('div'),description=document.createElement('p'),error=document.createElement('p'),buttons=[];
  box.className='search-result';description.textContent='Permission: '+pending.permission+'\n'+(pending.patterns||[]).join('\n');error.setAttribute('role','alert');box.append(description);
  const key=keyFor(pending),state=replies.get(key)||{submitting:false,accepted:false,failure:''};replies.set(key,state);state.buttons=buttons;state.error=error;error.textContent=state.failure;
  for(const [label,reply] of [['Allow once','once'],['Allow '+pending.permission+' this session','session'],['Reject','reject']]){
   const button=document.createElement('button');button.className='quiet';button.textContent=label;button.disabled=state.submitting||state.accepted;
   if(reply==='session')button.title='Allow future '+pending.permission+' requests in this coding session until DreadOS restarts.';
   button.onclick=()=>buildAction(async()=>{
    if(state.submitting||state.accepted||!current())return;
    state.submitting=true;state.failure='';state.error.textContent='';state.buttons.forEach(item=>item.disabled=true);
    try{
     await buildRequest('permission',{project,session,permission:pending.id,reply});state.accepted=true;
     if(!current())return;
     buildPermissionsSnapshot='';await pollBuild();
    }catch(cause){if(current()){state.failure=cause.message;state.error.textContent=state.failure;throw cause;}}
    finally{state.submitting=false;if(!state.accepted)state.buttons.forEach(item=>item.disabled=false);}
   });
   buttons.push(button);box.append(button);
  }
  box.append(error);$('build-permissions').append(box);
 }
}
async function pollBuild(){
 if(buildPolling||!$('build-session').value)return;buildPolling=true;
 const epoch=buildEpoch,project=$('build-project').value,session=$('build-session').value;
 try{
 const data=await buildRequest('poll');if(epoch!==buildEpoch||project!==$('build-project').value||session!==$('build-session').value)return;setBuildConnected(true);
 if(data.context && window.showContextMeter)showContextMeter('build-context-meter',data.context);
 const output=$('build-output'),atBottom=output.scrollHeight-output.scrollTop-output.clientHeight<80,scroll=output.scrollTop;
 const messagesSnapshot=JSON.stringify(data.messages);
 if(messagesSnapshot!==buildMessagesSnapshot){
 buildMessagesSnapshot=messagesSnapshot;
 const expanded=new Set([...output.querySelectorAll('details[open]')].map(el=>el.dataset.part));
 const existing=new Set([...output.querySelectorAll('details[data-part]')].map(el=>el.dataset.part));
 output.replaceChildren();
 for(const message of data.messages){
   const article=document.createElement('article');article.className='message';article.dataset.role=message.info.role;const title=document.createElement('div');title.className='eyebrow';title.textContent=message.info.role==='assistant'?'DreadOS AI':message.info.role==='user'?'You':message.info.role;article.append(title);
   if(message.info.finish==='length'){const notice=document.createElement('p');notice.className='build-continuity';notice.textContent='Response hit the output limit. An incomplete tool call cannot save files; continue with smaller edits.';article.append(notice);}
   if(message.info.error){const p=document.createElement('p');const raw=message.info.error.data?.message||message.info.error.name;p.textContent=isBuildContextOverflow(message.info.error)?'The coding request exceeded the model context window. Use Start fresh session below to prepare a short handoff. Review it before sending; your original chat and project files are preserved.':/failed to decode|Engine protocol predict/i.test(raw)?'The local model failed while generating. Stop any active request. Retry once; if it repeats, reload the model in LM Studio. Your files and chat are preserved.':raw;article.append(p);}
   for(const part of message.parts){if(part.type==='file'&&/^image\/(png|jpeg|webp)$/.test(part.mime)&&/^data:image\/(png|jpeg|webp);base64,/.test(part.url||'')){const img=document.createElement('img');img.className='build-chat-image';img.src=part.url;img.alt=part.filename||'Attached screenshot';img.loading='lazy';article.append(img);}else if(part.type==='compaction'){const p=document.createElement('p');p.className='build-continuity';p.textContent='Context handoff · summarizing earlier work for continuation';article.append(p);}else if(part.type==='reasoning'&&part.text?.trim()){article.append(renderBuildReasoning(part,expanded,existing));}else if(part.type==='text'){if(message.info.role==='assistant'&&window.renderBuildMarkdown)article.append(renderBuildMarkdown(part.text));else{const p=document.createElement('p');p.textContent=part.text;article.append(p);}}else if(part.type==='tool'){const details=document.createElement('details');details.className='ide-tool';details.dataset.part=part.id;details.open=expanded.has(part.id);const label=document.createElement('summary');label.textContent=buildToolLabel(part);if(isOfflineDocsTool(part))details.classList.add('ide-tool-offline-docs');const pre=document.createElement('pre');pre.textContent=part.state.output||part.state.error||JSON.stringify(part.state.input||{},null,2);details.append(label,pre);article.append(details);}}
   output.append(article);
 }
 if(!data.messages.length){const p=document.createElement('p');p.className='ide-empty';p.textContent='Ask OpenCode to create, explain, or improve your project.';output.append(p);}
 output.scrollTop=atBottom?output.scrollHeight:scroll;
 }
 renderBuildPermissions(data.permissions,epoch,project,session);
 const diffText=data.diff===null?$('build-diff').textContent:data.diff.map(f=>f.file+'\n'+(f.diff||('Before:\n'+f.before+'\nAfter:\n'+f.after))).join('\n\n')||'No recorded file changes yet.';
 if($('build-diff').textContent!==diffText)$('build-diff').textContent=diffText;
 renderBuildRecovery(data);
 buildAgentBusy=data.status.type!=='idle';
 $('send-build').disabled=buildBusy||buildAgentBusy;
 const progressKey=JSON.stringify([data.messages,data.permissions,data.status]);
 if(progressKey!==buildProgressKey){buildProgressKey=progressKey;buildProgressAt=Date.now();}
 const checkingOfflineDocs=buildOrbState(data)==='offline-docs';
 const generatingTool=data.messages.at(-1)?.parts?.some(p=>p.type==='tool'&&p.state?.status==='pending');
 const stalled=buildAgentBusy&&!data.permissions.length&&Date.now()-buildProgressAt>60000;
 const compacting=buildAgentBusy&&data.messages.at(-1)?.info?.agent==='compaction';
 setBuildOrb(buildPreviewCapturing?'preview-check':compacting?'thinking':stalled&&!generatingTool?'stalled':buildOrbState(data));
 updateBuildTaskTimer(data);
 if(compacting){$('build-orb-label').textContent='Compacting context';$('build-orb-detail').textContent='Preserving decisions and next steps';}
 const statusText=data.permission_error?data.permission_error:compacting?'Compacting context · preparing a seamless continuation…':checkingOfflineDocs?'Checking offline docs · searching local references':generatingTool?'Generating tool arguments · file is not saved yet · '+Math.floor((Date.now()-(data.messages.at(-1)?.info.time?.created||Date.now()))/1000)+'s elapsed. Partial progress is unavailable.':stalled?'No new progress for over a minute. Stop to cancel, then retry.':data.permissions.length?'OpenCode needs your approval.':'OpenCode · '+data.status.type;
 if($('build-status').textContent!==statusText)$('build-status').textContent=statusText;
 if(data.status.type==='idle'){
   await refreshBuildFiles();
   if(buildFile&&!buildBuffers.get(buildFile)?.readonly){const path=buildFile,b=buildBuffers.get(path);try{const disk=await buildRequest('read',{path});if(epoch!==buildEpoch||buildFile!==path)return;if(disk.revision!==b.revision){if(b.content===b.saved){buildBuffers.set(path,{...disk,saved:disk.content});displayBuildFile();$('build-file-status').textContent='Updated from disk';scheduleBuildPreview();}else $('build-file-status').textContent='File changed on disk · your draft is preserved. Reload to review.';}}catch(error){$('build-file-status').textContent=error.message;}}
 }
 }finally{if(epoch===buildEpoch)buildPolling=false;}
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
 const path=buildFile,b=buildBuffers.get(path),epoch=buildEpoch;if(!b)return;if(b.readonly)throw Error('Formatting is disabled for large read-only files.');
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
 const language=codeEditor.setDocument(b?buildProject+'/'+buildFile:'',buildFile,b?.content||'',!!b&&!b.readonly);
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

let buildImages=[];
function renderBuildImages(){
 $('build-images').replaceChildren();
 for(const [index,item] of buildImages.entries()){
  const box=document.createElement('div'),img=document.createElement('img'),remove=document.createElement('button');
  img.src='data:'+item.mime+';base64,'+item.data;img.alt=item.name;img.title=item.name;
  remove.type='button';remove.className='quiet';remove.textContent='×';remove.setAttribute('aria-label','Remove '+item.name);
  remove.onclick=()=>{if(!buildBusy){buildImages.splice(index,1);renderBuildImages();}};
  box.append(img,remove);$('build-images').append(box);
 }
 $('build-image-status').textContent=buildImages.length?buildImages.length+' image(s) ready · sent with your next message':'Paste or drop screenshots here';
}
async function attachBuildImages(files){
 if(buildBusy)return;
 const project=$('build-project').value;
 try{
  for(const file of files){
   if(buildImages.length>=3)throw Error('Attach up to three screenshots.');
   if(!['image/png','image/jpeg','image/webp'].includes(file.type))throw Error('Use PNG, JPEG or WebP images.');
   if(file.size>4000000)throw Error('Each image must be under 4 MB.');
   if(buildImages.reduce((sum,i)=>sum+i.data.length*.75,0)+file.size>9000000)throw Error('Images must total under 9 MB.');
   const url=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('Could not read image.'));reader.readAsDataURL(file);});
   if(project!==$('build-project').value)return;
   buildImages.push({type:'image',name:file.name,mime:file.type,data:url.split(',')[1]});renderBuildImages();
  }
 }catch(error){$('build-image-status').textContent=error.message;}
}
$('build-attach').onclick=()=>$('build-image-input').click();
$('build-image-input').onchange=async e=>{await attachBuildImages([...e.target.files]);e.target.value='';};
// Enter sends, Shift+Enter adds a new line (IME composition is left alone).
$('build-prompt').addEventListener('keydown',e=>{
 if(e.key!=='Enter'||e.shiftKey||e.isComposing||e.keyCode===229)return;
 e.preventDefault();if(!$('send-build').disabled)$('send-build').click();
});
$('build-prompt').addEventListener('paste',e=>{const files=[...e.clipboardData.items].filter(i=>i.kind==='file').map(i=>i.getAsFile()).filter(Boolean);if(files.length){e.preventDefault();attachBuildImages(files);}});
const buildDropZone=document.querySelector('.ide-prompt');
buildDropZone.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files'))e.preventDefault();});
buildDropZone.addEventListener('drop',e=>{if(e.dataTransfer.files.length){e.preventDefault();attachBuildImages([...e.dataTransfer.files]);}});
$('build-generate-image').onclick=()=>openImageReview($('build-prompt').value);

let buildProviderProfiles={};
function renderBuildProviderForm(){
 const id=$('build-ai-provider').value,cfg=buildProviderProfiles[id]||{},local=id==='local';
 for(const name of ['claude','claude-label','claude-note','defaults'])$('build-ai-'+name).hidden=id!=='claude';
 $('build-ai-model').value=cfg.model||'';$('build-ai-key').value='';$('build-ai-key').placeholder=cfg.has_key?'Key saved · leave blank to keep it':'Paste your provider API key';
 syncBuildClaudePicker();
 $('build-ai-context').value=cfg.context||32768;$('build-ai-output').value=cfg.output||8192;$('build-ai-vision').checked=!!cfg.vision;
 for(const name of ['model','key','context','output','vision'])$('build-ai-'+name).disabled=local;
 $('build-ai-autotune').hidden=!local;
 $('build-ai-help').textContent=local?'Uses your selected LM Studio model, detected vision support and loaded context. Use Auto-tune in Models to pick the largest context that fits your GPU.':'Use the exact model ID supplied by your provider. Context and vision are your configured budgets, not automatically verified model capabilities.';
}
async function loadBuildProviderSettings(refreshForm=true){
 const data=await buildRequest('provider_settings');buildProviderProfiles=data.profiles;
 if(!refreshForm){$('build-ai-settings').textContent='AI · '+data.profiles[data.selected].name;return;}
 $('build-ai-provider').replaceChildren();for(const [id,cfg] of Object.entries(data.profiles))$('build-ai-provider').add(new Option(cfg.name,id));
 $('build-ai-provider').value=data.selected;$('build-ai-settings').textContent='AI · '+data.profiles[data.selected].name;renderBuildProviderForm();
}
$('build-ai-settings').onclick=()=>buildAction(async()=>{await loadBuildProviderSettings();$('build-ai-feedback').textContent='';$('build-ai-dialog').showModal();});
$('build-ai-provider').onchange=renderBuildProviderForm;
$('build-ai-autotune').onclick=()=>{$('build-ai-dialog').close();$('model-manager').click();};
$('build-ai-save').onclick=async()=>{
 const button=$('build-ai-save');button.disabled=true;$('build-ai-feedback').textContent='Saving…';
 try{
  await buildRequest('save_provider',{provider:$('build-ai-provider').value,model:$('build-ai-model').value.trim(),key:$('build-ai-key').value.trim(),context:Number($('build-ai-context').value),output:Number($('build-ai-output').value),vision:$('build-ai-vision').checked});
  $('build-ai-key').value='';await loadBuildProviderSettings();$('build-ai-feedback').textContent='Saved. Used for the next Build request; no cloud request has been sent.';
 }catch(error){$('build-ai-feedback').textContent=error.message;}finally{button.disabled=false;}
};
setTimeout(()=>loadBuildProviderSettings(false).catch(()=>{}),1600);

function syncBuildClaudePicker(){
 const picker=$('build-ai-claude'),model=$('build-ai-model').value.trim();
 picker.value=[...picker.options].some(option=>option.value===model)?model:'';
 $('build-ai-defaults').disabled=!picker.value;
}
$('build-ai-claude').onchange=()=>{
 const model=$('build-ai-claude').value;
 $('build-ai-defaults').disabled=!model;
 if(model){$('build-ai-model').value=model;applyBuildClaudeDefaults();}
 else $('build-ai-model').focus();
};
$('build-ai-model').addEventListener('input',syncBuildClaudePicker);

function applyBuildClaudeDefaults(){
 if($('build-ai-provider').value!=='claude'||!$('build-ai-claude').value)return;
 $('build-ai-context').value=131072;
 $('build-ai-output').value=16384;
 $('build-ai-vision').checked=true;
 $('build-ai-feedback').textContent='Suggested coding settings filled in: 131,072 context · 16,384 output · image input on. Save to apply.';
}
$('build-ai-defaults').onclick=applyBuildClaudeDefaults;

let buildTerminalScope=null;
function buildTerminalEnabled(){
 return !!($('build-auto-bash').checked&&buildTerminalScope&&buildTerminalScope.project===$('build-project').value&&buildTerminalScope.session===$('build-session').value);
}
function resetBuildTerminalApproval(){
 buildTerminalScope=null;$('build-auto-bash').checked=false;
 $('build-approval-status').textContent='Other commands ask first · Context compacts automatically';
}
$('build-auto-bash').onchange=()=>{
 if(!$('build-auto-bash').checked){resetBuildTerminalApproval();return;}
 const project=$('build-project').value,session=$('build-session').value;
 if(!project||!session){resetBuildTerminalApproval();$('build-approval-status').textContent='Choose a project and coding session first.';return;}
 buildTerminalScope={project,session};
 $('build-approval-status').textContent='Terminal auto-approval ON for this session · Turn off to stop future approvals; Stop cancels running work.';
};

function isBuildContextOverflow(error){
 return /Context(?:Window|Length|Size)Exceeded|ContextOverflow|context[_ -](?:length|window|size)[_ -]exceeded|exceed[_ -]context|exceed.{0,100}context|context.{0,60}(?:exceed|too (?:long|large)|maximum)|maximum context (?:length|size)|prompt is too long/i.test(JSON.stringify(error||{}));
}
let buildRecovery=null;
function renderBuildRecovery(data){
 const recovery=data.recovery||{},warnings=data.warnings||[];
 buildRecovery={...recovery,project:$('build-project').value,session:$('build-session').value};
 $('build-recovery').hidden=data.status.type!=='idle'&&!data.permission_error&&!warnings.length;
 $('build-recovery-label').textContent=recovery.label||'Task status';
 $('build-recovery-detail').textContent=[recovery.detail,...warnings].filter(Boolean).join(' ');
 $('build-continue').hidden=!recovery.can_continue;
 $('build-continue').textContent=recovery.action==='recover_context'?'Start fresh session ↗':'Continue task ↗';
 $('build-continue').disabled=buildBusy||data.status.type!=='idle';
}
$('build-continue').onclick=()=>buildAction(async()=>{
 if(buildBusy||buildAgentBusy)return;
 const recovery=buildRecovery,epoch=buildEpoch,project=$('build-project').value,session=$('build-session').value;
 if(!recovery?.can_continue||recovery.project!==project||recovery.session!==session)return;
 if($('build-prompt').value.trim()){$('build-status').textContent='Your draft is preserved. Send it or clear it before continuing the previous task.';return;}
 if(buildImages.length){$('build-status').textContent='Your attachments are preserved. Send or remove them before continuing.';return;}
 if(recovery.action==='recover_context'){
  buildBusy=true;$('build-continue').disabled=true;$('send-build').disabled=true;
  try{
   const result=await buildRequest('recover_context',{project,session});
   if(epoch!==buildEpoch||project!==$('build-project').value||session!==$('build-session').value)return;
   $('build-session').add(new Option(result.session.title,result.session.id));
   if($('build-prompt').value.trim()||buildImages.length){$('build-status').textContent='Your draft and attachments are preserved. A fresh session is available in the session picker.';return;}
   $('build-session').value=result.session.id;
   buildEpoch++;buildPolling=false;buildMessagesSnapshot='';buildPermissionsSnapshot='';buildRecovery=null;
   $('build-output').replaceChildren();$('build-permissions').replaceChildren();$('build-recovery').hidden=true;$('build-diff').textContent='No recorded file changes yet.';
   resetBuildTerminalApproval();resetBuildTaskTimer();
   if(window.showContextMeter)showContextMeter('build-context-meter',null);
   $('build-prompt').value=result.prompt;$('build-prompt').focus();
   const freshEpoch=buildEpoch;
   beginBuildPolling();await pollBuild();
   if(freshEpoch===buildEpoch)$('build-status').textContent='Fresh session ready. Review the handoff, add any missing details, then Send. The original chat is still in the session picker.';
  }finally{buildBusy=false;$('send-build').disabled=buildAgentBusy;$('build-continue').disabled=buildAgentBusy;}
  return;
 }
 $('build-prompt').value='Continue the unfinished task in this session. First inspect the current project files and the most recent error. Preserve completed work; do not repeat already successful commands or edits. Make the next small useful change, run appropriate checks with the existing approval rules, and report what was verified and what remains blocked. If the task is already complete, summarize the result without making unnecessary changes.';
 $('send-build').click();
});

let docsTimer=null,docsRefreshBusy=false;
async function refreshOfflineDocs(){
 if(docsRefreshBusy)return;docsRefreshBusy=true;
 try{
 const data=await buildRequest('docs_status');const selected=$('docs-pack').value;
 $('docs-pack').replaceChildren(new Option('All packs','all'));
 $('docs-packs').replaceChildren();
 for(const pack of data.packs){
  $('docs-pack').add(new Option(pack.name,pack.id));
  const card=document.createElement('div');card.className='docs-pack';
  const title=document.createElement('strong');title.textContent=pack.name;
  const detail=document.createElement('small');detail.textContent=pack.version+' · '+pack.installed+'/'+pack.available+' pages'+(pack.updated?' · '+new Date(pack.updated).toLocaleDateString():' · not downloaded');
  card.append(title,detail);$('docs-packs').append(card);
 }
 $('docs-pack').value=selected;$('docs-install').disabled=data.job.running;
 if(data.job.running)$('docs-status').textContent='Downloading official sources… '+data.job.done+'/'+data.job.total;
 else if(data.job.errors.length)$('docs-status').textContent=data.job.errors.length+' pages could not update. Previous copies are preserved. '+data.job.errors.map(e=>e.pack+': '+e.message).join(' ');
 }finally{docsRefreshBusy=false;}
}
$('build-docs').onclick=()=>buildAction(async()=>{
 $('build-docs-dialog').showModal();await refreshOfflineDocs();
 clearInterval(docsTimer);docsTimer=setInterval(()=>{if(!$('build-docs-dialog').open){clearInterval(docsTimer);return;}refreshOfflineDocs().catch(e=>$('docs-status').textContent=e.message);},2500);
});
$('docs-install').onclick=async()=>{
 try{await buildRequest('docs_install',{pack:$('docs-pack').value});$('docs-status').textContent='Download started…';await refreshOfflineDocs();}
 catch(error){$('docs-status').textContent=error.message;}
};
$('docs-search-form').onsubmit=async event=>{
 event.preventDefault();$('docs-status').textContent='Searching local library…';
 try{
 const data=await buildRequest('docs_search',{query:$('docs-query').value,pack:$('docs-pack').value});$('docs-results').replaceChildren();
 for(const hit of data.results){
  const card=document.createElement('article');card.className='docs-result';
  const link=document.createElement('a');link.href=hit.source;link.target='_blank';link.rel='noopener noreferrer';link.textContent=hit.title;
  const meta=document.createElement('p');meta.className='micro';meta.textContent=hit.version+' · Downloaded '+new Date(hit.downloaded).toLocaleDateString()+' · Reference '+hit.reference;
  const content=document.createElement('pre');content.textContent=hit.excerpt;card.append(link,meta,content);$('docs-results').append(card);
 }
 $('docs-status').textContent=data.results.length?data.results.length+' excerpts found offline. Check versions before applying.':'No matching offline excerpts. Try different keywords, download the pack, or consult official online docs.';
 }catch(error){$('docs-status').textContent=error.message;}
};

// Capture uses saved files; the user reviews attachments before sending them.
$('audit-build-site').onclick=()=>buildAction(async()=>{
 if(!requireBuildProject())return;
 if(buildDirty())throw Error('Save your edits before auditing. The audit reads files on disk.');
 const button=$('audit-build-site');button.disabled=true;$('build-preview-status').textContent='Auditing site…';
 try{
  const result=await buildRequest('audit_site');
  const c=result.counts||{};
  $('build-preview-status').textContent=`Audit · score ${result.score}/100 · ${c.error||0} errors, ${c.warning||0} warnings${(c.error||c.warning)?' · report added to your prompt. Send to have the AI fix them.':' · nothing to fix.'}`;
  if(c.error||c.warning)$('build-prompt').value=(($('build-prompt').value?$('build-prompt').value+'\n\n':'')+'Fix these site audit findings (errors first), then run the audit again:\n'+result.report).slice(0,12000);
 }finally{button.disabled=false;}
});
$('capture-build-preview').onclick=()=>buildAction(async()=>{
 if(!requireBuildProject()||buildBusy)return;
 if(buildDirty())throw Error('Save your edits before checking the preview. Screenshots use files on disk.');
 if(buildImages.length>1)throw Error('Make room for two preview screenshots by removing an attachment.');
 const epoch=buildEpoch,button=$('capture-build-preview');button.disabled=true;buildBusy=true;buildPreviewCapturing=true;
 const dev=!!devLive(buildDev);
 setBuildOrb('preview-check');$('build-preview-status').textContent='Capturing desktop and mobile screenshots'+(dev?' of the live dev server…':'…');
 try{
  const result=await buildRequest('capture_preview',{path:$('build-preview-entry').value.trim(),dev});
  if(epoch!==buildEpoch)return;
  buildImages.push(...result.images);renderBuildImages();
  const report=JSON.stringify(result.reports);
  const review='Review these desktop and mobile screenshots of '+result.entry+'. Check layout, readability and rendering against the requested design. Fix visible problems. Browser report: '+report;
  $('build-prompt').value=($('build-prompt').value+'\n\n'+review).trim().slice(0,12000);
  $('build-preview-status').textContent='Desktop + mobile captured · screenshots attached. Send to ask AI to review.';
 }finally{buildBusy=false;buildPreviewCapturing=false;button.disabled=false;if(epoch===buildEpoch)setBuildOrb(buildAgentBusy?'thinking':'idle');}
});
