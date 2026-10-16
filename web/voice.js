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
function speechChunks(text){
  const clean=text.replace(/```[\s\S]*?```/g,' Code example omitted from speech. ').replace(/https?:\/\/\S+/g,' link ').replace(/[*#`_]/g,'').trim();
  return clean.match(/[\s\S]{1,350}(?:[.!?]\s+|\s+|$)|[\s\S]{1,350}/g)||[];
}
async function say(text,preview=false,configuration=voiceConfig){
  if(!preview&&!$('speak').checked)return;
  stopVoice();const generation=voiceGeneration;
  if(configuration.engine==='browser'){if(preview){const enabled=$('speak').checked;$('speak').checked=true;browserSay(text);$('speak').checked=enabled;}else browserSay(text);return;}
  if(configuration.engine==='qwen'?!voiceCatalog?.qwen?.available:!voiceAvailable){$('voice-note').textContent='This voice engine is unavailable. Open Voice to choose another engine.';return;}
  try{
    await connectVoiceMeter();
    if(!busy&&!listening)activity('PREPARING VOICE','thinking');
    for(const chunk of speechChunks(text)){
      if(generation!==voiceGeneration)return;
      voiceAbort=new AbortController();
      const response=await fetch('/api/speech',{method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Token':token},body:JSON.stringify({engine:configuration.engine,text:chunk,voice:configuration.voice,style:configuration.style||'',speed:Number(configuration.speed)}),signal:AbortSignal.any([voiceAbort.signal,AbortSignal.timeout(configuration.engine==='qwen'?320000:60000)])});
      if(!response.ok){const error=await response.json();throw Error(error.error||'Speech failed.');}
      const blob=await response.blob();if(generation!==voiceGeneration)return;
      const player=$('voice-player');if(voiceObjectURL)URL.revokeObjectURL(voiceObjectURL);voiceObjectURL=URL.createObjectURL(blob);
      player.src=voiceObjectURL;player.hidden=!preview;
      await new Promise((resolve,reject)=>{
        player.onended=resolve;player.onerror=()=>reject(Error('Audio playback failed.'));
        player.onpause=()=>{if(generation!==voiceGeneration)resolve();};
        player.play().then(()=>{if(!busy&&!listening)activity('SPEAKING','speaking');}).catch(()=>reject(Error('Playback was blocked. Open Voice and press Preview voice to enable audio.')));
      });
    }
    if(preview)$('voice-status').textContent='Preview complete. Save voice to use it for replies.';
  }catch(error){if(error.name!=='AbortError'){ $('voice-status').textContent=error.message;$('voice-note').textContent=error.message; }}
  finally{if(generation===voiceGeneration&&!busy&&!listening)activity('SYSTEM READY');}
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
