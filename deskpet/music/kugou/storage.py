import base64,json,re
from datetime import datetime, timedelta
from .service import song_id
from ..netease.storage import Cache as Base, protect

class Cache(Base):
    def settings(self): return '', ''
    def save_session(self,value):
        if not isinstance(value,dict) or not re.fullmatch(r'\d{1,32}',str(value.get('userid',''))) or not isinstance(value.get('token'),str) or not value['token'] or len(value['token'])>4096: raise ValueError('会话无效。')
        payload=protect(json.dumps(value,ensure_ascii=False).encode())
        self.write('session.json',dict(version=1,dpapi=base64.b64encode(payload).decode()))
    def load_session(self):
        try:
            raw=self.read('session.json'); value=json.loads(protect(base64.b64decode(raw['dpapi'],validate=True),True).decode())
            if raw.get('version')!=1 or not isinstance(value,dict) or not re.fullmatch(r'\d{1,32}',str(value.get('userid',''))) or not isinstance(value.get('token'),str) or not value['token']: raise ValueError()
            return value,''
        except FileNotFoundError: return None,''
        except (OSError,ValueError,TypeError,KeyError): return None,'酷狗会话无法解密，请重新扫码。'
    def save_snapshot(self,kind,item_id,data,private=False):
        if kind not in ('song','playlist','collections'): raise ValueError('无效缓存类型。')
        item_id=str(item_id)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',item_id): raise ValueError('无效标识。')
        previous=self.snapshot(kind,item_id,private)
        if previous and previous.get('data',{}).get('complete') is True and data.get('complete') is not True: return False
        self.write(f'{"private" if private else "public"}/{kind}-{item_id}.json',dict(version=1,kind=kind,id=item_id,data=data,fetched_at=datetime.now().isoformat()))
        return True
    def snapshot(self,kind,item_id,private=False,fresh=False):
        if kind not in ('song','playlist','collections') or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',str(item_id)): return None
        try:
            value=self.read(f'{"private" if private else "public"}/{kind}-{item_id}.json')
            if value.get('version') != 1 or value.get('kind') != kind or value.get('id') != str(item_id): return None
            if fresh and datetime.now()-datetime.fromisoformat(value['fetched_at']) > timedelta(hours=24): return None
            return value
        except (OSError,ValueError,KeyError,TypeError): return None
