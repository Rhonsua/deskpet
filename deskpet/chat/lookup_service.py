"""Anonymous public search and lyric retrieval on a cancellable worker thread."""
import html
from html.parser import HTMLParser
import json
import re
import threading
import time
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request, build_opener
import xml.etree.ElementTree as ET

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from .lookup_protocol import safe_link
from .sticker_service import public_url, PublicRedirects


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.fragments = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden += 1
        elif tag in ('p', 'div', 'li', 'br', 'h1', 'h2', 'h3') and not self.hidden:
            self.fragments.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, value):
        if not self.hidden:
            self.fragments.append(value)

    def text(self):
        return '\n'.join(line for part in ''.join(self.fragments).splitlines() if (line := ' '.join(part.split())))


def plain(page):
    parser = PageText()
    parser.feed(page)
    return parser.text()


def parse_rss(page):
    if '<!DOCTYPE' in page.upper():
        return []
    try:
        root = ET.fromstring(page)
    except ET.ParseError:
        return []
    rows = []
    for item in root.findall('.//item'):
        url = item.findtext('link', '')
        if safe_link(url):
            rows.append(dict(title=plain(item.findtext('title', ''))[:160], url=url,
                             text=plain(item.findtext('description', ''))[:700], kind='search_summary'))
    return rows[:5]


def relevant(rows, query):
    terms = [t.casefold() for t in re.split(r'[\s·，。,.？?：:《》"/]+|是什么|什么意思|歌词|含义|设定|资料|查询|搜索|介绍|的', query)
             if len(t) >= 2 and not t.isdecimal()]
    if not terms:
        return rows
    return [row for row in rows if any(term in (row['title'] + ' ' + row['text']).casefold() for term in terms)]


def parse_headings(page):
    """Public result headings and summaries; never use generated AI answers."""
    headings = list(re.finditer(r'<h[23]\b[^>]*>.*?</h[23]>', page, re.I | re.S))
    rows = []
    for index, match in enumerate(headings):
        link = re.search(r'<a\b[^>]*href=["\']([^"\']+)', match[0], re.I)
        if not link:
            continue
        url = html.unescape(link[1])
        if not safe_link(url) or urlsplit(url).hostname == 'ai.so.com':
            continue
        end = headings[index+1].start() if index+1 < len(headings) else match.end()+2400
        rows.append(dict(title=plain(match[0])[:160], url=url,
                         text=plain(page[match.end():min(end, match.end()+5000)])[:700], kind='search_summary'))
    return rows[:8]


class DuckResults(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.capture = False
        self.title = []
        self.url = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and 'result__a' in attrs.get('class', '').split():
            url = attrs.get('href', '')
            if url.startswith('//'):
                url = 'https:' + url
            if urlsplit(url).hostname in ('duckduckgo.com', 'html.duckduckgo.com'):
                url = parse_qs(urlsplit(url).query).get('uddg', [''])[0]
            self.capture, self.title, self.url = True, [], url

    def handle_data(self, value):
        if self.capture:
            self.title.append(value)

    def handle_endtag(self, tag):
        if tag == 'a' and self.capture:
            if safe_link(self.url):
                self.rows.append(dict(title=''.join(self.title)[:160], url=self.url, text='', kind='search_summary'))
            self.capture = False


class LookupSignals(QObject):
    done = Signal(int, object, str)


class LookupJob(QRunnable):
    def __init__(self, ticket, request, local=None):
        super().__init__()
        self.ticket, self.request, self.local = ticket, request, local
        self.stopped = threading.Event()
        self.signals = LookupSignals()
        self.deadline = 0

    def check(self):
        if self.stopped.is_set():
            raise ValueError('查询已取消。')
        if time.monotonic() > self.deadline:
            raise ValueError('查询超时，稍后再试。')

    def fetch(self, url, headers=None):
        self.check()
        public_url(url)
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0 TianyiPet/0.7',
                                       'Accept': 'text/html,application/xml,application/json', **(headers or {})})
        with build_opener(PublicRedirects()).open(request, timeout=min(8, max(1, self.deadline-time.monotonic()))) as response:
            data = bytearray()
            while True:
                self.check()
                chunk = response.read(65536)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > 1024 * 1024:
                    raise ValueError('网页过大，已跳过。')
            charset = response.headers.get_content_charset() or 'utf-8'
            try:
                return data.decode(charset, errors='replace')
            except LookupError:
                return data.decode('utf-8', errors='replace')

    def drive(self, operation):
        try:
            request = next(operation)
            for _ in range(4):
                self.check()
                if urlsplit(request.url).hostname not in ('gateway.kugou.com', 'lyrics.kugou.com') or request.body:
                    raise ValueError('不支持的歌词请求。')
                raw = self.fetch(request.url + '?' + urlencode(request.params), request.headers)
                request = operation.send(json.loads(raw))
        except StopIteration as result:
            return result.value
        finally:
            operation.close()
        raise ValueError('歌词请求次数过多。')

    def lyrics(self):
        from deskpet.music.kugou.service import Service
        from deskpet.music.lyrics.parser import parse_lrc
        service = Service()  # Anonymous; never reuse music account cookies/tokens.
        query = self.request['query']
        result = self.drive(service.search(query))
        norm = lambda text: re.sub(r'[^\w\u4e00-\u9fff]', '', text.casefold())
        q = norm(query)
        tracks = [t for t in result.get('tracks', []) if len(norm(t['title'])) >= 2
                  and (norm(t['title']) in q or q in norm(t['title']))]
        tracks.sort(key=lambda t: (abs(len(norm(t['title']))-len(q)), t['title']))
        if not tracks:
            return []
        track = self.drive(service.song(tracks[0]))
        if not track.get('lrc'):
            return []
        lyrics = parse_lrc(track['lrc'])
        text = lyrics.plain_text or '\n'.join(cue.text for cue in lyrics.cues)
        return [dict(title=track['title'] + ' · ' + track.get('artists', ''),
                     url='https://www.kugou.com/song/#hash=' + track['hash'],
                     kind='lyrics', text=text[:7000])]

    def web(self):
        query = self.request['query'] + (' 歌词' if self.request['kind'] == 'lyrics' else '')
        rows = []
        try:
            rows = relevant(parse_headings(self.fetch('https://www.so.com/s?' + urlencode(dict(q=query)))), self.request['query'])[:5]
        except Exception:
            self.check()
        if not rows:
            try:
                rows = relevant(parse_rss(self.fetch('https://www.bing.com/search?' + urlencode(dict(q=query, format='rss', setlang='zh-hans')))), self.request['query'])
            except Exception:
                self.check()
            if not rows:
                parser = DuckResults()
                parser.feed(self.fetch('https://html.duckduckgo.com/html/?' + urlencode(dict(q=query))))
                rows = relevant(parser.rows[:8], self.request['query'])[:5]
        for row in rows[:2]:
            if time.monotonic() >= self.deadline-2:
                break
            try:
                body = plain(self.fetch(row['url']))
                if body and not any(word in body[:700].casefold() for word in ('verify you are human', '访问验证', '安全验证')):
                    row.update(text=body[:5000], kind='page')
            except Exception:
                if self.stopped.is_set():
                    raise
        return [row for row in rows if row['text']][:4]

    def run(self):
        self.deadline = time.monotonic() + 32
        rows, error = [], ''
        try:
            if self.request.get('current') and self.local:
                rows = [self.local]
            if not rows and self.request['kind'] == 'lyrics':
                try:
                    rows = self.lyrics()
                except Exception:
                    self.check()
            if not rows:
                rows = self.web()
            if self.stopped.is_set():
                raise ValueError('查询已取消。')
            if not rows:
                error = '没有找到可读取的公开资料，可能需要更准确的歌名或关键词。'
        except Exception:
            error = '查询暂时未完成，可能是网络、网站验证或超时；没有取得可用资料。'
        self.signals.done.emit(self.ticket, rows, error)


class LookupService(QObject):
    ready = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ticket = 0
        self.jobs = {}
        self.active = False

    def start(self, request, local=None):
        self.cancel()
        self.active = True
        job = LookupJob(self.ticket, request, local)
        self.jobs[self.ticket] = job
        job.signals.done.connect(self.finished)
        QThreadPool.globalInstance().start(job)

    def finished(self, ticket, rows, error):
        self.jobs.pop(ticket, None)
        if self.active and ticket == self.ticket:
            self.active = False
            self.ready.emit(rows, error)

    def cancel(self):
        self.ticket += 1
        self.active = False
        for job in self.jobs.values():
            job.stopped.set()
