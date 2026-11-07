import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sandbox
import dev_server
import opencode_bridge as bridge

ROOT = Path(__file__).resolve().parents[1]


class SandboxStateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.project = Path(self.dir.name) / 'my site'
        self.project.mkdir()
        context = patch.object(sandbox, 'STATE_FILE', Path(self.dir.name) / 'sandbox.json')
        context.start()
        self.addCleanup(context.stop)
        # No real Docker: set_project must still record the choice.
        for target in (patch.object(sandbox, 'docker', return_value=None), patch.object(sandbox, 'prepare')):
            target.start()
            self.addCleanup(target.stop)

    def test_off_by_default_and_toggles(self):
        self.assertIsNone(sandbox.setting(self.project))
        sandbox.set_project(self.project, True, network=False)
        self.assertEqual(sandbox.setting(self.project), {'network': False})
        self.assertEqual(sandbox.root_for(self.project / 'src'), sandbox.key(self.project))
        self.assertIsNone(sandbox.root_for(self.project.parent))
        self.assertIsNone(sandbox.root_for(str(self.project) + '-other'))
        sandbox.set_project(self.project, False)
        self.assertIsNone(sandbox.setting(self.project))

    def test_payload_round_trip_keeps_shell_text_exactly(self):
        command = 'echo "a \'b\' & $HOME | c" && exit 3'
        payload = sandbox.encode(command, self.project, 60)
        self.assertRegex(payload, r'^[A-Za-z0-9+/=]+$')
        self.assertEqual(sandbox.decode(payload)['c'], command)
        self.assertEqual(sandbox.unwrap(f'C:/x/python.exe -X utf8 C:/x/sandbox.py run {payload}'), command)
        self.assertEqual(sandbox.unwrap(f'& "C:/my dir/python.exe" -X utf8 "C:/my dir/sandbox.py" run {payload}'), command)
        self.assertIsNone(sandbox.unwrap('npm test'))
        self.assertIsNone(sandbox.unwrap('python sandbox.py run !!notbase64'))

    def test_container_path_stays_in_project(self):
        self.assertEqual(str(sandbox.container_path(self.project, self.project / 'src' / 'app')), '/work/src/app')
        self.assertEqual(str(sandbox.container_path(self.project, self.project)), '/work')
        with self.assertRaises(ValueError):
            sandbox.container_path(self.project, self.project.parent)

    def test_run_refuses_when_off_or_outside_and_never_runs_on_host(self):
        with patch.object(sandbox.subprocess, 'run') as run:
            self.assertEqual(sandbox.run(sandbox.encode('ls', self.project, 30)), 126)
            sandbox.set_project(self.project, True)
            self.assertEqual(sandbox.run(sandbox.encode('ls', self.project.parent, 30, root=self.project)), 126)
            run.assert_not_called()

    def test_run_executes_in_container_with_time_limit(self):
        sandbox.set_project(self.project, True)
        with patch.object(sandbox, 'ensure', return_value='box'), patch.object(sandbox, 'docker', return_value='docker'), \
                patch.object(sandbox.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(sandbox.run(sandbox.encode('npm test', self.project / 'web', 9999)), 0)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:5], ['docker', 'exec', '-w', '/work/web', 'box'])
        self.assertEqual(argv[5:], ['timeout', '-k', '5', '3600', 'sh', '-c', 'npm test'])

    def test_container_is_locked_down(self):
        calls = []
        with patch.object(sandbox, '_docker', side_effect=lambda *a, **k: calls.append(a)):
            sandbox._create(self.project, network=False)
        run = calls[0]
        for flag in ('--init', '--read-only', 'no-new-privileges', '--pids-limit', '--memory'):
            self.assertIn(flag, run)
        self.assertEqual(run[run.index('--cap-drop') + 1], 'ALL')
        self.assertEqual(run[run.index('--user') + 1], '1000:1000')
        mounts = [run[i + 1] for i, a in enumerate(run) if a == '-v']
        self.assertEqual(mounts, [f'{self.project.resolve()}:/work'])  # nothing else from this PC
        self.assertTrue(all(run[i + 1].startswith('127.0.0.1::') for i, a in enumerate(run) if a == '-p'))
        self.assertEqual(calls[1], ('network', 'disconnect', 'bridge', sandbox.name(self.project)))

    def test_dev_command_binds_all_interfaces_in_container(self):
        with patch.object(sandbox, 'ensure', return_value='box'), patch.object(sandbox, 'docker', return_value='docker'):
            vite = sandbox.dev_command(self.project, ['run', 'dev'], 'vite')
            install = sandbox.dev_command(self.project, ['install'])
        self.assertTrue(vite[-1].endswith('exec npm run dev -- --host 0.0.0.0'))
        self.assertTrue(install[-1].endswith('exec npm install'))
        self.assertIn('setsid', vite)

    def test_host_url_maps_published_port(self):
        with patch.object(sandbox, 'host_port', side_effect=lambda f, p: 49200 if p == 5173 else None):
            self.assertEqual(sandbox.host_url(self.project, 'http://localhost:5173/app/'), 'http://127.0.0.1:49200/app/')
            self.assertIsNone(sandbox.host_url(self.project, 'http://localhost:9999/'))

    def test_dev_server_refuses_offline_sandbox(self):
        (self.project / 'package.json').write_text(json.dumps({'scripts': {'dev': 'vite'}}))
        sandbox.set_project(self.project, True, network=False)
        with self.assertRaisesRegex(ValueError, 'internet'):
            dev_server.start(self.project, 'my site')


class NativeModulesTests(unittest.TestCase):
    def test_detects_which_os_native_packages_were_built_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(dev_server.modules_platforms(tmp), set())
            (Path(tmp) / 'node_modules/@esbuild/win32-x64').mkdir(parents=True)
            (Path(tmp) / 'node_modules/@rollup/rollup-win32-x64-msvc').mkdir(parents=True)
            self.assertEqual(dev_server.modules_platforms(tmp), {'win32'})
            self.assertEqual(dev_server._target_os(True), 'linux')


class ApprovalTests(unittest.TestCase):
    def test_auto_checks_judge_the_original_sandboxed_command(self):
        folder = ROOT / 'tests'
        wrapped = 'python -X utf8 sandbox.py run ' + sandbox.encode('node --test', folder, 60)
        permission = {'permission': 'bash', 'sessionID': 's', 'tool': {'messageID': 'm', 'callID': 'c'}}
        messages = [{'info': {'id': 'm', 'sessionID': 's'}, 'parts': [
            {'type': 'tool', 'callID': 'c', 'tool': 'bash', 'state': {'status': 'running', 'input': {'command': wrapped}}}]}]
        self.assertTrue(bridge.safe_project_check(permission, folder, messages))
        messages[0]['parts'][0]['state']['input']['command'] = wrapped.replace(
            wrapped.split()[-1], sandbox.encode('rm -rf /work', folder, 60))
        self.assertFalse(bridge.safe_project_check(permission, folder, messages))


@unittest.skipUnless(shutil.which('node'), 'node is required')
class PluginTests(unittest.TestCase):
    def test_plugin_wraps_only_sandboxed_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'proj'
            (project / 'src').mkdir(parents=True)
            state = Path(tmp) / 'sandbox.json'
            state.write_text(json.dumps({'projects': {sandbox.key(project): {'network': True}}}))
            script = """
const { DreadOSSandbox } = await import(process.argv[1]);
const out = [];
for (const [dir, workdir, command] of JSON.parse(process.argv[2])) {
  const hooks = await DreadOSSandbox({ directory: dir });
  const output = { args: { command, workdir, timeout: 30000 } };
  await hooks["tool.execute.before"]({ tool: "bash" }, output);
  out.push(output.args.command);
}
console.log(JSON.stringify(out));"""
            cases = [[str(project), 'src', 'curl.exe -sS https://x'], [str(Path(tmp)), None, 'dir']]
            result = subprocess.run(['node', '--input-type=module', '-e', script,
                                     (ROOT / 'opencode-plugins/sandbox.mjs').as_uri(), json.dumps(cases)],
                                    capture_output=True, text=True, env={**os.environ, 'DREADOS_SANDBOX_STATE': str(state)})
            self.assertEqual(result.returncode, 0, result.stderr)
            wrapped, untouched = json.loads(result.stdout)
            self.assertEqual(untouched, 'dir')
            data = sandbox.decode(sandbox.WRAPPED_RE.search(wrapped).group(1))
            self.assertEqual(data['c'], 'curl -sS https://x')  # PowerShell's curl.exe fix undone for Linux
            self.assertEqual(sandbox.key(data['w']), sandbox.key(project / 'src'))
            self.assertEqual(data['t'], 30)


if __name__ == '__main__':
    unittest.main()
