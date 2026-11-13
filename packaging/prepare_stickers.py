"""Compress generated stickers, preserve alpha, and build the shipped catalogue."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets/stickers'
MOODS = [('hello','你好'),('happy','开心'),('laugh','笑哭'),('shy','害羞'),('love','喜欢'),
         ('hug','抱抱'),('cheer','加油'),('thanks','谢谢'),('puzzled','疑惑'),('thinking','思考'),
         ('shocked','震惊'),('sulk','哼'),('cry','委屈'),('tired','累了'),('sleepy','困困'),
         ('hungry','饿了'),('yum','好吃'),('music','听歌'),('work','努力中'),('bye','晚安')]


def main():
    rows = []
    before = after = 0
    preview = ROOT / 'preview/stickers'
    preview.mkdir(parents=True, exist_ok=True)
    for char, name in (('tianyi','洛天依'), ('aling','乐正绫')):
        sheet = Image.new('RGB', (1000, 920), '#edf4f7')
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 20)
        for index, (mood, title) in enumerate(MOODS):
            source = (ASSETS / char / (mood + '.png')).resolve()
            target = source.with_suffix('.webp')
            if source.exists():
                before += source.stat().st_size
                with Image.open(source) as image:
                    image = image.convert('RGBA')
                    if image.getchannel('A').getextrema()[0] != 0:
                        raise ValueError('Missing transparent background: ' + str(source))
                    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
                    image.save(target, 'WEBP', quality=87, method=6, exact=True)
                with Image.open(target) as verified:
                    verified.load()
                    if verified.mode != 'RGBA' or verified.getchannel('A').getextrema()[0] != 0:
                        raise ValueError('Alpha was lost: ' + str(target))
                if not source.is_relative_to(ASSETS.resolve()):
                    raise ValueError('Unexpected source path')
                source.unlink()  # Original full-size generation remains in Codex's image folder.
            after += target.stat().st_size
            with Image.open(target) as image:
                thumb = image.convert('RGBA')
                thumb.thumbnail((180, 180), Image.Resampling.LANCZOS)
                x, y = (index % 5) * 200, (index // 5) * 230
                for gx in range(0, 200, 16):
                    for gy in range(0, 194, 16):
                        color = '#ffffff' if (gx // 16 + gy // 16) % 2 else '#e0e8ec'
                        draw.rectangle((x + gx, y + gy, x + min(199,gx + 15), y + min(193,gy + 15)), fill=color)
                sheet.paste(thumb, (x + (200-thumb.width)//2, y + (190-thumb.height)//2), thumb)
                draw.text((x+100,y+200), title, font=font, anchor='mt', fill='#254051')
            rows.append(dict(id=char+'_'+mood, file=char+'/'+mood+'.webp', title=title,
                             character=name, verified=True, source=''))
        sheet.save(preview / (char + '-overview.webp'), 'WEBP', quality=90, method=6)
    (ASSETS / 'catalog.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(count=len(rows), original_bytes=before, shipped_bytes=after), ensure_ascii=False))


if __name__ == '__main__':
    main()
