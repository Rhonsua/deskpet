"""Bounded, data-only character personality files; never imports plugin code."""
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Personality:
    version: int
    id: str
    name: str
    persona: str
    allowed: tuple[str, ...]
    decline: tuple[str, ...]
    guidance: str
    examples: tuple[tuple[str, str], ...]
    source: str


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('invalid text')
    value.encode('utf-8')  # Reject escaped lone surrogates before they reach HTTP encoding.
    return value.strip()


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('invalid fields')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


def _scope_list(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        raise ValueError('invalid scope')
    return tuple(_text(item, 300) for item in value)


def _parse(raw, source):
    _keys(raw, ('version', 'id', 'name', 'persona', 'scope', 'examples'))
    if type(raw['version']) is not int or raw['version'] != 1:
        raise ValueError('unsupported version')
    scope = raw['scope']
    _keys(scope, ('allowed', 'decline', 'guidance'))
    examples = raw['examples']
    if not isinstance(examples, list) or len(examples) > 12:
        raise ValueError('invalid examples')
    parsed = []
    for example in examples:
        _keys(example, ('user', 'assistant'))
        parsed.append((_text(example['user'], 1000), _text(example['assistant'], 1000)))
    result = Personality(1, _text(raw['id'], 100), _text(raw['name'], 100),
                         _text(raw['persona'], 8000), _scope_list(scope['allowed']),
                         _scope_list(scope['decline']), _text(scope['guidance'], 2000),
                         tuple(parsed), source)
    texts = (result.id, result.name, result.persona, result.guidance,
             *result.allowed, *result.decline, *(text for pair in result.examples for text in pair))
    if sum(map(len, texts)) > 16000:
        raise ValueError('personality too long')
    return result


def _fallback(character_key, name):
    if character_key == 'builtin:luotianyi':
        from .persona import TIANYI_PERSONA, TIANYI_SCOPE, TIANYI_EXAMPLES
        return Personality(1, 'luotianyi', '洛天依', TIANYI_PERSONA,
                           tuple(TIANYI_SCOPE['allowed']), tuple(TIANYI_SCOPE['decline']),
                           TIANYI_SCOPE['guidance'],
                           tuple((item['user'], item['assistant']) for item in TIANYI_EXAMPLES),
                           '内置洛天依人格（备用）')
    return Personality(1, 'companion', str(name).strip()[:100] or '桌面伙伴',
                       '你是住在用户桌面的友善伙伴，真诚自然地陪伴聊天。不假冒其他角色，不编造经历。',
                       ('日常闲聊', '分享心情与兴趣', '简单生活常识'),
                       ('复杂解题与专业任务', '声称操作电脑或读取未提供的数据'),
                       '不懂就坦诚说明；超出范围时简短解释，并自然回到可以陪伴的话题。',
                       (), '通用陪伴人格')


def load_personality(character_key: str, name: str, root: Path | None = None) -> tuple[Personality, str]:
    builtin = character_key == 'builtin:luotianyi'
    base = Path(__file__).parent / 'personas' if builtin else (Path(root) if root is not None else None)
    fallback = _fallback(character_key, name)
    if base is None:
        return fallback, ''
    try:
        base = base.resolve()
        candidate = base / ('luotianyi.json' if builtin else 'personality.json')
        resolved = candidate.resolve()
        # A fixed filename may itself be a symlink; it must stay inside its character root.
        resolved.relative_to(base)
        try:
            with resolved.open('rb') as file:
                data = file.read(65537)
        except FileNotFoundError:
            return fallback, '内置人格文件缺失，已使用备用人格。' if builtin else ''
        if len(data) > 65536:
            raise ValueError('file too large')
        raw = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_pairs,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError('invalid number')))
        return _parse(raw, '内置洛天依人格' if builtin else '角色目录中的人格插件'), ''
    except (OSError, ValueError, TypeError, RuntimeError):
        return fallback, '人格文件无法读取或格式不符合要求，已使用备用人格。'
