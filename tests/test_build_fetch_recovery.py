import copy
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import opencode_bridge as bridge


def user(text='Build the game', **info):
    return {'info': {'role': 'user', 'sessionID': 'ses_test', **info},
            'parts': [{'type': 'text', 'text': text}]}


def fetch(error='DREADOS_WEBFETCH_RETRY_BLOCKED: already failed', status='error', tool='webfetch'):
    return {'info': {'role': 'assistant', 'sessionID': 'ses_test'},
            'parts': [{'type': 'tool', 'tool': tool, 'state': {'status': status, 'error': error}}]}


class FetchLoopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'demo').mkdir()
        self.messages = [user(), fetch(), fetch()]
        self.status = 'busy'
        self.calls = []
        self.pending = [{'id': 'pending', 'sessionID': 'ses_test', 'permission': 'webfetch'}]
        self.grants = {(str((self.root / 'demo').resolve()), 'ses_test'): {'webfetch'}}
        for attr, value in [('PROJECTS', self.root), ('_session_permissions', self.grants)]:
            mocked = patch.object(bridge, attr, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        for attr, value in [('build_context', {}), ('configure_model', {'providerID': 'local', 'modelID': 'test'})]:
            mocked = patch.object(bridge, attr, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        mocked = patch.object(bridge, 'request', side_effect=lambda *a, **k: self.respond(*a, **k))
        mocked.start()
        self.addCleanup(mocked.stop)

    def respond(self, path, data=None, name=None, **kwargs):
        self.calls.append(path)
        if path == '/session/ses_test':
            return {'directory': str(self.root / 'demo')}
        if path == '/session/ses_test/message':
            return copy.deepcopy(self.messages)
        if path == '/session/status':
            return {'ses_test': {'type': self.status}, 'ses_other': {'type': 'busy'}}
        if path == '/permission':
            return copy.deepcopy(self.pending)
        if path == '/session/ses_test/abort':
            self.status = 'idle'
            self.pending = []
            return True
        if path == '/session/ses_test/prompt_async':
            self.messages.append(user('New request'))
            self.status = 'busy'
            return True
        if path == '/session/ses_test/diff':
            return []
        if path == '/permission/pending/reply':
            self.pending = []
            return True
        self.fail('Unexpected request: ' + path)

    def poll(self):
        return bridge.action({'action': 'poll', 'project': 'demo', 'session': 'ses_test'})

    def test_pauses_selected_loop_before_approving_and_reads_real_status(self):
        result = self.poll()
        self.assertEqual(result['status']['type'], 'idle')
        self.assertEqual(result['recovery']['label'], 'Web fetch loop paused')
        self.assertTrue(result['recovery']['can_continue'])
        self.assertTrue(result['warnings'])
        self.assertNotIn('/permission/pending/reply', self.calls)
        self.assertNotIn('/session/ses_other/abort', self.calls)
        self.assertEqual(self.calls.count('/session/ses_test/abort'), 1)
        self.poll()
        self.assertEqual(self.calls.count('/session/ses_test/abort'), 1)

    def test_single_block_and_initial_http_failures_do_not_pause(self):
        for messages in [[user(), fetch()], [user(), fetch('HTTP 404'), fetch('HTTP 404')]]:
            with self.subTest(messages=messages):
                self.messages = messages
                self.calls = []
                self.poll()
                self.assertNotIn('/session/ses_test/abort', self.calls)

    def test_new_user_successful_tool_and_final_reply_reset_loop(self):
        final = {'info': {'role': 'assistant', 'finish': 'stop'}, 'parts': [{'type': 'text', 'text': 'Used local files instead.'}]}
        for tail in [user('Use another source'), fetch(status='completed'), fetch(tool='read'), final]:
            with self.subTest(tail=tail):
                self.assertFalse(bridge.webfetch_retry_loop(self.messages + [tail]))

    def test_real_user_message_with_per_message_summary_resets_loop(self):
        # OpenCode 1.18 attaches {diffs,title?} to every user message; Continue must still reset the pause.
        for summary in ({'diffs': []}, {'title': 'Continue task', 'diffs': []}):
            with self.subTest(summary=summary):
                self.assertFalse(bridge.webfetch_retry_loop(self.messages + [user(bridge.CONTINUE_TASK_PROMPT, summary=summary)], 'ses_test'))
        excerpts = bridge.context_recovery_prompt([user('Make the maze authentic', summary={'diffs': []})])
        self.assertIn('Make the maze authentic', excerpts)

    def test_synthetic_compaction_and_foreign_messages_do_not_reset_or_create_loop(self):
        for tail in [user(summary=True), user(agent='compaction'),
                     {'info': {'role': 'user'}, 'parts': [{'type': 'text', 'text': 'Continue', 'synthetic': True}]},
                     {'info': {'role': 'user'}, 'parts': [{'type': 'file', 'synthetic': True}]}]:
            with self.subTest(tail=tail):
                self.assertTrue(bridge.webfetch_retry_loop(self.messages + [tail], 'ses_test'))
        foreign = copy.deepcopy(fetch())
        foreign['info']['sessionID'] = 'ses_other'
        self.assertFalse(bridge.webfetch_retry_loop([user(), foreign, foreign], 'ses_test'))

    def test_abort_failure_keeps_task_active_and_blocks_automatic_approval(self):
        original = self.respond

        def failed_abort(path, *args, **kwargs):
            if path.endswith('/abort'):
                raise ValueError('Connection interrupted')
            return original(path, *args, **kwargs)

        self.respond = failed_abort
        result = self.poll()
        self.assertEqual(result['status']['type'], 'busy')
        self.assertFalse(result['recovery']['can_continue'])
        self.assertTrue(any('Could not pause' in warning for warning in result['warnings']))
        self.assertNotIn('/permission/pending/reply', self.calls)

    def test_new_send_waits_for_old_poll_and_is_never_aborted_using_old_history(self):
        self.status = 'idle'
        history_read, release_poll, send_attempted = threading.Event(), threading.Event(), threading.Event()
        original = self.respond

        def paused_history(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == '/session/ses_test/message':
                history_read.set()
                if not release_poll.wait(5):
                    raise RuntimeError('Test did not release history read')
            return result

        self.respond = paused_history

        def send():
            send_attempted.set()
            return bridge.action({'action': 'send', 'project': 'demo', 'session': 'ses_test', 'prompt': 'New request'})

        with ThreadPoolExecutor(max_workers=2) as pool:
            poll = pool.submit(self.poll)
            try:
                self.assertTrue(history_read.wait(2))
                new_task = pool.submit(send)
                self.assertTrue(send_attempted.wait(2))
                self.assertFalse(new_task.done())
            finally:
                release_poll.set()
            self.assertEqual(poll.result(timeout=5)['status']['type'], 'idle')
            self.assertTrue(new_task.result(timeout=5))
        self.respond = original
        self.assertNotIn('/session/ses_test/abort', self.calls)
        self.poll()
        self.assertNotIn('/session/ses_test/abort', self.calls)
        self.assertEqual(self.status, 'busy')


if __name__ == '__main__':
    unittest.main()
