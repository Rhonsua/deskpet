"""Validate the hand-data allowlist without invoking PyInstaller/building."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HandPackagingTests(unittest.TestCase):
    def test_only_aligned_runtime_art_and_manifest_are_bundled(self):
        tree = ast.parse((ROOT/'packaging/deskpet.spec').read_text(encoding='utf-8'))
        start = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == 'hand_root' for target in node.targets))
        nodes = tree.body[start:start+2]
        self.assertIsInstance(nodes[1], ast.For)
        namespace = {'root': ROOT, 'datas': []}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<hand-asset-check>', 'exec'), namespace)
        self.assertEqual({Path(src).name for src, dest in namespace['datas']},
                         {'hand-hover.png', 'hand-contact.png', 'manifest.json'})
        self.assertTrue(all(dest == 'assets/ui/headpat' for src, dest in namespace['datas']))
        self.assertTrue(all('original' not in Path(src).parts for src, dest in namespace['datas']))


if __name__ == '__main__':
    unittest.main()
