import unittest
from unittest.mock import patch

import chat_tools as t

CATALOG = [{'id': 'gltch', 'name': 'GLTCH Runner', 'status': 'connected',
            'tools': [{'name': 'generate_image', 'description': 'Make an image',
                       'inputSchema': {'type': 'object', 'required': ['prompt'], 'properties': {'prompt': {'type': 'string'}}}}]}]
GOOD = '{"connection_id":"gltch","tool":"generate_image","arguments":{"prompt":"a glowing AI"}}'


class ExtractTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(t.extract_choice(GOOD)['tool'], 'generate_image')

    def test_json_wrapped_in_prose_fences_and_thinking(self):
        for raw in ('Sure! Here is the tool call:\n```json\n' + GOOD + '\n```\nLet me know.',
                    '<think>The user wants an image {maybe}…</think>\n' + GOOD,
                    'I will use {"note": 1} then ' + GOOD):
            with self.subTest(raw=raw[:30]):
                self.assertEqual(t.extract_choice(raw)['arguments']['prompt'], 'a glowing AI')

    def test_clarification_and_garbage(self):
        self.assertEqual(t.extract_choice('{"clarification":"Which model?"}')['clarification'], 'Which model?')
        self.assertIsNone(t.extract_choice('I cannot do that.'))
        self.assertIsNone(t.extract_choice(None))


class ProposeTests(unittest.TestCase):
    def propose(self, replies):
        with patch.object(t.mcp_client, 'public_connections', return_value=CATALOG), \
             patch.object(t.providers, 'reply', side_effect=replies) as reply:
            return t.propose('draw yourself', [], 'local'), reply

    def test_prose_wrapped_proposal_is_accepted(self):
        (proposal, note), reply = self.propose(['Okay, here you go: ' + GOOD])
        self.assertEqual(proposal['tool'], 'generate_image')
        self.assertEqual(reply.call_count, 1)

    def test_retries_once_with_json_reminder(self):
        (proposal, _), reply = self.propose(['I would love to draw myself as a robot!', GOOD])
        self.assertEqual(proposal['tool'], 'generate_image')
        self.assertIn('only the JSON object', reply.call_args_list[1].args[0])

    def test_gives_a_useful_error_after_retry(self):
        with self.assertRaisesRegex(ValueError, 'answered in text instead of choosing a tool.*robot'):
            self.propose(['I would love to draw myself as a robot!', 'Still a robot, honestly.'])


if __name__ == '__main__':
    unittest.main()
