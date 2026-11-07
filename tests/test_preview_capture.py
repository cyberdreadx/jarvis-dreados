import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import preview_capture as preview

class PreviewCaptureTests(unittest.TestCase):
 def test_project_and_entry_boundaries(self):
  with tempfile.TemporaryDirectory() as temp:
   projects=Path(temp)/'projects'; root=projects/'demo';root.mkdir(parents=True)
   (root/'index.html').write_text('<h1>Hi</h1>')
   with patch.object(preview,'PROJECTS',projects):
    self.assertEqual(preview.project_root(root),root.resolve())
    with self.assertRaises(ValueError):preview.project_root(Path(temp))
    with self.assertRaises(ValueError):preview.capture(root,'../secret.html')
    with self.assertRaises(ValueError):preview.capture(root,'https://example.com')
 def test_mcp_returns_images_and_report(self):
  result={'entry':'index.html','images':[{'mime':'image/jpeg','data':'abc'}],'reports':[{'errors':[]}],'note':'Saved files'}
  with patch.object(preview,'capture',return_value=result):
   response=preview.mcp_result('tools/call',{'name':'check_preview','arguments':{}})
  self.assertEqual(response['content'][1],{'type':'image','mimeType':'image/jpeg','data':'abc'})
  self.assertNotIn('images',json.loads(response['content'][0]['text']))
 def test_mcp_failure_is_explicit(self):
  with patch.object(preview,'capture',side_effect=ValueError('Missing HTML')):
   response=preview.mcp_result('tools/call',{'name':'check_preview'})
  self.assertTrue(response['isError'])
  self.assertIn('Missing HTML',response['content'][0]['text'])
 def test_no_arbitrary_url_or_shell_tool(self):
  tools=preview.mcp_result('tools/list',{})['tools']
  self.assertEqual([t['name'] for t in tools],['check_preview'])
  self.assertEqual(list(tools[0]['inputSchema']['properties']),['entry','dev'])
  self.assertEqual(tools[0]['inputSchema']['properties']['dev']['type'],'boolean')
  self.assertFalse(tools[0]['inputSchema']['additionalProperties'])

if __name__=='__main__':unittest.main()
