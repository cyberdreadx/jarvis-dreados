let creationKind = 'post', connections = [], selectedTool = null;
const draftKey = 'jarvis-drafts-v1';
function showView(name) {
  document.body.classList.toggle('ide-active',name==='build');
  for (const view of ['assistant','create','connections','build','situation','media']) $(view + '-view').hidden = view !== name;
  document.querySelectorAll('[data-view]').forEach(button => {
    if (button.dataset.view === name) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  });
  if (name === 'create' || name === 'connections') loadConnections();
  if (name === 'situation' && typeof interactiveMap!=='undefined' && interactiveMap)requestAnimationFrame(()=>interactiveMap.invalidateSize());
  if (name === 'build') refreshBuildProjects();
  if (name === 'create') renderLibrary();
  if (name === 'media') loadMedia();
  window.scrollTo({top:0,behavior:'instant'});
}
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => showView(button.dataset.view));
document.querySelectorAll('[data-open-connections]').forEach(button => button.onclick = () => showView('connections'));
async function api(path, data, timeout = 130000) {
  if (!token) throw new Error('DreadOS AI is reconnecting. Try again in a moment.');
  const response = await fetch(path, {method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Token':token},body:JSON.stringify(data),signal:AbortSignal.timeout(timeout)});
  const value = await response.json(); if (!response.ok) throw new Error(value.error || 'Request failed.'); return value;
}
function setKind(kind) {
  creationKind = kind;
  $('creative-brief').placeholder={post:'Describe your post. What is the idea, announcement, or story?',art:'Describe the artwork. What should it look and feel like?',video:'Describe your video. What happens, and who is it for?'}[kind];
  document.querySelectorAll('[data-kind]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.kind === kind)));
  $('brief-title').textContent = {post:'What are we posting?',art:'What should we bring to life?',video:'What story are we telling?'}[kind];
  $('create-draft').textContent = {post:'Create post draft ↗',art:'Create artwork prompt ↗',video:'Create video brief ↗'}[kind];
  $('create-help').textContent = kind === 'post' ? 'Uses your selected AI provider. You review and publish.' : 'AI-written direction. Generate the actual media with a connected tool.';
}
document.querySelectorAll('[data-kind]').forEach(button => button.onclick = () => setKind(button.dataset.kind));
$('create-form').onsubmit = async event => {
  event.preventDefault(); const kind = creationKind, provider = activeProvider;
  $('create-draft').disabled = true; $('create-status').textContent = 'Developing your idea…';
  try {
    const data = await api('/api/create', {kind,provider,brief:$('creative-brief').value,platform:$('creative-platform').value,tone:$('creative-tone').value,audience:$('creative-audience').value}, 310000);
    if (typeof data.draft !== 'string' || !data.draft.trim()) throw new Error('The model returned an empty draft. Please try again.');
    $('draft-output').value = data.draft; $('output-title').textContent = {post:'Your post, ready to refine.',art:'Your visual direction.',video:'Your story, shot by shot.'}[kind];
    $('draft-meta').textContent = `${providerSettings?.[provider]?.name || provider} · ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
    outputChanged(); $('create-status').textContent = 'Draft ready.'; $('creator-result').scrollIntoView({behavior:'smooth',block:'start'});
  } catch (error) { $('create-status').textContent = error.message; }
  finally { $('create-draft').disabled = false; }
};
function outputChanged() { $('creator-result').hidden=!$('draft-output').value.trim(); for (const id of ['copy-draft','download-draft','save-draft']) $(id).disabled = !$('draft-output').value.trim(); }
$('draft-output').oninput = outputChanged;
$('copy-draft').onclick = async () => {
  try { await navigator.clipboard.writeText($('draft-output').value); $('create-status').textContent = 'Copied to clipboard.'; }
  catch { $('draft-output').focus(); $('draft-output').select(); $('create-status').textContent = 'Select and copy the draft with Ctrl+C.'; }
};
$('download-draft').onclick = () => {
  const url = URL.createObjectURL(new Blob([$ ('draft-output').value], {type:'text/plain;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = `jarvis-${creationKind}-${Date.now()}.txt`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
function drafts() { try { const value = JSON.parse(localStorage.getItem(draftKey) || '[]'); return Array.isArray(value) ? value.filter(v => v && typeof v.text === 'string' && typeof v.id === 'string').slice(0,30) : []; } catch { return []; } }
$('save-draft').onclick = async () => {
  $('save-draft').disabled=true;
  try { await api('/api/media',{action:'draft',format:creationKind,text:$('draft-output').value,brief:$('creative-brief').value}); $('create-status').textContent='Saved to shared Library. Available on your other devices.'; }
  catch(error){$('create-status').textContent=error.message;}
  finally {outputChanged();}
};
function element(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function renderLibrary() {
  $('draft-library').replaceChildren(); const items = drafts();
  if (!items.length) $('draft-library').append(element('p','Your saved drafts will appear here.','micro'));
  for (const item of items) {
    const card = element('article',undefined,'library-card'); card.append(element('div',`${item.kind || 'draft'} · ${item.date || ''}`,'eyebrow'),element('p',item.text.slice(0,150)));
    const open = element('button','Open draft ↗','quiet'); open.onclick = () => { setKind(['post','art','video'].includes(item.kind) ? item.kind : 'post'); $('draft-output').value = item.text; $('creative-brief').value = item.brief || ''; $('output-title').textContent = 'Your saved draft.'; $('draft-meta').textContent = 'Opened from this browser'; outputChanged(); $('draft-output').focus(); };
    const remove = element('button','Remove','quiet'); remove.onclick = () => { try { localStorage.setItem(draftKey,JSON.stringify(drafts().filter(d => d.id !== item.id))); renderLibrary(); } catch { $('create-status').textContent = 'Could not update browser storage.'; } };
    card.append(open,remove); $('draft-library').append(card);
  }
}
async function loadConnections() {
  try {
    const response = await fetch('/api/connections'); if (!response.ok) throw new Error('Could not load connections.'); const data = await response.json();
    connections = data.connections; renderConnections();
    $('connection-presets').replaceChildren();
    for (const preset of data.presets) {
      const card = element('article',undefined,'connection-card'); card.append(element('span',preset.category,'eyebrow'),element('h2',preset.name),element('p',preset.description));
      const button = element('button','Set up connection ↗','quiet'); button.onclick = () => { $('connection-name').value = preset.name; $('connection-url').value = preset.url; $('connection-token').value = ''; $('connection-token').placeholder=preset.name==='GLTCH Runner'?'gltch_sk_… (saved with Windows encryption)':'Leave blank for browser sign-in';$('connection-token').focus(); };
      const docs = element('a','Setup guide','quiet'); docs.href = preset.docs; docs.target = '_blank'; docs.rel = 'noopener noreferrer'; card.append(button,docs); $('connection-presets').append(card);
    }
  } catch (error) { $('connection-status').textContent = error.message; }
}
function renderConnections() {
  $('connection-list').replaceChildren();
  if (!connections.length) $('connection-list').append(element('p','Nothing connected yet. Pick a service above or add your own server.','micro'));
  for (const connection of connections) {
    const card = element('article',undefined,'connected-row'); card.append(element('strong',connection.name),element('span',connection.status.replaceAll('_',' '),'connection-state'));
    card.append(element('p',connection.status === 'connected' ? `${connection.tools.length} tools available` : connection.error || 'Ready to connect','micro'));
    const retry = element('button','Reconnect','quiet'); retry.onclick = () => connectionAction('/api/mcp/connect',{id:connection.id});
    const auth = element('button','Sign in ↗','quiet'); auth.onclick = () => connectionAction('/api/mcp/auth',{id:connection.id});
    const remove = element('button','Disconnect','quiet'); remove.onclick = () => connectionAction('/api/mcp/remove',{id:connection.id});
    card.append(retry); if (connection.status !== 'connected' && connection.url !== 'https://api.gltch.app') card.append(auth); card.append(remove); $('connection-list').append(card);
  }
  const prior = $('tool-connection').value;
  $('tool-connection').replaceChildren(new Option('Choose a connected service',''));
  for (const connection of connections.filter(c => c.status === 'connected')) $('tool-connection').append(new Option(connection.name,connection.id));
  if (connections.some(c => c.id === prior && c.status === 'connected')) $('tool-connection').value = prior;
  renderTools();
}
let connecting = false;
async function connectionAction(path, payload) {
  if (connecting) return; connecting = true; $('connect-server').disabled = true; $('connection-status').textContent = path.endsWith('/auth') ? 'Preparing secure sign-in…' : 'Contacting the MCP server…'; $('auth-link').replaceChildren();
  try {
    const data = await api(path,payload);
    if (data.authorization_url) {
      const link = element('a','Continue to service sign-in ↗','primary auth-button'); link.href = data.authorization_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; $('auth-link').append(link);
      $('connection-status').textContent = 'Complete sign-in in the service’s page, then refresh connections here.';
    } else {
      connections = data.connections; renderConnections(); $('connection-token').value = '';
      $('connection-status').textContent = 'Connection status updated. Tool access is shown above.';
    }
  } catch (error) { $('connection-status').textContent = error.message; }
  finally { connecting = false; $('connect-server').disabled = false; }
}
$('connection-form').onsubmit = event => { event.preventDefault(); connectionAction('/api/mcp/add',{name:$('connection-name').value,url:$('connection-url').value.trim(),token:$('connection-token').value.trim()}); };
$('refresh-connections').onclick = loadConnections;
function renderTools() {
  $('tool-select').replaceChildren(new Option('Choose a tool',''));
  const connection = connections.find(c => c.id === $('tool-connection').value);
  for (const tool of connection?.tools || []) $('tool-select').append(new Option(tool.title || ({list_models:'Browse models · free',generate_image:'Generate image',edit_image:'Edit image',generate_video:'Animate image → video',check_job:'Check video progress'}[tool.name]) || tool.name,tool.name));
  renderToolFields();
}
$('tool-connection').onchange = renderTools;
$('tool-select').onchange = renderToolFields;
function renderToolFields() {
  const connection = connections.find(c => c.id === $('tool-connection').value);
  selectedTool = connection?.tools.find(t => t.name === $('tool-select').value) || null;
  $('tool-fields').replaceChildren(); $('tool-extra').value = ''; $('tool-result').replaceChildren(); $('tool-status').textContent = '';
  $('tool-description').textContent = selectedTool?.description || 'Available tools appear after a service is connected.'; $('run-tool').disabled = !selectedTool;
  const schema = selectedTool?.inputSchema || {};
  for (const [name, property] of Object.entries(schema.properties || {})) {
    const type = property.type || 'json'; const required = (schema.required || []).includes(name); const id = 'tool-field-' + $('tool-fields').children.length;
    const label = element('label',(property.title || name.replaceAll('_',' ')) + (required ? ' *' : '')); label.htmlFor = id;
    let input;
    if (property.enum) { input = document.createElement('select'); input.append(new Option('Select…','')); for (const choice of property.enum) input.append(new Option(String(choice),JSON.stringify(choice))); input.dataset.enum = 'true'; }
    else if (type === 'boolean') { input = document.createElement('select'); input.append(new Option(required ? 'Select…' : 'Use service default',''),new Option('Yes','true'),new Option('No','false')); }
    else if (type === 'number' || type === 'integer') { input = document.createElement('input'); input.type = 'number'; input.step = type === 'integer' ? '1' : 'any'; if (property.minimum !== undefined) input.min = property.minimum; if (property.maximum !== undefined) input.max = property.maximum; }
    else { input = document.createElement('textarea'); input.rows = /prompt|description|text/.test(name) ? 4 : 2; if (type !== 'string') input.placeholder = 'Enter JSON'; }
    input.id = id; input.dataset.field = name; input.dataset.type = type; input.required = required;
    if (property.default !== undefined) input.value = property.enum || type !== 'string' ? JSON.stringify(property.default) : property.default;
    $('tool-fields').append(label,input); if (property.description) $('tool-fields').append(element('small',property.description));
  }
}
$('use-draft').onclick = () => {
  const prompt = Array.from($('tool-fields').querySelectorAll('[data-field]')).find(el => ['prompt','text','description'].includes(el.dataset.field));
  if (prompt) { prompt.value = $('draft-output').value || $('creative-brief').value; prompt.focus(); }
  else $('tool-status').textContent = 'This tool has no simple prompt field. Fill the fields its service requires.';
};
$('tool-form').onsubmit = async event => {
  event.preventDefault(); if (!selectedTool) return;
  const connectionId = $('tool-connection').value, tool = selectedTool.name;
  try {
    const args = JSON.parse($('tool-extra').value || '{}'); if (!args || Array.isArray(args) || typeof args !== 'object') throw new Error('Additional arguments must be a JSON object.');
    for (const input of $('tool-fields').querySelectorAll('[data-field]')) {
      if (!input.value.trim()) continue;
      args[input.dataset.field] = input.dataset.enum || input.dataset.type !== 'string' ? JSON.parse(input.value) : input.value;
    }
    $('run-tool').disabled = true; $('tool-status').textContent = `Running ${tool}…`; $('tool-result').replaceChildren();
    const data = await api('/api/mcp/call',{id:connectionId,tool,arguments:args},700000);
    $('tool-status').textContent = data.result.isError ? 'The service reported an error. See its response below.' : 'Tool response received. Some media jobs return an ID to check with a status tool.';
    renderResult(data.result);
    if(data.media_item) $('tool-result').append(mediaCard(data.media_item));
  } catch (error) { $('tool-status').textContent = error instanceof SyntaxError ? 'Check the JSON in complex fields and additional arguments.' : error.message; }
  finally { $('run-tool').disabled = !selectedTool; }
};
function renderResult(result) {
  for (const content of result.content || []) {
    if (content.type === 'text') {
      $('tool-result').append(element('pre',content.text));
      for(const url of new Set((content.text||'').match(/https:\/\/[^\s<>"')]+/g)||[])){
        const link=element('a','Open result ↗','asset-link');link.href=url;link.target='_blank';link.rel='noopener noreferrer';$('tool-result').append(link);
      }
    }
    else if (content.type === 'image' && ['image/png','image/jpeg','image/webp'].includes(content.mimeType) && typeof content.data === 'string') {
      const image = document.createElement('img'); image.alt = 'Connected tool image result'; image.src = `data:${content.mimeType};base64,${content.data}`; $('tool-result').append(image);
    } else if (content.type === 'resource_link' && /^https?:\/\//i.test(content.uri || '')) {
      const link = element('a',content.title || content.name || 'Open generated asset','asset-link'); link.href = content.uri; link.target = '_blank'; link.rel = 'noopener noreferrer'; $('tool-result').append(link);
    }
  }
  const details = element('details'); details.append(element('summary','Full tool response'),element('pre',JSON.stringify(result,null,2))); $('tool-result').append(details);
}
renderLibrary();
if (new URLSearchParams(location.search).get('view') === 'connections') showView('connections');
