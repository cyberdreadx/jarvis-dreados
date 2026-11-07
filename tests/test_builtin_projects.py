import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from builtin_tools import projects as p


class ProjectSandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(p, 'PROJECTS', Path(self.tmp.name) / 'build-projects')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_slug(self):
        self.assertEqual(p.slug('Jazz Guitar Site!'), 'jazz-guitar-site')
        self.assertEqual(p.slug('***'), 'my-site')

    def test_names_and_escapes_are_rejected(self):
        for bad in ('../x', 'Bad Name', '', 'a/b', 'C:\\x', '.hidden'):
            with self.subTest(name=bad):
                with self.assertRaises(p.ProjectError):
                    p.project_dir(bad, must_exist=False)

    def test_create_never_overwrites_and_rejects_unsafe_files(self):
        p.write_files('site', {'index.html': '<h1>hi</h1>', 'css/style.css': 'body{}'})
        self.assertEqual((p.PROJECTS / 'site' / 'css' / 'style.css').read_text(), 'body{}')
        with self.assertRaisesRegex(p.ProjectError, 'already exists'):
            p.write_files('site', {'index.html': 'x'})
        for bad in ('../escape.txt', '/abs.txt', 'a/../../b.txt'):
            with self.subTest(path=bad):
                with self.assertRaises(p.ProjectError):
                    p.write_files('other-' + str(abs(hash(bad)) % 1000), {bad: 'x'})

    def test_read_stays_inside(self):
        p.write_files('site', {'index.html': 'ok'})
        self.assertEqual(p.read_text('site', 'index.html'), 'ok')
        with self.assertRaises(p.ProjectError):
            p.read_text('site', '../../secret.txt')
        self.assertEqual([rel for rel, _ in p.iter_files('site')], ['index.html'])
        with self.assertRaisesRegex(p.ProjectError, 'No Build project'):
            p.project_dir('missing')


if __name__ == '__main__':
    unittest.main()
