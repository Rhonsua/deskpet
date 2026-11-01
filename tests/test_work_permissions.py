import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from deskpet.chat.work_permissions import write_runtime_patch


class WorkPermissionTests(unittest.TestCase):
    def test_enabled_and_disabled_keep_review_loaded_and_human_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            module=root/'node_modules/@deepseek-ai/dsh-experimental-auto-review/lib/index.js'
            module.parent.mkdir(parents=True);module.write_text('fixture')
            with patch('deskpet.chat.work_permissions.INSTALL',root):
                for enabled in (True,False):
                    rows=json.loads(write_runtime_patch(root,'session1',enabled).read_text('utf8'))
                    byid={r['id']:r for r in rows if 'id' in r}
                    self.assertEqual(byid['approval']['config']['policy'],'ask')
                    self.assertEqual(byid['sandbox-policy']['config']['mode'],'workspace-write')
                    inserted=rows[-1]['insert']
                    self.assertEqual(inserted[0]['name'],str(module))
                    self.assertEqual(inserted[1]['config'],{'sessionId':'session1','autoApprove':enabled})
                module.unlink()
                with self.assertRaises(ValueError):write_runtime_patch(root,'session1',True)
