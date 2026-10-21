"""Personality plugins use isolated data only; no provider access."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pet_chat.personality import load_personality


def valid():
    return dict(version=1, id='custom', name='伙伴', persona='温柔地陪伴聊天。',
                scope=dict(allowed=['闲聊'], decline=['复杂解题'], guidance='坦诚说明能力边界。'),
                examples=[dict(user='你好', assistant='你好呀。')])


class PersonalityTests(unittest.TestCase):
    def test_distributed_character_personality_templates_load(self):
        project = Path(__file__).resolve().parents[1]
        for relative in ('pet_chat/personas/miku.json', 'characters/example/personality.json.example'):
            with self.subTest(template=relative):
                data = (project / relative).read_bytes()
                plugin, warning = self.load_data(data)
                self.assertFalse(warning)
                self.assertNotEqual(plugin.id, 'luotianyi')
                self.assertTrue(plugin.allowed)
                self.assertTrue(plugin.decline)
                self.assertNotIn('你是洛天依', plugin.persona)
                if relative.endswith('miku.json'):
                    self.assertIn('初音未来', plugin.persona)

    def load_data(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'personality.json'
            path.write_bytes(data)
            return load_personality('external:test', '洛天依', Path(directory))

    def test_bom_valid_and_frozen(self):
        result, warning = self.load_data(b'\xef\xbb\xbf' + json.dumps(valid(), ensure_ascii=False).encode())
        self.assertFalse(warning)
        self.assertEqual(result.id, 'custom')
        self.assertEqual(result.examples, (('你好', '你好呀。'),))
        self.assertEqual(result.allowed, ('闲聊',))
        with self.assertRaises(FrozenInstanceError):
            result.name = 'other'

    def test_external_same_name_does_not_bind_tianyi(self):
        for root in (None,):
            result, warning = load_personality('external:luotianyi', '洛天依', root)
            self.assertFalse(warning)
            self.assertEqual(result.id, 'companion')
            self.assertNotIn('小笼包', result.persona)
        with tempfile.TemporaryDirectory() as directory:
            result, warning = load_personality('external:x', '洛天依', Path(directory))
            self.assertFalse(warning)
            self.assertEqual(result.id, 'companion')

    def test_malformed_json_and_encoding_fall_back_with_warning(self):
        for data in (b'{', b'[]', b'null', b'\xff', b'{"version":1,"version":1}',
                     json.dumps(valid()).replace('"allowed": ["', '"allowed": [NaN, "').encode(),
                     b' ' * 65537):
            with self.subTest(data=data[:80]):
                result, warning = self.load_data(data)
                self.assertTrue(warning)
                self.assertEqual(result.id, 'companion')

    def test_strict_schema_and_types(self):
        mutations = [lambda x: x.update(version=True), lambda x: x.update(version=2),
                     lambda x: x.update(version=1.0), lambda x: x.update(extra='x'),
                     lambda x: x.pop('name'), lambda x: x.update(persona=4),
                     lambda x: x.update(persona='\ud800'),
                     lambda x: x.update(name=' '), lambda x: x.update(id='x' * 101),
                     lambda x: x.update(persona='x' * 8001),
                     lambda x: x['scope'].update(allowed='chat'),
                     lambda x: x['scope'].update(allowed=[]),
                     lambda x: x['scope'].update(allowed=['x'] * 33),
                     lambda x: x['scope'].update(decline=[False]),
                     lambda x: x['scope'].update(guidance='x' * 2001),
                     lambda x: x['scope'].update(allowed=['x' * 301]),
                     lambda x: x.update(examples={}),
                     lambda x: x.update(examples=[dict(user='a', assistant='b')] * 13),
                     lambda x: x.update(examples=[dict(user='a')]),
                     lambda x: x.update(examples=[dict(user='a', assistant=0)]),
                     lambda x: x.update(examples=[dict(user='a' * 1001, assistant='b')])]
        for mutate in mutations:
            data = valid()
            mutate(data)
            with self.subTest(data=data):
                self.assertTrue(self.load_data(json.dumps(data).encode())[1])

    def test_total_text_limit_and_exact_byte_limit(self):
        data = valid()
        data.update(persona='a' * 8000, examples=[dict(user='u' * 1000, assistant='a' * 1000)] * 5)
        self.assertTrue(self.load_data(json.dumps(data).encode())[1])
        payload = json.dumps(valid()).encode()
        self.assertFalse(self.load_data(payload + b' ' * (65536 - len(payload)))[1])
        self.assertTrue(self.load_data(payload + b' ' * (65537 - len(payload)))[1])

    def test_duplicate_nested_keys_rejected(self):
        payload = json.dumps(valid()).replace('"guidance":', '"allowed": ["override"], "guidance":')
        self.assertTrue(self.load_data(payload.encode())[1])

    def test_resolved_path_must_stay_within_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = Path.resolve
            def resolve(path, *args, **kwargs):
                if path.name == 'personality.json':
                    return root.parent / 'outside.json'
                return original(path, *args, **kwargs)
            with patch.object(Path, 'resolve', resolve):
                result, warning = load_personality('external:x', 'other', root)
            self.assertEqual(result.id, 'companion')
            self.assertTrue(warning)

    def test_symlink_resolution_error_falls_back(self):
        with patch.object(Path, 'resolve', side_effect=RuntimeError('Symlink loop')):
            result, warning = load_personality('external:x', 'other', Path('.'))
        self.assertEqual(result.id, 'companion')
        self.assertTrue(warning)

    def test_builtin_missing_and_damaged_use_authored_fallback(self):
        from pet_chat import persona
        scope = dict(allowed=['闲聊'], decline=['解题'], guidance='说明边界')
        with patch.object(persona, 'TIANYI_SCOPE', scope, create=True), \
             patch.object(persona, 'TIANYI_EXAMPLES', [dict(user='hi', assistant='你好')], create=True):
            with patch.object(Path, 'open', side_effect=FileNotFoundError):
                result, warning = load_personality('builtin:luotianyi', 'other')
            self.assertEqual(result.id, 'luotianyi')
            self.assertEqual(result.persona, persona.TIANYI_PERSONA)
            self.assertTrue(warning)
            with patch.object(Path, 'open', side_effect=PermissionError):
                result, warning = load_personality('builtin:luotianyi', 'other')
            self.assertEqual(result.id, 'luotianyi')
            self.assertTrue(warning)


if __name__ == '__main__':
    unittest.main()
