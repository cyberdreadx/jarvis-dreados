"""macOS-only code paths, checked with stand-ins so they also run on Windows and Linux."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import secure_settings


class FakeKeychain:
    """Mimics `/usr/bin/security` for one generic password."""
    def __init__(self):
        self.value = None
        self.commands = []

    def run(self, args, input=None, **kwargs):
        self.commands.append((args, input))
        if args[1:2] == ['find-generic-password']:
            if self.value is None:
                return subprocess.CompletedProcess(args, 44, '', 'not found')
            return subprocess.CompletedProcess(args, 0, self.value + '\n', '')
        if args[1:2] == ['-i']:
            self.value = input.split(' -w ')[1].strip()
            return subprocess.CompletedProcess(args, 0, '', '')
        raise AssertionError(args)


class MacKeychainTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.fake = FakeKeychain()
        for p in (patch.object(secure_settings, '_mac', return_value=True),
                  patch.object(secure_settings, 'MAC_PATH', Path(self.folder.name) / 'settings.mac'),
                  patch.object(secure_settings.subprocess, 'run', self.fake.run)):
            p.start(); self.addCleanup(p.stop)

    def test_round_trip_is_encrypted_and_key_stays_off_the_command_line(self):
        self.assertEqual(secure_settings.read(), {})
        secure_settings.save('providers', {'key': 'sk-secret-value'})
        secure_settings.save('second', {'value': 2})
        self.assertNotIn(b'sk-secret-value', secure_settings.MAC_PATH.read_bytes())
        self.assertEqual(secure_settings.read(), {'providers': {'key': 'sk-secret-value'}, 'second': {'value': 2}})
        for args, _ in self.fake.commands:
            self.assertNotIn(self.fake.value, ' '.join(args))
        self.assertEqual(sum(1 for a, _ in self.fake.commands if a[1:2] == ['-i']), 1)  # key created once

    def test_tampered_file_is_rejected(self):
        secure_settings.save('providers', {'key': 'x'})
        data = bytearray(secure_settings.MAC_PATH.read_bytes()); data[25] ^= 1
        secure_settings.MAC_PATH.write_bytes(bytes(data))
        with self.assertRaises(ValueError):
            secure_settings.read()

    def test_missing_key_never_replaces_existing_settings(self):
        secure_settings.save('providers', {'key': 'x'})
        before = secure_settings.MAC_PATH.read_bytes()
        self.fake.value = None
        with self.assertRaises(ValueError):
            secure_settings.save('providers', {'key': 'y'})
        self.assertEqual(secure_settings.MAC_PATH.read_bytes(), before)


class MacLauncherTests(unittest.TestCase):
    def test_stop_only_matches_this_installation(self):
        import importlib
        with patch('os.name', 'posix'):
            import launcher.control as control
            control = importlib.reload(control)
        try:
            boot = str(control.BOOT)
            self.assertTrue(control.owned({'CommandLine': f'/Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python {boot}'}))
            self.assertTrue(control.owned({'CommandLine': f'/Users/a b/DreadOS-AI/.venv-voice/bin/python {boot}'}))
            self.assertFalse(control.owned({'CommandLine': '/usr/bin/python3 -m http.server 8765'}))
            self.assertFalse(control.owned({'CommandLine': f'/usr/bin/python3 /elsewhere/launcher/server_boot.py'}))
        finally:
            importlib.reload(control)


if __name__ == '__main__':
    unittest.main()
