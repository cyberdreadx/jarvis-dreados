import unittest
import speech_input
class SpeechInputTests(unittest.TestCase):
    def test_invalid_requests(self):
        for data in (None,{}, {'audio':'??'}, {'audio':'YQ==','language':'xx'}, {'audio':'a'*8000001}):
            with self.subTest(data=str(data)[:50]), self.assertRaises(ValueError): speech_input.transcribe(data)
    def test_invalid_audio_releases_lock(self):
        with self.assertRaises(ValueError):speech_input.transcribe({'audio':'YQ=='})
        self.assertTrue(speech_input._lock.acquire(False))
        speech_input._lock.release()

    def test_duration_limit(self):
        import io, wave, base64
        out=io.BytesIO()
        with wave.open(out,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
            wav.writeframes(b'\0'*(16000*66*2))
        with self.assertRaisesRegex(ValueError,'under 60'):
            speech_input.transcribe({'audio':base64.b64encode(out.getvalue()).decode()})
