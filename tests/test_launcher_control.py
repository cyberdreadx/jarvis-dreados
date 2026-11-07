import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'launcher'))
import control  # noqa: E402

MINE = f'"{control.PYTHON}" "{control.BOOT}"'


class StopTests(unittest.TestCase):
    def stop(self, listener, ready=True, processes=()):
        with patch.object(control, 'listener', return_value=listener), \
             patch.object(control, 'ready', side_effect=[ready, False]), \
             patch.object(control, 'own_processes', return_value=list(processes)), \
             patch.object(control, 'owned', side_effect=lambda p: p.get('CommandLine') == MINE), \
             patch.object(control, 'stop_pids') as stop:
            return control.run('stop', 8765, True), stop

    def test_known_owner_is_stopped(self):
        message, stop = self.stop({'ProcessId': 42, 'CommandLine': MINE})
        stop.assert_called_once_with([42])
        self.assertIn('stopped', message)

    def test_unattributed_port_falls_back_to_this_installation_root_process(self):
        # Windows reported the listener as PID 0; the venv launcher (10) started the server (11).
        procs = [{'ProcessId': 10, 'ParentProcessId': 1, 'CommandLine': MINE},
                 {'ProcessId': 11, 'ParentProcessId': 10, 'CommandLine': MINE}]
        message, stop = self.stop({'ProcessId': 0, 'CommandLine': None}, processes=procs)
        stop.assert_called_once_with([10])
        self.assertIn('stopped', message)

    def test_missing_listener_but_dreados_answering_is_still_stopped(self):
        procs = [{'ProcessId': 10, 'ParentProcessId': 1, 'CommandLine': MINE}]
        with patch.object(control, 'listener', return_value=None), \
             patch.object(control, 'ready', side_effect=[True, True, False]), \
             patch.object(control, 'own_processes', return_value=procs), \
             patch.object(control, 'stop_pids') as stop:
            self.assertIn('stopped', control.run('stop', 8765, True))
        stop.assert_called_once_with([10])

    def test_nothing_listening_and_not_answering_is_already_stopped(self):
        with patch.object(control, 'listener', return_value=None), patch.object(control, 'ready', return_value=False):
            self.assertEqual(control.run('stop', 8765, True), 'DreadOS is already stopped.')

    def test_unattributed_port_that_is_not_dreados_is_left_alone(self):
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            self.stop({'ProcessId': 0, 'CommandLine': None}, ready=False)

    def test_dreados_answering_but_not_this_installation_is_left_alone(self):
        with self.assertRaisesRegex(RuntimeError, 'could not be identified'):
            self.stop({'ProcessId': 0, 'CommandLine': None}, processes=[])

    def test_start_ignores_ghost_listeners_when_port_binds(self):
        import socket
        with socket.socket() as probe:  # find a free port
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        self.assertTrue(control.port_free(port))
        with socket.socket() as held:
            held.bind(('127.0.0.1', port)); held.listen()
            with patch.object(control.time, 'sleep'):
                self.assertFalse(control.port_free(port))

    def test_other_application_is_never_stopped(self):
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            self.stop({'ProcessId': 99, 'CommandLine': 'python -m http.server 8765'})


if __name__ == '__main__':
    unittest.main()
