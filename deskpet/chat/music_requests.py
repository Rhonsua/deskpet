"""Whole-request shortcuts for delegated song selection, never assistant prose."""
import re
import unicodedata


def delegated_music(text, name='洛天依'):
    value = unicodedata.normalize('NFKC', text).strip()
    names = '|'.join(re.escape(n) for n in sorted({name, '天依', '洛天依'}, key=len, reverse=True) if n)
    prefix = rf'(?:(?:{names})[,，、\s]*)?(?:(?:请|麻烦你|能不能|你能不能|可以|你可以|帮我|给我|你|先)\s*){{0,3}}'
    suffix = r'(?:给我听听|给我听|让我听听|听听|听一下)?(?:吧|呀|啊|啦|哦|好吗|好不好|可以吗)?[。.!！?？~～\s]*'
    source = r'(?P<source>本地|B站|b站|哔哩哔哩)?(?:的)?'
    patterns = (
        rf'(?:随便|随机)(?:给我)?(?:播放|放|唱|来|挑|选)(?:一)?(?:首歌|首歌曲|首音乐|个歌|首){source}',
        rf'(?:播放|放|唱|来)(?:一)?(?:首歌|首歌曲|首音乐|个歌){source}',
        rf'(?:从|在)?{source}(?:歌单里|歌单中|歌单)?(?:随便|随机)(?:播放|放|唱|来|挑|选)(?:一)?(?:首歌|首歌曲|首音乐|个歌|首)',
        rf'(?:随便|随机)(?:给我)?(?:播放|放|唱|来|挑|选){source}(?:一)?(?:首歌|首歌曲|首音乐|个歌|首)',
        rf'(?:播放|放|来){source}(?:歌|音乐)(?:听听)?',
        rf'(?:挑|选)(?:一)?(?:首歌|首歌曲|首音乐|首){source}(?:播放|放|唱)?',
    )
    for pattern in patterns:
        match = re.fullmatch(prefix + pattern + suffix, value)
        if match:
            selected = match.groupdict().get('source')
            return 'music_random', ({'source': 'local' if selected == '本地' else 'web'} if selected else {})
    # A subjective request goes to the model with actual candidates, never a
    # regex search for a title literally called "适合放松".
    pattern = rf'(?:挑|选|推荐|播放|放|来|唱)(?:一)?首(?P<preference>[^。！？!?\n]{{1,80}}?)(?:的)?(?:歌曲|音乐|歌)(?:来听|来放|播放)?'
    match = re.fullmatch(prefix + pattern + suffix, value)
    if match and re.search(r'适合|喜欢|推荐|好听|开心|快乐|轻松|放松|安静|温柔|治愈|伤感|提神|睡前|现在|心情', match['preference']):
        if not re.search(r'如果|假如|不要|别放|他说|她说|[“”「」《》"\[\]]', value):
            return 'music_pick', {'preference': value[:160]}
    return None
