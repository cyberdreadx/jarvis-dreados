"""Local Kokoro synthesis. Audio is returned in memory, never sent to a service."""
import qwen_voice
import importlib.util
import io
import math
import threading
from pathlib import Path
ROOT=Path(__file__).resolve().parent
MODEL=ROOT/'data/kokoro/kokoro-v1.0.onnx'
VOICES=ROOT/'data/kokoro/voices-v1.0.bin'
CHOICES={'bm_george':'George · British male','bm_lewis':'Lewis · British male','bf_emma':'Emma · British female','af_heart':'Heart · American female','af_bella':'Bella · American female','am_michael':'Michael · American male'}
_engine=None
_lock=threading.Lock()

def status():
    return {'available':MODEL.is_file() and VOICES.is_file() and importlib.util.find_spec('kokoro_onnx') is not None,'voices':CHOICES,'default':'bm_george','qwen':qwen_voice.status()}

def synthesize(data):
    global _engine
    if not isinstance(data,dict):raise ValueError('Invalid speech request.')
    if data.get('engine')=='qwen': return qwen_voice.synthesize(data)
    text=data.get('text','');voice=data.get('voice','bm_george');speed=data.get('speed',1.0)
    if not isinstance(text,str) or not 1<=len(text.strip())<=1800:raise ValueError('Speech text must be between 1 and 1,800 characters.')
    if voice not in CHOICES:raise ValueError('Choose a supported Kokoro voice.')
    if not isinstance(speed,(int,float)) or not math.isfinite(speed) or not .7<=speed<=1.3:raise ValueError('Choose a speech speed between 0.7 and 1.3.')
    if not status()['available']:raise ValueError('Kokoro is not ready. Start JARVIS with Start-JARVIS.cmd after installing the voice model.')
    if not _lock.acquire(blocking=False):raise ValueError('Kokoro is finishing another request. Try again shortly.')
    try:
        import soundfile as sf
        if _engine is None:
            import onnxruntime as rt
            from kokoro_onnx import Kokoro
            options=rt.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            session=rt.InferenceSession(str(MODEL),sess_options=options,providers=['CPUExecutionProvider'])
            _engine=Kokoro.from_session(session,str(VOICES))
            # kokoro-onnx 0.4.7 emits integer speed for newer input_ids exports;
            # this v1.0 model declares speed as float. Follow the model metadata.
            class TypedSession:
                def get_inputs(self): return session.get_inputs()
                def run(self, outputs, inputs):
                    import numpy as np
                    for spec in session.get_inputs():
                        if spec.name=='speed' and spec.type=='tensor(float)':
                            inputs['speed']=np.full(np.asarray(inputs['speed']).shape,self.speed,dtype=np.float32)
                    return session.run(outputs,inputs)
            _engine.sess=TypedSession()
        _engine.sess.speed=float(speed)
        samples,rate=_engine.create(text.strip(),voice=voice,speed=float(speed),lang='en-gb' if voice.startswith('b') else 'en-us')
        output=io.BytesIO();sf.write(output,samples,rate,format='WAV',subtype='PCM_16')
        return output.getvalue()
    finally:_lock.release()
