"""Isolated Qwen TTS worker. JSON on stdin; WAV output path supplied by parent."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.environ['HF_HOME']=str(ROOT/'data/qwen-cache')
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'

def main():
    import torch
    import soundfile as sf
    from qwen_tts import Qwen3TTSModel
    torch.set_num_threads(8)
    data=json.load(sys.stdin)
    model=Qwen3TTSModel.from_pretrained(str(ROOT/'data/qwen-tts'),device_map='cpu',dtype=torch.float32,attn_implementation='sdpa')
    wavs,rate=model.generate_custom_voice(text=data['text'],language='English',speaker=data['voice'],instruct=data.get('style','Speak naturally, warmly, and clearly.'),max_new_tokens=1024)
    sf.write(sys.argv[1],wavs[0],rate,subtype='PCM_16')

if __name__=='__main__': main()
