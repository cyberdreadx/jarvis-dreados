import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_terminal as term
import sandbox


def wait(root, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        info = term.status(root, 0)
        if not info['running']:
            return info
        time.sleep(0.1)
    raise AssertionError('command did not finish')


class BuildTerminalTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name) / 'proj'
        (self.root / 'src').mkdir(parents=True)
        for target in (patch.object(sandbox, 'STATE_FILE', Path(self.dir.name) / 'sandbox.json'),
                       patch.dict(term._terms, clear=True)):
            target.start()
            self.addCleanup(target.stop)
        self.addCleanup(lambda: [term._kill(t) for t in list(term._terms.values())])

    def test_cd_stays_inside_project(self):
        term.run(self.root, 'cd src')
        self.assertEqual(term.status(self.root)['cwd'], 'src')
        term.run(self.root, 'cd..')
        self.assertEqual(term.status(self.root)['cwd'], '.')
        for outside in ('cd ..', 'cd /', 'cd C:\\', f'cd "{self.dir.name}"'):
            term.run(self.root, outside)
            self.assertEqual(term.status(self.root)['cwd'], '.')
        self.assertIn('stays inside the project folder', term.status(self.root, 0)['output'])
        term.run(self.root, 'cd missing')
        self.assertIn('No such folder', term.status(self.root, 0)['output'])

    def test_runs_in_cwd_streams_output_and_reports_exit_code(self):
        (self.root / 'src' / 'app.py').write_text('import os\nprint("in", os.path.basename(os.getcwd()), "é")\nraise SystemExit(3)\n',
                                                  encoding='utf-8')
        term.run(self.root, 'cd src')
        term.run(self.root, f'"{sys.executable}" app.py' if sys.platform != 'win32' else f'& "{sys.executable}" app.py')
        info = wait(self.root)
        self.assertIn('in src é', info['output'])
        self.assertEqual(info['exit'], 3)
        self.assertIn('[exit code 3]', info['output'])

    def test_typed_input_reaches_the_running_command(self):
        (self.root / 'ask.py').write_text('name = input("name? ")\nprint("hi", name)\n')
        term.run(self.root, f'& "{sys.executable}" ask.py' if sys.platform == 'win32' else f'"{sys.executable}" ask.py')
        time.sleep(1)
        term.send_input(self.root, 'Ada')
        self.assertIn('hi Ada', wait(self.root)['output'])

    def test_one_command_at_a_time_and_stop(self):
        slow = f'& "{sys.executable}" -c "import time; time.sleep(60)"' if sys.platform == 'win32' else \
            f'"{sys.executable}" -c "import time; time.sleep(60)"'
        term.run(self.root, slow)
        with self.assertRaisesRegex(ValueError, 'still running'):
            term.run(self.root, 'echo hi')
        info = term.stop(self.root)
        self.assertFalse(info['running'])
        self.assertIn('^C stopped', info['output'])
        self.assertNotIn('[exit code', info['output'])
        self.assertIsNone(wait(self.root)['exit'])
        with self.assertRaisesRegex(ValueError, 'No command'):
            term.send_input(self.root, 'x')

    def test_offsets_and_clear(self):
        t = term._term(self.root)
        t.write('abc')
        first = term.status(self.root, None)
        self.assertTrue(first['reset'])
        self.assertEqual(first['output'], 'abc')
        t.write('def')
        later = term.status(self.root, first['offset'])
        self.assertEqual((later['output'], later['reset']), ('def', False))
        cleared = term.clear(self.root)
        self.assertEqual(cleared['output'], '')
        self.assertEqual(term.status(self.root, cleared['offset'])['output'], '')
        with patch.object(term, 'KEEP', 4):
            t.write('123456')
        self.assertTrue(term.status(self.root, 0)['reset'])
        self.assertEqual(term.status(self.root, 0)['output'], '3456')

    def test_rejects_empty_and_huge_commands(self):
        for bad in ('', '   ', None, 'x' * 9000):
            with self.assertRaises(ValueError):
                term.run(self.root, bad)

    def test_sandboxed_project_runs_in_container(self):
        with patch.object(sandbox, 'docker', return_value=None), patch.object(sandbox, 'prepare'), \
                patch.object(sandbox, 'status', return_value={}):
            sandbox.set_project(self.root, True)
        t = term._term(self.root)
        t.sandboxed, t.cwd = True, ('src',)
        with patch.object(sandbox, 'ensure', return_value='box'), patch.object(sandbox, 'docker', return_value='docker'):
            argv, folder = term._argv(t, 'python app.py')
        self.assertEqual(argv[:7], ['docker', 'exec', '-i', '-e', 'PYTHONUNBUFFERED=1', '-w', '/work/src'])
        self.assertEqual(argv[7:10], ['box', 'setsid', '-w'])
        self.assertEqual(argv[-1], 'python app.py')
        self.assertEqual(folder, self.root.resolve() / 'src')


if __name__ == '__main__':
    unittest.main()
