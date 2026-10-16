// Local speech capture. Opening settings never starts recording without a click.
(() => {
  let stream, recorder, context, timer, chunks=[], cancelled=false, pending=false, starting=false;
  const note = text => {$('voice-note').textContent=text;};
  const supported=!!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
  function release(){clearInterval(timer);stream?.getTracks().forEach(t=>t.stop());stream=null;context?.close().catch(()=>{});context=null;$('mic-level').hidden=true;$('mic-level').value=0;listening=false;$('mic').textContent='◉ Talk to DreadOS AI';}
  async function devices(){const items=await navigator.mediaDevices.enumerateDevices();const current=$('mic-device').value||localStorage.getItem('mic-device')||'';$('mic-device').replaceChildren(new Option('System default',''));items.filter(d=>d.kind==='audioinput').forEach((d,i)=>$('mic-device').add(new Option(d.label||`Microphone ${i+1}`,d.deviceId)));$('mic-device').value=current;}
  function stop(discard=false){cancelled=discard;if(recorder?.state==='recording'){pending=!discard;recorder.stop();}release();}
  async function upload(blob){
    pending=true;setBusy(true);activity('TRANSCRIBING','transcribing');note('Transcribing locally…');
    try{
      const audio=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob);});
      const response=await fetch('/api/transcribe',{method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Token':token},body:JSON.stringify({audio,engine:$('mic-engine').value,language:$('mic-language').value}),signal:AbortSignal.timeout(180000)});
      const data=await response.json();if(!response.ok)throw Error(data.error||'Transcription failed.');
      if(!data.text){note('No speech detected. Try again closer to the microphone.');return;}
      $('input').value=[$('input').value.trim(),data.text].filter(Boolean).join(' ');$('input').focus();
      note(`Transcribed locally ${data.engine==='parakeet'?'with Parakeet':`with Whisper (${data.language})`}. Review your message, then press Send.`);
      if($('mic-auto').checked){setBusy(false);await send($('input').value);}
    }catch(error){note(error.name==='TimeoutError'?'Transcription took too long. Try a shorter recording.':error.message);}
    finally{pending=false;setBusy(false);if(!busy)activity('SYSTEM READY');}
  }
  recognition=supported?{abort:()=>stop(true),stop:()=>stop()}:null;
  $('mic').onclick=async()=>{
    if(listening){stop();return;}if(busy||pending||starting)return;
    starting=true;stopAssistantVoice();cancelled=false;
    try{
      stream=await navigator.mediaDevices.getUserMedia({audio:{deviceId:$('mic-device').value?{exact:$('mic-device').value}:undefined,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
      await devices();context=new AudioContext();await context.resume();const analyser=context.createAnalyser();analyser.fftSize=1024;context.createMediaStreamSource(stream).connect(analyser);
      const type=['audio/webm;codecs=opus','audio/webm','audio/mp4'].find(t=>MediaRecorder.isTypeSupported(t));recorder=new MediaRecorder(stream,type?{mimeType:type}:{});chunks=[];
      recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};recorder.onstop=()=>{pending=false;if(!cancelled)upload(new Blob(chunks,{type:recorder.mimeType}));};recorder.onerror=()=>{stop(true);note('Recording failed. Check your microphone.');};
      recorder.start();listening=true;$('mic').textContent='■ Finish recording';$('mic-level').hidden=false;activity('LISTENING','listening');note('Listening… click Finish recording when done.');
      const samples=new Float32Array(analyser.fftSize),began=Date.now();let lastSpeech=began,heard=false;
      timer=setInterval(()=>{analyser.getFloatTimeDomainData(samples);const rms=Math.sqrt(samples.reduce((sum,v)=>sum+v*v,0)/samples.length);$('mic-level').value=Math.min(1,rms*8);if(rms>.015){heard=true;lastSpeech=Date.now();}if(Date.now()-began>=60000||($('mic-silence').checked&&heard&&Date.now()-lastSpeech>2000))stop();},100);
    }catch(error){release();note(error.name==='NotAllowedError'?'Allow microphone access in your browser to talk.':`Microphone unavailable: ${error.message}`);}
    finally{starting=false;}
  };
  $('mic-refresh').onclick=async()=>{try{const permission=await navigator.mediaDevices.getUserMedia({audio:true});permission.getTracks().forEach(t=>t.stop());await devices();note('Microphones updated. Choose your input, then click Talk.');}catch{note('Allow microphone access to list your devices.');}};
  $('mic-device').addEventListener('change',()=>localStorage.setItem('mic-device',$('mic-device').value));
  for(const id of ['mic-engine','mic-language','mic-auto','mic-silence']){const el=$(id),saved=localStorage.getItem(id);if(saved!==null){if(el.type==='checkbox')el.checked=saved==='true';else el.value=saved;}el.addEventListener('change',()=>localStorage.setItem(id,el.type==='checkbox'?String(el.checked):el.value));}
  function engineChanged(){$('mic-language').disabled=$('mic-engine').value==='parakeet';$('mic-language').title=$('mic-engine').value==='parakeet'?'Parakeet detects language automatically.':'';}
  $('mic-engine').addEventListener('change',engineChanged);engineChanged();
  window.addEventListener('pagehide',()=>stop(true));
  if(supported)devices().catch(()=>{});else note('Microphone recording is unavailable in this browser. Use Chrome or Edge.');
  setBusy(busy);
})();
