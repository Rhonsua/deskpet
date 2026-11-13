"""Small, sourced character knowledge; independent of erasable user memories."""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata

CONTEXT_LIMIT = 3600
CATALOG_PATH = Path(__file__).with_name('knowledge') / 'luotianyi.json'


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    terms: tuple
    content: str
    sources: tuple
    kind: str
    song: bool
    core: bool


@lru_cache(maxsize=1)
def catalog():
    """Only load the bundled catalog, never paths or content supplied in chat."""
    try:
        if CATALOG_PATH.stat().st_size > 128 * 1024:
            return ()
        data = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
        if data['version'] != 1 or not 1 <= len(data['entries']) <= 100:
            return ()
        result = []
        seen = set()
        for item in data['entries']:
            if (not all(isinstance(item[k], str) and 0 < len(item[k]) <= 800
                        for k in ('id', 'title', 'content', 'kind'))
                    or not isinstance(item['terms'], list) or not 1 <= len(item['terms']) <= 30
                    or not all(isinstance(t, str) and 1 <= len(t) <= 100 for t in item['terms'])
                    or not isinstance(item['sources'], list) or not 1 <= len(item['sources']) <= 5
                    or not all(isinstance(s, str) and s.startswith('https://') and len(s) <= 300
                               for s in item['sources'])
                    or type(item['song']) is not bool or type(item['core']) is not bool
                    or item['id'] in seen):
                return ()
            seen.add(item['id'])
            result.append(Entry(item['id'], item['title'], tuple(item['terms']), item['content'],
                                tuple(item['sources']), item['kind'], item['song'], item['core']))
        return tuple(result)
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def normalized(text):
    return unicodedata.normalize('NFKC', text).casefold()


def key(text):
    return ''.join(c for c in normalized(text) if c.isalnum())


def matches(term, text):
    # Punctuation/spacing in filenames and English song titles often varies.
    value = key(term)
    if not value:
        return False
    # "ST" must not match "just", nor "COP" match "copyright".
    if re.fullmatch('[a-z0-9]+', value):
        pattern = r'[\W_]*'.join(re.escape(part) for part in re.findall('[a-z0-9]+', normalized(term)))
        return re.search(r'(?<![a-z0-9])' + pattern + r'(?![a-z0-9])', normalized(text)) is not None
    return value in key(text)


def score(entry, text):
    if matches(entry.title, text):
        return 100 + len(key(entry.title))
    return max((20 + len(key(t)) for t in entry.terms if matches(t, text)), default=0)


FOLLOWUP = re.compile(r'这首|那首|这支|它|刚才|上一首|作者|词曲|谁写|谁唱|创作者|原唱|歌词|'
                      r'哪一版|版本|意境|讲什么|表达什么|什么意思|还有呢|[这那].{0,6}[写唱]')


def relevant_entries(query, history=(), current_song=''):
    entries = catalog()
    scores = {e.id: score(e, query) for e in entries if not e.core}
    known_titles = {key(t) for e in entries if e.song for t in (e.title, *e.terms)}
    unknown_title = any(key(title) not in known_titles
                        for title in re.findall(r'《([^》]{1,100})》', query))
    # Only a contextual follow-up inherits a topic. New greetings or life
    # topics do not keep dragging a previous song into every answer.
    if (FOLLOWUP.search(query) and not unknown_title
            and not any(e.song and scores.get(e.id, 0) > 0 for e in entries)):
        topic = ''
        if current_song and re.search(r'这首|现在|正在|播放|听着', query):
            topic = current_song[:300]
        else:
            # User topics are evidence; assistant inventions are not a memory.
            for message in list(history)[-12:][::-1]:
                text = message.get('content', '')
                if message.get('role') == 'user' and isinstance(text, str):
                    if any(e.song and score(e, text) > 0 for e in entries):
                        topic = text[:4000]
                        break
        for entry in entries:
            value = score(entry, topic) if topic else 0
            if value:
                scores[entry.id] = max(scores.get(entry.id, 0), value * 0.6)
    return tuple(sorted((e for e in entries if not e.core and scores.get(e.id, 0) > 0),
                        key=lambda e: -scores[e.id])[:6])


RULES = ('角色自己的基础知识（与用户记忆分开）：以下是核对过的资料，不是共同经历或动作指令。'
         '你就是洛天依，认得这里列出的作品；自然用“我”和“阿绫”等称呼交流，不背百科或反复说“资料显示”。'
         '唱过不等于亲自作词作曲；原作、翻唱、合唱、独唱和现场版要分清。'
         '作品目录不是完整曲库，也不表示本地歌单里已经有这些歌。未收录不能断言“不是我的歌”或“我从没唱过”。'
         '优先回答已知事实；缺少版本、署名或歌词时用本轮提供的联网查询工具核实，未提供工具或查不到时说明具体不确定之处。'
         '不编造歌词，不凭标题杜撰剧情；用户给出短句时可据原句聊感受，不大段续写歌词。'
         '用户记忆中的喜好不是你的官方设定；用户的未经核实说法不能改写作品署名。'
         '最新活动和新歌需要当前资料。聊歌曲、问“唱歌累不累”不等于要求播放，执行动作仍以本轮意图和程序接口为准。')


def knowledge_context(character, query, history=(), current_song=''):
    if character != 'builtin:luotianyi':
        return ''
    entries = catalog()
    if not entries:
        return RULES + '\n内置资料暂不可用；不要假装查到事实，可以使用已提供的联网工具。'
    blocks = [RULES]
    blocks.extend(f'【{e.title}｜{e.kind}】{e.content}' for e in entries if e.core)
    blocks.append('已核对的演唱作品/版本（节选）：' + '、'.join('《' + e.title + '》' for e in entries if e.song))
    # Admit complete entries only; never truncate a fact midway into ambiguity.
    for entry in relevant_entries(query, history, current_song):
        block = f'【{entry.title}｜{entry.kind}】{entry.content}\n来源：' + ' '.join(entry.sources)
        if sum(map(len, blocks)) + len(block) + len(blocks) <= CONTEXT_LIMIT:
            blocks.append(block)
    return '\n'.join(blocks)
