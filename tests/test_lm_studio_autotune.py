import unittest
from unittest.mock import patch
import lm_studio as lm

GPU = {'available': True, 'gpus': [{'name': 'RTX 4090', 'total_mb': 24564, 'used_mb': 0, 'free_mb': 24564}]}
MODEL = {'key': 'qwen', 'type': 'llm', 'max_context_length': 262144, 'loaded_instances': [{'id': 'qwen-1'}],
         'capabilities': {'reasoning': {'allowed_options': ['off', 'on'], 'default': 'on'}}}


def fake_estimate(base=19.48, per_32k=4.1):
    # Shaped like the real Qwen3.8 27B readings: 32K -> 23.58 GiB, 64K -> 27.68 GiB.
    calls = []
    def estimate(key, context):
        calls.append(context)
        return base + per_32k * context / 32768
    return estimate, calls


class AutoTuneTests(unittest.TestCase):
    def tune(self, estimate, model=MODEL, gpu=GPU):
        with patch.object(lm, 'call', return_value={'models': [model]}), \
             patch.object(lm, 'gpu_memory', return_value=gpu), patch.object(lm, 'estimate_gpu_gib', side_effect=estimate):
            return lm.recommend('qwen')

    def test_picks_largest_context_that_fits_the_gpu(self):
        estimate, calls = fake_estimate()
        result = self.tune(estimate)
        self.assertEqual(result['settings'], {'context_length': 32768, 'flash_attention': True, 'offload_kv_cache_to_gpu': True})
        self.assertTrue(result['fits_gpu'])
        self.assertLess(len(calls), 12)  # binary search, not 64 estimates

    def test_bigger_card_gets_bigger_context_capped_at_model_max(self):
        estimate, _ = fake_estimate()
        big = {'available': True, 'gpus': [{'name': 'H100', 'total_mb': 81920, 'used_mb': 0, 'free_mb': 81920}]}
        self.assertEqual(self.tune(estimate, gpu=big)['settings']['context_length'], 262144)

    def test_model_too_big_for_gpu_is_flagged(self):
        estimate, _ = fake_estimate(base=30)
        result = self.tune(estimate)
        self.assertFalse(result['fits_gpu'])
        self.assertIn('system RAM', result['note'])

    def test_falls_back_to_32k_without_estimates_or_gpu_info(self):
        self.assertEqual(self.tune(lambda k, c: None)['settings']['context_length'], 32768)
        self.assertEqual(self.tune(fake_estimate()[0], gpu={'available': False})['settings']['context_length'], 32768)

    def test_parses_lms_estimate_output(self):
        out = type('R', (), {'stdout': 'Context Length: 32,768\nEstimated GPU Memory:   23.58 GiB\n', 'stderr': ''})()
        with patch.object(lm, 'LMS', type('P', (), {'exists': lambda self: True, '__str__': lambda self: 'lms'})()), \
             patch.object(lm.subprocess, 'run', return_value=out):
            self.assertAlmostEqual(lm.estimate_gpu_gib('qwen', 32768), 23.58)


class ReasoningTests(unittest.TestCase):
    def effort(self, options):
        model = {**MODEL, 'capabilities': {'reasoning': {'allowed_options': options}} if options is not None else {}}
        with patch.object(lm, 'call', return_value={'models': [model]}):
            return lm.reasoning_effort('qwen-1')

    def test_on_off_models_keep_their_default_instead_of_an_unsupported_level(self):
        self.assertIsNone(self.effort(['off', 'on']))

    def test_graded_models_get_low(self):
        self.assertEqual(self.effort(['off', 'low', 'medium', 'high']), 'low')

    def test_models_without_reasoning_get_nothing(self):
        self.assertIsNone(self.effort(None))


if __name__ == '__main__':
    unittest.main()
