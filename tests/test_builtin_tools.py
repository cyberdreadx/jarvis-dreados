"""Registry-level checks for DreadOS Tools and how their results land in the media library."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import builtin_tools
import media_library
import mcp_client


class RegistryTests(unittest.TestCase):
    def test_all_tools_registered_with_valid_schemas(self):
        names = {t['name'] for t in builtin_tools.tools()}
        self.assertEqual(names, {'draw_chord_diagrams', 'calculate', 'draw_chart', 'draw_flowchart',
                                 'make_qr_code', 'color_palette', 'draw_scale', 'new_site', 'audit_site'})
        self.assertNotIn('audit_site', builtin_tools.image_tools())
        for tool in builtin_tools.tools():
            with self.subTest(tool=tool['name']):
                self.assertLessEqual(len(tool['description']), 700)
                self.assertEqual(tool['inputSchema']['type'], 'object')
                self.assertNotIn('returnsImage', tool)
        self.assertNotIn('calculate', builtin_tools.image_tools())
        self.assertLess(len(json.dumps(builtin_tools.tools())), 50000)   # chat_tools catalog limit

    def test_a_crashing_tool_reports_instead_of_raising(self):
        registry = builtin_tools._load()[0]
        tool, module = registry['draw_chart']
        with patch.object(module, 'call', side_effect=ZeroDivisionError):
            out = builtin_tools.call('draw_chart', {})
        self.assertTrue(out['isError'])


class MediaTests(unittest.TestCase):
    def capture(self, tool, args):
        with tempfile.TemporaryDirectory() as tmp, patch.object(media_library, 'DB', Path(tmp) / 'm.sqlite3'):
            call = {'tool': tool, 'arguments': args}
            return media_library.capture(call, mcp_client.call({'id': builtin_tools.SERVICE_ID, **call}))

    def test_wifi_password_is_never_stored(self):
        item = self.capture('make_qr_code', {'wifi': {'ssid': 'Lab', 'password': 'hunter2!', 'security': 'WPA'}})
        self.assertNotIn('hunter2', json.dumps(item))
        self.assertEqual(item['prompt'], 'Wi-Fi QR code: Lab')

    def test_descriptive_captions(self):
        self.assertEqual(self.capture('make_qr_code', {'url': 'https://dreados.ai'})['prompt'], 'QR code: https://dreados.ai')
        self.assertEqual(self.capture('draw_scale', {'root': 'A', 'scale': 'minor_pentatonic'})['prompt'], 'A minor pentatonic (guitar)')
        self.assertEqual(self.capture('color_palette', {'color': '#2ff3d0', 'scheme': 'complementary'})['prompt'],
                         'Complementary palette from #2ff3d0')

    def test_text_only_and_failed_tools_are_not_saved(self):
        self.assertIsNone(self.capture('calculate', {'expression': '2+2'}))
        self.assertIsNone(self.capture('draw_chord_diagrams', {'chords': ['Qzz']}))


if __name__ == '__main__':
    unittest.main()
