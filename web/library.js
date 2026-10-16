let currentChat=null, chatLibrary={chats:[],folders:[]};
async function libraryRequest(data){
  const response=await fetch('/api/library',{method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Token':token},body:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Could not save changes.');return result;
}
async function fetchConversation(id){
  const response=await fetch('/api/conversation?id='+encodeURIComponent(id),{headers:{'X-Jarvis-Token':token}});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Could not load chat.');return result;
}
async function ensureConversation(){
  if(!currentChat){
    let previous;try{previous=localStorage.getItem('jarvis-current-chat');}catch{}
    if(previous){await openConversation(previous);}
    else await newConversation();
  }

}
async function newConversation(){
  if(busy)return;
  const result=await libraryRequest({action:'create',personality:systemPrompt,folder_id:$('folder-filter').value||null});
  await openConversation(result.id);await refreshLibrary();
}
function renderSavedResults(article,results){
  if(!results?.length)return;
  const sources=document.createElement('details');sources.className='answer-sources';
  const summary=document.createElement('summary');summary.textContent=`Sources · ${results.length}`;sources.append(summary);article.append(sources);
  for(const [index,result] of results.entries()){
    let url;try{url=new URL(result.url);}catch{continue;}if(!['http:','https:'].includes(url.protocol))continue;
    const card=document.createElement('div');card.className='search-result';
    const a=document.createElement('a');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent=`[${index+1}] ${result.title}`;
    const p=document.createElement('p');p.textContent=result.snippet;card.append(a,p);sources.append(card);
  }
}
async function openConversation(id){
  if(busy)return;
  const chat=await fetchConversation(id);currentChat=chat;systemPrompt=chat.personality;
  try{localStorage.setItem('jarvis-current-chat',id);}catch{}
  stopAssistantVoice();history=[];attachments=[];renderAttachments();$('messages').replaceChildren();
  for(const message of chat.messages){
    const article=addMessage(message.role,message.content,message.source);
    for(const file of message.attachments||[]){
      const name=document.createElement('small');name.textContent='Attached: '+(file.name||'Image');article.append(name);
      if(file.type==='image'){const img=document.createElement('img');img.className='saved-image';img.alt=file.name||'Attached image';img.src='data:'+file.mime+';base64,'+file.data;article.append(img);}
    }
    renderSavedResults(article,message.results);
  }
  if(!chat.messages.length)addMessage('assistant','A fresh start. What would you like to work on?');
  $('conversation-title').textContent=chat.title;
  $('messages').scrollTop=$('messages').scrollHeight;
  fillChatDetails();
}
function fillChatDetails(){
  $('auto-memory-text').textContent=currentChat?.summary?.content||'No compaction needed yet.';
  $('chat-title').value=currentChat?.title||'';$('chat-memory').value=currentChat?.memory||'';
  $('chat-folder').value=currentChat?.folder_id||'';
  $('archive-chat').textContent=currentChat?.archived?'Restore chat':'Archive chat';
  $('save-chat').disabled=!currentChat;$('archive-chat').disabled=!currentChat;
}
async function refreshLibrary(){
  const response=await fetch('/api/library',{headers:{'X-Jarvis-Token':token},signal:AbortSignal.timeout(15000)});if(!response.ok)throw Error('Could not load chat library.');
  chatLibrary=await response.json();
  for(const id of ['folder-filter','chat-folder']){
    const select=$(id),previous=select.value;select.replaceChildren();
    const all=document.createElement('option');all.value='';all.textContent=id==='folder-filter'?'All folders':'Unfiled';select.append(all);
    for(const folder of chatLibrary.folders){const option=document.createElement('option');option.value=folder.id;option.textContent=folder.name;select.append(option);}
    select.value=previous;
  }
  fillChatDetails();renderChatList();
}
function renderChatList(){
  $('chat-list').replaceChildren();const query=$('chat-filter').value.toLowerCase(),folder=$('folder-filter').value;
  const chats=chatLibrary.chats.filter(c=>Boolean(c.archived)===$('show-archived').checked&&(!folder||c.folder_id===folder)&&c.title.toLowerCase().includes(query));
  for(const chat of chats){
    const button=document.createElement('button');button.className='chat-row';button.textContent=chat.title;button.title=new Date(chat.updated*1000).toLocaleString();
    if(chat.id===currentChat?.id)button.setAttribute('aria-current','true');
    button.onclick=()=>libraryAction(async()=>{await openConversation(chat.id);renderChatList();$('library-dialog').close();if(innerWidth<=1100)setSidebar(false);if(typeof showView==='function')showView('assistant');});
    const row=document.createElement('div');row.className='chat-entry';
    const actions=document.createElement('div');actions.className='chat-row-actions';
    for(const [action,label,icon] of [['rename','Rename','✎'],['archive',chat.archived?'Restore':'Archive',chat.archived?'↶':'▣'],['delete','Delete','×']]){
      const control=document.createElement('button');control.className='chat-action '+action;control.textContent=icon;control.title=label;control.setAttribute('aria-label',`${label} ${chat.title}`);
      control.onclick=()=>{if(!busy)openChatAction(chat,action);};actions.append(control);
    }
    row.append(button,actions);$('chat-list').append(row);
  }
  if(!chats.length){const p=document.createElement('p');p.className='micro';p.textContent='No chats here yet.';$('chat-list').append(p);}
}
async function libraryAction(fn){if(busy)return;try{$('library-status').textContent='';await fn();}catch(error){$('library-status').textContent=error.message;$('sidebar-status').textContent=error.message;}}
$('manage-chat').onclick=()=>libraryAction(async()=>{await ensureConversation();currentChat=await fetchConversation(currentChat.id);await refreshLibrary();$('library-dialog').showModal();});
$('close-library').onclick=()=>$('library-dialog').close();
$('new-chat').onclick=()=>libraryAction(newConversation);
$('chat-filter').oninput=renderChatList;$('folder-filter').onchange=renderChatList;$('show-archived').onchange=renderChatList;
$('new-folder').onclick=()=>libraryAction(async()=>{const result=await libraryRequest({action:'folder_create',name:$('folder-name').value});await refreshLibrary();$('folder-filter').value=result.id;renderChatList();$('folder-name').value='';});
$('rename-folder').onclick=()=>libraryAction(async()=>{if(!$('folder-filter').value)throw Error('Choose a folder first.');await libraryRequest({action:'folder_rename',id:$('folder-filter').value,name:$('folder-name').value});await refreshLibrary();});
$('remove-folder').onclick=()=>libraryAction(async()=>{if(!$('folder-filter').value)throw Error('Choose a folder first.');await libraryRequest({action:'folder_remove',id:$('folder-filter').value});if(currentChat)currentChat=await fetchConversation(currentChat.id);await refreshLibrary();$('library-status').textContent='Folder removed; its chats are now unfiled.';});
$('save-chat').onclick=()=>libraryAction(async()=>{await libraryRequest({action:'update',id:currentChat.id,version:currentChat.version,title:$('chat-title').value,folder_id:$('chat-folder').value,memory:$('chat-memory').value});currentChat=await fetchConversation(currentChat.id);$('conversation-title').textContent=currentChat.title;await refreshLibrary();$('library-status').textContent='Saved locally.';});
$('archive-chat').onclick=()=>libraryAction(async()=>{await libraryRequest({action:'update',id:currentChat.id,version:currentChat.version,archived:!currentChat.archived});currentChat=await fetchConversation(currentChat.id);await refreshLibrary();$('library-status').textContent=currentChat.archived?'Chat archived. Use Show archived chats to restore it.':'Chat restored.';});
async function restoreCurrentChat(){
  let id;try{id=localStorage.getItem('jarvis-current-chat');}catch{}
  if(id)await openConversation(id);
  await refreshLibrary();
}
function updateSearchFields(){
  const local=$('search-engine').value==='searxng';
  $('searxng-fields').hidden=!local; $('brave-fields').hidden=local;
}
$('search-engine').onchange=()=>{updateSearchFields();$('search-status').textContent='';};
$('search-settings').onclick=async()=>{ $('search-key').value='';$('search-status').textContent='';updateSearchFields();$('search-dialog').showModal(); try { const response=await fetch('/api/status'); const data=await response.json(); $('search-engine').value=data.search.engine||'brave'; $('search-url').value=data.search.url||'http://127.0.0.1:8088'; updateSearchFields(); } catch(error) { $('search-status').textContent=error.message; } };
$('close-search').onclick=()=>$('search-dialog').close();
$('search-dialog').addEventListener('close',()=>{$('search-key').value='';});
async function saveSearch(remove=false){
  $('save-search').disabled=true;
  try{
    const response=await fetch('/api/search-settings',{method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Token':token},body:JSON.stringify({key:$('search-key').value.trim(),remove,engine:$('search-engine').value,url:$('search-url').value.trim()})});
    const data=await response.json();if(!response.ok)throw Error(data.error);
    $('search-key').value='';$('search-status').textContent=data.engine==='searxng'?'Local SearXNG selected. Send a web search to verify the server.':data.configured?'Key saved. Send a web search to verify it.':'No key configured. Browser search links are available.';
  }catch(error){$('search-status').textContent=error.message;}finally{$('save-search').disabled=false;}
}
$('save-search').onclick=()=>saveSearch();$('remove-search').onclick=()=>saveSearch(true);

function setSidebar(open){
  document.body.classList.toggle('sidebar-open',open);
  $('sidebar-backdrop').hidden=!open||innerWidth>1100;
  $('chat-library').setAttribute('aria-expanded',String(open));
}
$('chat-library').onclick=()=>setSidebar(!document.body.classList.contains('sidebar-open'));
$('close-sidebar').onclick=() =>setSidebar(false);
$('sidebar-backdrop').onclick=()=>setSidebar(false);
const sidebarMedia=matchMedia('(min-width:1101px)');
sidebarMedia.addEventListener('change',event=>setSidebar(event.matches));
setSidebar(sidebarMedia.matches);

let pendingChatAction=null;
function openChatAction(chat,action){
  pendingChatAction={chat,action};
  $('chat-action-heading').textContent={rename:'Rename chat',archive:chat.archived?'Restore chat?':'Archive chat?',delete:'Delete chat?'}[action];
  $('chat-action-description').textContent=action==='delete'?`“${chat.title}” and its messages, attachments, and memory will be permanently deleted.`:action==='archive'?`“${chat.title}” will be ${chat.archived?'returned to your chats':'archived. You can restore it later'}.`:'Give this conversation a name.';
  $('chat-action-name').hidden=action!=='rename';$('chat-action-name').value=chat.title;
  $('confirm-chat-action').textContent={rename:'Save name',archive:chat.archived?'Restore':'Archive',delete:'Delete permanently'}[action];
  $('confirm-chat-action').classList.toggle('danger',action==='delete');$('chat-action-error').textContent='';
  $('chat-action-dialog').showModal();if(action==='rename')$('chat-action-name').focus();else $('cancel-chat-action').focus();
}
$('cancel-chat-action').onclick=()=>$('chat-action-dialog').close();
$('chat-action-form').onsubmit=async event=>{
  event.preventDefault();if(busy||!pendingChatAction)return;
  const {chat,action}=pendingChatAction;$('confirm-chat-action').disabled=true;
  try{
    const data={action:action==='delete'?'delete':'update',id:chat.id,version:chat.version};
    if(action==='rename')data.title=$('chat-action-name').value.trim();
    if(action==='archive')data.archived=!chat.archived;
    await libraryRequest(data);
    if(currentChat?.id===chat.id){
      if(action==='delete'){
        stopAssistantVoice();currentChat=null;history=[];attachments=[];renderAttachments();$('messages').replaceChildren();$('conversation-title').textContent='New chat';
        try{localStorage.removeItem('jarvis-current-chat');}catch{}
        addMessage('assistant','Chat deleted. Start a new conversation whenever you’re ready.');
      }else{currentChat=await fetchConversation(chat.id);$('conversation-title').textContent=currentChat.title;}
    }
    await refreshLibrary();$('chat-action-dialog').close();$('sidebar-status').textContent=action==='delete'?'Chat deleted.':action==='rename'?'Chat renamed.':chat.archived?'Chat restored.':'Chat archived.';
  }catch(error){$('chat-action-error').textContent=error.message;}
  finally{$('confirm-chat-action').disabled=false;}
};

// Start chat after its small core dependencies, without waiting for IDE downloads.
connectAssistant();
