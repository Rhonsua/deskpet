"""Versioned event and presentation bridge. No package receives the pet object."""
from types import SimpleNamespace
from copy import deepcopy
import time


class InteractionServices:
    def __init__(self, host):
        self.host = host
        self.listeners = {}
        self.memories = {}
        self.growth_owner = None
        self.panels = {}
        self.shops = {}
        self.audio_owner = None

    def for_mod(self, owner):
        return SimpleNamespace(version=3, subscribe=lambda cb: self.subscribe(owner, cb),
            snapshot=self.snapshot, growth=lambda cb: self.growth(owner, cb),
            companion_context=lambda cb: self.memories.update({owner:cb}),
            panel=lambda summary, actions: self.register_panel(owner, summary, actions),
            library=self.library, analysis=lambda parent: self.analysis(owner, parent),
            audio_claim=lambda: self.audio_claim(owner),
            audio_valid=lambda token: self.audio_owner == (owner, token),
            audio_release=lambda token: self.audio_release(owner, token),
            audio_route=self.audio_route,
            shop=lambda catalog: self.shops.update({owner:dict(catalog)}),
            buy=lambda item: self.buy(owner,item), owned=lambda: self.owned(owner),
            present=lambda destination: self.present(owner,destination),
            act=lambda action: self.act(owner, action))

    def present(self, owner, destination):
        """Open a host-owned entrance after an explicit Mod UI click; never award it."""
        if not self.host.manager.is_enabled(owner) or destination not in ('control','food','chat','music'):
            return False
        pet=self.host.pet
        if destination=='chat':
            pet.open_chat()
            return getattr(pet,'chat_window',None) is not None
        if destination=='music':
            pet.open_tools(0)
            return True
        # Head-petting still starts only at the original control-panel button.
        # Calling toggle() on an already-visible toolbar would close it instead.
        from deskpet.pet.desktop import clamp_near
        pet.stop_roaming();pet.reveal_dock()
        pet.toolbar.page('food' if destination=='food' else 'home')
        clamp_near(pet,pet.toolbar)
        pet.toolbar.show();pet.toolbar.raise_()
        pet.toolbar.close_timer.start(12000)
        return True

    def subscribe(self, owner, callback):
        if not callable(callback):
            raise ValueError('互动监听必须可调用')
        self.listeners.setdefault(owner, []).append(callback)

    def release(self, owner):
        self.listeners.pop(owner, None)
        self.memories.pop(owner, None)
        self.panels.pop(owner, None)
        self.shops.pop(owner, None)
        if self.audio_owner and self.audio_owner[0] == owner:self.audio_owner = None
        if self.growth_owner == owner:
            self.host.pet.panel.store.growth_provider = None
            self.growth_owner = None

    def register_panel(self, owner, summary, actions):
        if not callable(summary) or not isinstance(actions,dict):raise ValueError('主面板入口无效')
        if len(actions)>12:raise ValueError('主面板入口过多')
        if any(not isinstance(k,str) or not isinstance(v,tuple) or len(v)!=2 or not isinstance(v[0],str)
               or not callable(v[1]) for k,v in actions.items()):raise ValueError('主面板操作无效')
        self.panels[owner] = (summary,dict(actions))

    def panel_items(self):
        result=[]
        for owner,(summary,actions) in list(self.panels.items()):
            if self.host.manager.is_enabled(owner):
                try:result.append((owner,str(summary())[:300],actions))
                except Exception as error:self.host.manager._fault(owner,'主面板',error)
        return result

    def invoke(self, owner, key):
        if not self.host.manager.is_enabled(owner) or owner not in self.panels:return
        try:self.panels[owner][1][key][1]()
        except Exception as error:self.host.manager._fault(owner,'功能入口',error)

    def library(self):
        from pathlib import Path
        library=getattr(self.host.pet.panel,'library',None)
        seen=set();result=[]
        for playlist in getattr(library,'playlists',[]):
            for path in playlist.get('paths',[]):
                key=str(Path(path).absolute())
                if key.casefold() not in seen:
                    seen.add(key.casefold());result.append(dict(path=key,title=Path(key).stem))
        return result

    def analysis(self, owner, parent):
        from deskpet.music.beats.controller import BeatController
        return BeatController(self.host.manager.data_dir/owner/'analysis',parent)

    def audio_claim(self, owner):
        from uuid import uuid4
        if not self.host.manager.is_enabled(owner) or self.snapshot()['playing'] or self.audio_owner:return None
        token=uuid4().hex;self.audio_owner=(owner,token);return token

    def audio_release(self, owner, token):
        if self.audio_owner == (owner,token):self.audio_owner=None

    def audio_route(self,audio,parent):
        from deskpet.music.audio.routing import AudioRouter
        router=AudioRouter(audio,self.host.pet.panel.settings,parent);router.refresh()
        return router

    def buy(self, owner, item):
        if not self.host.manager.is_enabled(owner):return False,'扩展未启用'
        cost=self.shops.get(owner,{}).get(item)
        if type(cost) is not int or not 0<=cost<=10000:return False,'这个装饰暂不可用'
        return self.host.pet.panel.store.mod_purchase(owner,item,cost)

    def owned(self, owner):
        return self.host.pet.panel.store.mod_owned(owner)

    def emit(self, kind, data=None):
        data = dict(data or {})
        if kind == 'listen':
            data['title'] = self.host.pet.panel.song_title.text()
            try:
                from deskpet.music.tools.clock import playback_snapshot
                track=playback_snapshot(self.host.pet.panel)
                if track.valid and track.playing:
                    data['track']=dict(source=track.source_key,position=track.position_ms/1000,duration=track.duration_ms/1000)
            except AttributeError:pass
        for owner, callbacks in list(self.listeners.items()):
            if not self.host.manager.is_enabled(owner):
                continue
            for callback in list(callbacks):
                try:
                    callback(kind, deepcopy(data or {}))
                except Exception as error:
                    self.host.manager._fault(owner, '互动事件', error)
                    break

    def growth(self, owner, callback):
        if self.growth_owner not in (None, owner):
            raise ValueError('已有另一个成长扩展启用，请先停用它')
        self.growth_owner = owner
        def projection():
            try:
                value = callback()
                if (not isinstance(value, dict) or not set(value) <= {'level','xp','xp_goal','stage','affinity','growth_label'}
                        or any(type(value.get(key)) is not int for key in ('level','xp','xp_goal'))
                        or not 1 <= value['level'] <= 100
                        or not 1 <= value['xp_goal'] <= 1000000000
                        or not 0 <= value['xp'] <= value['xp_goal']
                        or any(key in value and (not isinstance(value[key],str) or len(value[key])>100)
                               for key in ('stage','growth_label'))
                        or ('affinity' in value and (type(value['affinity']) is not int or not 0<=value['affinity']<=1000000000))):
                    raise ValueError('成长显示数据无效')
                return value
            except Exception as error:
                self.host.manager._fault(owner, '成长显示', error)
                return {}
        self.host.pet.panel.store.growth_provider = projection

    def memory_context(self):
        values = []
        for owner, callback in list(self.memories.items()):
            if self.host.manager.is_enabled(owner):
                try:values.append(str(callback())[:1200])
                except Exception as error:self.host.manager._fault(owner, '回忆读取', error)
        return '\n'.join(values)[:2400]

    def snapshot(self, *, music=False):
        pet, panel = self.host.pet, self.host.pet.panel
        work = getattr(getattr(pet, 'chat_window', None), 'work_panel', None)
        companion = getattr(pet, 'music_companion', None)
        beats = getattr(companion, 'beats', None)
        return dict(character=pet.character_name, busy=bool(pet.dragging or pet.petting or pet.behavior.layers
            or getattr(pet, 'dock_edge', None) or getattr(pet, 'press_point', None) is not None
            or time.monotonic() < getattr(pet, 'work_preview_until', 0)
            or pet.behavior.mode not in ('idle', 'listen') or getattr(work, 'is_running', False)),
            playing=bool(pet.playing), title=panel.song_title.text(),
            hunger=panel.store.pet()['hunger'], notes=panel.store.pet()['notes'],
            local_path=str(panel.current_path() or '') if panel.playback_source == 'local' else '',
            volume=panel.volume.value() / 100,
            beat_source=getattr(beats, 'source', ''), beats=deepcopy(getattr(beats, 'analysis', {})) if music else {},
            state=pet.behavior.activity)

    def act(self, owner, action):
        if not self.host.manager.is_enabled(owner) or self.snapshot()['busy']:
            return False
        activities = {'wave':'mouse_wave', 'happy':'happy', 'turn':'turn', 'celebrate':'level_up', 'sing':'sing'}
        if action not in activities:
            return False
        pet = self.host.pet
        from deskpet.chat.actions import supports
        if not supports(pet, activities[action]):
            return False
        pet.react(activities[action], seconds=2.0, automatic=True)
        return True
