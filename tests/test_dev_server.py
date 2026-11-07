import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import dev_server as d


def fake_spawn(lines, exit_code=None):
    """Stand-in for npm: prints `lines`, then exits with exit_code or keeps running."""
    body = ';'.join(f'print({line!r}, flush=True)' for line in lines)
    tail = f';sys.exit({exit_code})' if exit_code is not None else ';time.sleep(60)'
    def spawn(cmd, root):
        return subprocess.Popen([sys.executable, '-c', 'import sys,time;' + body + tail], cwd=root,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return spawn


def wait_for(predicate, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(.05)
    return False


class DevServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'app'
        self.root.mkdir()
        self.patches = [patch.object(d, 'STATE_FILE', Path(self.tmp.name) / 'dev-server.json'),
                        patch.object(d.shutil, 'which', return_value='npm')]
        for p in self.patches:
            p.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        d.stop()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def package(self, scripts, modules=True):
        (self.root / 'package.json').write_text(json.dumps({'scripts': scripts}))
        if modules:
            (self.root / 'node_modules').mkdir(exist_ok=True)

    def test_picks_dev_then_start_then_serve_and_explains_missing(self):
        with self.assertRaisesRegex(ValueError, 'no package.json'):
            d.script_for(self.root)
        self.package({'build': 'vite build'})
        with self.assertRaisesRegex(ValueError, 'no "dev"'):
            d.script_for(self.root)
        self.package({'start': 'node server.js', 'serve': 'x'})
        self.assertEqual(d.script_for(self.root), 'start')
        self.package({'dev': 'vite', 'start': 'x'})
        self.assertEqual(d.script_for(self.root), 'dev')

    def test_runs_detects_loopback_url_registers_it_and_stops_cleanly(self):
        self.package({'dev': 'vite'})
        lines = ['  VITE v6.0.0  ready in 300 ms', '  \x1b[32m➜\x1b[39m  Local:   \x1b[36mhttp://localhost:\x1b[1m5173\x1b[22m/\x1b[39m',
                 '  ➜  Network: http://192.168.1.20:5173/']
        with patch.object(d, '_spawn', side_effect=fake_spawn(['  VITE ready', '  Local:   http://localhost:5173/', '  Network: http://192.168.1.20:5173/'])):
            d.start(self.root, 'app')
            self.assertTrue(wait_for(lambda: d.status()['status'] == 'running'))
        info = d.status()
        self.assertEqual(info['url'], 'http://localhost:5173/')
        self.assertEqual(d.registered_url(self.root), 'http://localhost:5173/')
        self.assertIsNone(d.registered_url(Path(self.tmp.name)))  # other folders get nothing
        self.assertIn('VITE ready', info['log'])
        d.stop()
        self.assertEqual(d.status()['status'], 'stopped')
        self.assertIsNone(d.registered_url(self.root))
        # ANSI-coloured Vite output (real format) is still parsed.
        self.assertEqual(d.URL_RE.search(d.ANSI_RE.sub('', lines[1])).group(0), 'http://localhost:5173/')

    def test_lan_only_urls_are_never_used(self):
        self.package({'dev': 'vite --host'})
        with patch.object(d, '_spawn', side_effect=fake_spawn(['Network: http://192.168.1.20:5173/'])):
            d.start(self.root, 'app')
            time.sleep(1)
        self.assertIsNone(d.status()['url'])
        self.assertEqual(d.status()['status'], 'starting')

    def test_other_importers_exiting_do_not_clear_a_running_server(self):
        d.STATE_FILE.write_text(json.dumps({'root': str(self.root), 'project': 'app', 'url': 'http://localhost:5173/'}))
        d._shutdown()  # this process never started a server
        self.assertEqual(d.registered_url(self.root), 'http://localhost:5173/')

    def test_failed_install_reports_crash(self):
        self.package({'dev': 'vite'}, modules=False)
        with patch.object(d, '_spawn', side_effect=fake_spawn(['npm ERR! network'], exit_code=1)):
            self.assertEqual(d.start(self.root, 'app')['status'], 'installing')
            self.assertTrue(wait_for(lambda: d.status()['status'] == 'crashed'))
        self.assertIn('npm install failed', d.status()['error'])
        self.assertIn('npm ERR! network', d.status()['log'])

    def test_server_exit_is_reported(self):
        self.package({'dev': 'vite'})
        with patch.object(d, '_spawn', side_effect=fake_spawn(['Error: Cannot find module vite'], exit_code=1)):
            d.start(self.root, 'app')
            self.assertTrue(wait_for(lambda: d.status()['status'] == 'crashed'))
        self.assertIn('exited (code 1)', d.status()['error'])


if __name__ == '__main__':
    unittest.main()
