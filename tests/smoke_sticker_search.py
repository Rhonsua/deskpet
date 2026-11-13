"""Small opt-in public search check; no account, key or model call."""
import sys
import json
import threading
from pathlib import Path
from urllib.parse import quote_plus, urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deskpet.chat.sticker_service import fetch_public, search_urls, baidu_urls


if __name__ == '__main__':
    query = quote_plus('洛天依 开心 表情包')
    for name, url, parse in (
        ('baidu', 'https://image.baidu.com/search/acjson?tn=resultjson_com&ipn=rj&ie=utf-8&oe=utf-8&pn=0&rn=12&word=' + query, baidu_urls),
        ('bing', 'https://www.bing.com/images/search?q=' + query, search_urls)):
        try:
            data = fetch_public(url, 2 * 1024 * 1024, threading.Event())
            urls = parse(data.decode('utf-8', 'replace'))
            print(json.dumps(dict(provider=name, candidates=len(urls), hosts=[urlsplit(u).hostname for u in urls[:3]])))
        except Exception as error:
            print(json.dumps(dict(provider=name, error=type(error).__name__)))
