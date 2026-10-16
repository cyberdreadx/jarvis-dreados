"""Bounded local microphone transcription; recordings are never persisted."""
import base64
import binascii
import io
import threading
from pathlib import Path

MODEL = Path(__file__).resolve().parent / 'data/whisper-turbo'
_lock = threading.Lock()
_model = None
_parakeet = None
_device = 'cpu'

def transcribe(data):
    global _model, _device, _parakeet
    if not isinstance(data, dict): raise ValueError('Invalid recording.')
    encoded = data.get('audio', '')
    engine = data.get('engine', 'parakeet')
    if engine not in ('parakeet', 'whisper'): raise ValueError('Choose Parakeet or Whisper.')
    language = data.get('language', 'auto')
    if language not in ('auto', 'en', 'es'): raise ValueError('Choose Auto, English, or Spanish.')
    if not isinstance(encoded, str) or not 1 <= len(encoded) <= 8000000: raise ValueError('Recording is too large. Record up to 60 seconds.')
    try: raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error): raise ValueError('Invalid recording encoding.')
    if not _lock.acquire(blocking=False): raise ValueError('Another recording is being transcribed. Try again shortly.')
    try:
        import numpy as np
        import av
        from faster_whisper import WhisperModel
        # Decode incrementally with a hard duration cap before allocating inference audio.
        chunks = []
        count = 0
        try:
            with av.open(io.BytesIO(raw)) as container:
                resampler = av.AudioResampler(format='fltp', layout='mono', rate=16000)
                for frame in container.decode(audio=0):
                    for sample in resampler.resample(frame):
                        count += sample.samples
                        if count > 16000 * 65: raise ValueError('Recordings must be under 60 seconds.')
                        chunks.append(sample.to_ndarray().reshape(-1))
        except ValueError: raise
        except Exception: raise ValueError('Could not read this audio recording.')
        if not chunks: raise ValueError('No audio was recorded.')
        audio = np.concatenate(chunks)
        if engine == 'parakeet':
            if _parakeet is None:
                import onnx_asr
                import onnxruntime as ort
                options = ort.SessionOptions()
                options.intra_op_num_threads = 6
                options.inter_op_num_threads = 1
                _parakeet = onnx_asr.load_model('nemo-parakeet-tdt-0.6b-v3', path=MODEL.parent/'parakeet', quantization='int8', sess_options=options, providers=['CPUExecutionProvider'])
            # Skip silent input rather than asking the decoder to invent words.
            if float(np.sqrt(np.mean(audio ** 2))) < .001:
                return {'text':'', 'language':'auto', 'device':'cpu', 'engine':engine}
            return {'text':_parakeet.recognize(audio, sample_rate=16000).strip(), 'language':'auto', 'device':'cpu', 'engine':engine}
        if _model is None:
            if not (MODEL / 'model.bin').is_file(): raise ValueError('Whisper model is not installed yet.')
            _model = WhisperModel(str(MODEL), device='cpu', compute_type='int8', cpu_threads=6, num_workers=1)
        segments, info = _model.transcribe(audio, language=None if language == 'auto' else language,
                                          beam_size=3, vad_filter=True, condition_on_previous_text=False)
        text = ' '.join(s.text.strip() for s in segments).strip()
        return {'text': text, 'language': info.language, 'device': _device, 'engine':engine}
    finally: _lock.release()
