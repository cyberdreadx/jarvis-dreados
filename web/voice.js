let voiceContext=null, voiceAnalyser=null, voiceWave=null, voiceSpectrum=null;
async function connectVoiceMeter(){
  const AudioContextType=window.AudioContext||window.webkitAudioContext;
  if(!AudioContextType)return;
  if(!voiceContext){
    voiceContext=new AudioContextType();
    const source=voiceContext.createMediaElementSource($('voice-player'));
    voiceAnalyser=voiceContext.createAnalyser();voiceAnalyser.fftSize=512;voiceAnalyser.smoothingTimeConstant=.55;
    source.connect(voiceAnalyser);voiceAnalyser.connect(voiceContext.destination);
    voiceWave=new Float32Array(voiceAnalyser.fftSize);voiceSpectrum=new Uint8Array(voiceAnalyser.frequencyBinCount);
  }
  if(voiceContext.state==='suspended')await voiceContext.resume();
}
function getVoiceEnergy(){
  const player=$('voice-player');
  if(!voiceAnalyser||player.paused||player.ended)return {level:0,bands:null};
  voiceAnalyser.getFloatTimeDomainData(voiceWave);voiceAnalyser.getByteFrequencyData(voiceSpectrum);
  let sum=0;for(const sample of voiceWave)sum+=sample*sample;
  return {level:Math.min(1,Math.sqrt(sum/voiceWave.length)*5),bands:voiceSpectrum};
}
let voiceConfig={engine:'kokoro',voice:'bm_george',speed:1}, voiceAbort=null, voiceGeneration=0, voiceObjectURL=null, voiceAvailable=false, voiceCatalog=null;
try{voiceConfig={...voiceConfig,...JSON.parse(localStorage.getItem('jarvis-voice')||'{}')};}catch{}
function stopVoice(){
  voiceGeneration++;voiceAbort?.abort();voiceAbort=null;speech?.cancel();
  const audio=$('voice-player');audio.pause();audio.removeAttribute('src');audio.load();
  if(voiceObjectURL){URL.revokeObjectURL(voiceObjectURL);voiceObjectURL=null;}
  if(!busy&&!listening)activity('SYSTEM READY');
}
function speechSegments(text){
  let clean='';const sourceEnds=[];
  const append=(value,start,end=null)=>{
    for(let index=0;index<value.length;index++){
      clean+=value[index];
      sourceEnds.push(end===null?start+index+1:index===value.length-1?end:start);
    }
  };
  // Keep the original positions when replacing code/URLs or stripping Markdown.
  const omitted=/```[\s\S]*?```|https?:\/\/\S+|[*#`_]/g;
  let cursor=0;
  for(const match of text.matchAll(omitted)){
    append(text.slice(cursor,match.index),cursor);
    if(match[0].startsWith('```'))append(' Code example omitted from speech. ',match.index,match.index+match[0].length);
    else if(match[0].startsWith('http'))append(' link ',match.index,match.index+match[0].length);
    cursor=match.index+match[0].length;
  }
  append(text.slice(cursor),cursor);
  const start=clean.length-clean.trimStart().length,end=clean.trimEnd().length;
  clean=clean.slice(start,end);const positions=sourceEnds.slice(start,end);
  const chunks=[];let offset=0;
  for(const chunk of clean.match(/[\s\S]{1,350}(?:[.!?]\s+|\s+|$)|[\s\S]{1,350}/g)||[]){
    chunks.push({text:chunk,sourceEnds:positions.slice(offset,offset+chunk.length)});offset+=chunk.length;
  }
  return chunks;
}
function speechChunks(text){return speechSegments(text).map(chunk=>chunk.text);}
function waitForVoice(promise,signal){
  return new Promise((resolve,reject)=>{
    const abort=()=>reject(new DOMException('Voice stopped.','AbortError'));
    if(signal.aborted)abort();else signal.addEventListener('abort',abort,{once:true});
    Promise.resolve(promise).then(resolve,reject).finally(()=>signal.removeEventListener('abort',abort));
  });
}
// onProgress(sourceEnd) uses character positions in the original reply.
async function say(text,preview=false,configuration=voiceConfig,onProgress=null){
  if(!preview&&!$('speak').checked)return;
  stopVoice();const generation=voiceGeneration;
  const controller=new AbortController();voiceAbort=controller;const signal=controller.signal;
  try{
    if(configuration.engine==='browser'){await browserSay(text,onProgress,signal,preview);return;}
    if(configuration.engine==='qwen'?!voiceCatalog?.qwen?.available:!voiceAvailable){$('voice-note').textContent='This voice engine is unavailable. Open Voice to choose another engine.';return;}
    await waitForVoice(connectVoiceMeter(),signal);
    if(generation!==voiceGeneration)return;
    if(!busy&&!listening)activity('PREPARING VOICE','thinking');
    const chunks=speechSegments(text);
    const synthesize=async chunk=>{
      const response=await fetch('/api/speech',{method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Token':token},body:JSON.stringify({engine:configuration.engine,text:chunk.text,voice:configuration.voice,style:configuration.style||'',speed:Number(configuration.speed)}),signal:AbortSignal.any([signal,AbortSignal.timeout(configuration.engine==='qwen'?320000:60000)])});
      if(!response.ok){const error=await response.json();throw Error(error.error||'Speech failed.');}
      return response.blob();
    };
    // Generate the next chunk while the current one plays, so there is no silent gap between chunks.
    let upcoming=chunks.length?synthesize(chunks[0]):null;
    for(const [position,chunk] of chunks.entries()){
      if(generation!==voiceGeneration)return;
      const blob=await waitForVoice(upcoming,signal);if(generation!==voiceGeneration)return;
      upcoming=position+1<chunks.length?synthesize(chunks[position+1]):null;
      upcoming?.catch(()=>{}); // Awaited on the next pass; this only silences an early rejection.
      const player=$('voice-player');if(voiceObjectURL)URL.revokeObjectURL(voiceObjectURL);voiceObjectURL=URL.createObjectURL(blob);
      player.src=voiceObjectURL;player.hidden=!preview;
      await new Promise((resolve,reject)=>{
        let settled=false,frame=null;
        const cleanup=()=>{
          if(frame!==null)cancelAnimationFrame(frame);
          player.removeEventListener('ended',ended);player.removeEventListener('error',failed);
          player.removeEventListener('playing',playing);signal.removeEventListener('abort',stopped);
        };
        const finish=error=>{if(settled)return;settled=true;cleanup();if(error)reject(error);else resolve();};
        const ended=()=>finish(),failed=()=>finish(Error('Audio playback failed.')),stopped=()=>finish();
        const tick=()=>{
          frame=null;
          if(settled||generation!==voiceGeneration||player.ended||player.paused)return;
          if(onProgress&&Number.isFinite(player.duration)&&player.duration>0){
            const fraction=Math.max(0,Math.min(1,player.currentTime/player.duration));
            const index=Math.min(chunk.text.length-1,Math.floor(fraction*chunk.text.length));
            onProgress(chunk.sourceEnds[index]);
          }
          frame=requestAnimationFrame(tick);
        };
        const playing=()=>{if(frame===null)tick();};
        player.addEventListener('ended',ended);player.addEventListener('error',failed);
        player.addEventListener('playing',playing);signal.addEventListener('abort',stopped,{once:true});
        player.play().then(()=>{
          if(settled||generation!==voiceGeneration)return;
          if(!busy&&!listening)activity('SPEAKING','speaking');
          playing();
        }).catch(()=>finish(Error('Playback was blocked. Open Voice and press Preview voice to enable audio.')));
      });
      if(generation!==voiceGeneration)return;
      onProgress?.(chunk.sourceEnds.at(-1));
    }
    if(preview)$('voice-status').textContent='Preview complete. Save voice to use it for replies.';
  }catch(error){if(generation===voiceGeneration&&error.name!=='AbortError'){ $('voice-status').textContent=error.message;$('voice-note').textContent=error.message; }}
  finally{
    // Playback can fail while the next chunk is still being fetched.
    controller.abort();
    if(voiceAbort===controller)voiceAbort=null;
    if(generation===voiceGeneration&&!busy&&!listening)activity('SYSTEM READY');
  }
}
async function loadVoices(){
  const response=await fetch('/api/voices');const data=await response.json();voiceAvailable=data.available;
  voiceCatalog=data;
  $('voice-engine').value=voiceConfig.engine;
  updateVoiceChoices(voiceConfig.voice);$('qwen-style').value=voiceConfig.style||'';
  $('voice-speed').value=voiceConfig.speed;$('speed-value').value=Number(voiceConfig.speed).toFixed(2)+'×';
}
$('voice-settings').onclick=()=>{$('voice-dialog').showModal();loadVoices().catch(()=>{$('voice-status').textContent='Could not reach the voice engine.';});};
$('close-voice').onclick=()=>{$('voice-dialog').close();};
$('voice-dialog').addEventListener('close',()=>{stopVoice();});
$('voice-speed').oninput=()=>{$('speed-value').value=Number($('voice-speed').value).toFixed(2)+'×';};
function selectedVoice(){return {style:$('qwen-style').value,engine:$('voice-engine').value,voice:$('kokoro-voice').value,speed:Number($('voice-speed').value)};}
$('preview-voice').onclick=async()=>{
  const button=$('preview-voice');
  if(button.disabled)return;
  button.disabled=true;$('voice-status').textContent='Generating preview…';
  try{await say($('voice-sample').value,true,selectedVoice());}
  finally{button.disabled=false;}
};
$('save-voice').onclick=()=>{voiceConfig=selectedVoice();try{localStorage.setItem('jarvis-voice',JSON.stringify(voiceConfig));$('voice-status').textContent='Voice saved for spoken replies.';}catch{$('voice-status').textContent='Voice selected for this tab.';}};
loadVoices().catch(()=>{});

function updateVoiceChoices(preferred){
 const qwen=$('voice-engine').value==='qwen',catalog=qwen?voiceCatalog?.qwen:voiceCatalog;
 $('kokoro-voice').replaceChildren();
 for(const [id,name] of Object.entries(catalog?.voices||{}))$('kokoro-voice').append(new Option(name,id));
 if(preferred&&catalog?.voices?.[preferred])$('kokoro-voice').value=preferred;
 $('qwen-style-field').hidden=!qwen;$('voice-speed').disabled=qwen||$('voice-engine').value==='browser';
 $('voice-status').textContent=qwen?(catalog?.available?catalog.note:'Qwen setup is not complete. Kokoro is available.'):voiceAvailable?'Kokoro ready · local CPU':'Kokoro unavailable.';
}
$('voice-engine').onchange=()=>updateVoiceChoices();
