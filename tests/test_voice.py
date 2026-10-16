import unittest
from unittest.mock import patch
import voice

class VoiceValidation(unittest.TestCase):
    def test_bad_inputs_before_loading_model(self):
        for payload in ({}, {'text':'x','voice':'../../file'}, {'text':'x','speed':0}, {'text':'x','speed':float('nan')}, {'text':'x'*1801}):
            with self.assertRaises(ValueError):voice.synthesize(payload)
    def test_missing_runtime_is_actionable(self):
        with patch('voice.status',return_value={'available':False}):
            with self.assertRaisesRegex(ValueError,'Start-JARVIS'):voice.synthesize({'text':'Hello'})
