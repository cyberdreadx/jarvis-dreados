"""Optional Qwen3-TTS runner, isolated from Kokoro's dependencies."""
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PYTHON=ROOT/('.venv-qwen/Scripts/python.exe' if os.name=='nt' else '.venv-qwen/bin/python')
MODEL=ROOT/'data/qwen-tts'
CHOICES={'Ryan':'Ryan · English male','Aiden':'Aiden · American male','Vivian':'Vivian · bright female','Serena':'Serena · gentle female'}
LOCK=threading.Lock()
def status():
    return {'available':PYTHON.exists() and (MODEL/'ready.json').exists(),'voices':CHOICES,'default':'Ryan','device':'CPU','note':'Qwen3-TTS 1.7B · CPU preview may take several minutes. Kokoro is faster.'}
def synthesize(data):
    text=data.get('text','');speaker=data.get('voice','Ryan');style=data.get('style','')
    if not isinstance(text,str) or not 1<=len(text.strip())<=500: raise ValueError('Qwen speech supports up to 500 characters per chunk.')
    if speaker not in CHOICES: raise ValueError('Choose a supported Qwen voice.')
    if not isinstance(style,str) or len(style)>500: raise ValueError('Voice style must be under 500 characters.')
    if not status()['available']: raise ValueError('Qwen3-TTS setup is not complete. Choose Kokoro for now.')
    if not LOCK.acquire(blocking=False): raise ValueError('Qwen TTS is still generating. Please wait.')
    try:
        with tempfile.TemporaryDirectory(prefix='dreados-qwen-') as folder:
            output=Path(folder)/'speech.wav'
            try:
                result=subprocess.run([str(PYTHON),str(ROOT/'qwen_voice_worker.py'),str(output)],input=json.dumps({'text':text,'voice':speaker,'style':style}),text=True,encoding='utf-8',capture_output=True,timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),cwd=ROOT)
            except subprocess.TimeoutExpired: raise ValueError('Qwen CPU generation took too long. Try a shorter preview or use Kokoro.') from None
            if result.returncode or not output.exists():
                (ROOT/'data/qwen-error.log').write_text(result.stderr[-12000:],encoding='utf-8')
                raise ValueError('Qwen speech failed. Kokoro remains available; see data/qwen-error.log for details.')
            return output.read_bytes()
    finally: LOCK.release()
