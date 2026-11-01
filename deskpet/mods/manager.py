"""Trusted mod lifecycle and persistent, fail-closed local reminder limits."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import tempfile

from .api import ModContext, ModManifest


_ID = re.compile(r'[a-z][a-z0-9_-]{0,63}')
_DEFAULT_POLICY = dict(sound_enabled=True, quiet_enabled=True, quiet_start=22, quiet_end=8,
                       daily_limit=3, min_interval_minutes=120)


def _valid_id(value):
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _policy(values):
    if not isinstance(values, dict) or set(values) != set(_DEFAULT_POLICY):
        raise ValueError('invalid policy fields')
    if type(values['quiet_enabled']) is not bool or type(values['sound_enabled']) is not bool:
        raise ValueError('sound_enabled and quiet_enabled must be bool')
    for key, lower, upper in [('quiet_start', 0, 23), ('quiet_end', 0, 23),
                              ('daily_limit', 1, 20), ('min_interval_minutes', 1, 1440)]:
        if type(values[key]) is not int or not lower <= values[key] <= upper:
            raise ValueError('invalid policy value')
    return dict(values)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate setting')
        result[key] = value
    return result


class ModManager:
    def __init__(self, data_dir: Path, deliver, clock=datetime.now):
        self.data_dir = Path(data_dir)
        self._deliver = deliver
        self._clock = clock
        self._registry = {}
        self._running = {}
        self._errors = {}
        self._enabled = set()
        self._policy = dict(_DEFAULT_POLICY)
        self._reminders = dict(day=None, count=0, last_sent=None)
        self._closed = False
        self._notify_blocked = False
        self.warning = ''
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.data_dir = self.data_dir.resolve()
            self._load()
        except (OSError, ValueError, RuntimeError):
            self.warning = 'Mod设置无法读取，已使用默认设置；本次运行暂停提醒。'
            self._notify_blocked = True

    def _load(self):
        path = (self.data_dir / 'settings.json').resolve()
        path.relative_to(self.data_dir)
        try:
            with path.open('rb') as file:
                data = file.read(65537)
        except FileNotFoundError:
            return
        try:
            if len(data) > 65536:
                raise ValueError('settings too large')
            raw = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_unique)
            if not isinstance(raw, dict) or set(raw) != {'version', 'enabled', 'policy', 'reminders'}:
                raise ValueError('invalid settings')
            if type(raw['version']) is not int or raw['version'] != 1:
                raise ValueError('unsupported version')
            enabled = raw['enabled']
            if not isinstance(enabled, list) or len(enabled) > 100 or not all(_valid_id(x) for x in enabled) or len(set(enabled)) != len(enabled):
                raise ValueError('invalid enabled ids')
            policy_raw = raw['policy']
            if isinstance(policy_raw, dict) and 'sound_enabled' not in policy_raw:
                policy_raw = dict(policy_raw, sound_enabled=True)
            policy = _policy(policy_raw)
            reminders = raw['reminders']
            if not isinstance(reminders, dict) or set(reminders) != {'day', 'count', 'last_sent'}:
                raise ValueError('invalid reminders')
            if type(reminders['count']) is not int or not 0 <= reminders['count'] <= 20:
                raise ValueError('invalid count')
            if reminders['day'] is not None:
                reminders['day'] = date.fromisoformat(reminders['day']).isoformat()
            if reminders['last_sent'] is not None:
                sent = datetime.fromisoformat(reminders['last_sent'])
                if sent.tzinfo is not None:
                    raise ValueError('local naive time required')
                reminders['last_sent'] = sent.isoformat()
            if reminders['count'] and (reminders['day'] is None or reminders['last_sent'] is None):
                raise ValueError('incomplete reminder state')
            self._enabled = set(enabled)
            self._policy = policy
            self._reminders = dict(reminders)
        except (ValueError, TypeError, RecursionError):
            self.warning = 'Mod设置格式损坏，已恢复默认关闭；本次运行暂停提醒。'
            # A damaged ledger cannot safely prove how many reminders were sent.
            self._notify_blocked = True

    def _save(self):
        temporary = None
        try:
            raw = dict(version=1, enabled=sorted(self._enabled), policy=self._policy,
                       reminders=self._reminders)
            descriptor, temporary = tempfile.mkstemp(prefix='settings-', suffix='.tmp', dir=self.data_dir)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
                json.dump(raw, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.data_dir / 'settings.json')
            return True
        except (OSError, ValueError, TypeError):
            self.warning = 'Mod设置保存失败，请检查本地目录；未确认的更改没有保存成功。'
            return False
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass

    def register(self, manifest: ModManifest, factory):
        if self._closed:
            raise RuntimeError('manager already shut down')
        if (not isinstance(manifest, ModManifest) or not _valid_id(manifest.id)
                or not isinstance(manifest.name, str) or not manifest.name.strip() or len(manifest.name) > 100
                or not isinstance(manifest.version, str)
                or re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}(?:[-+][a-zA-Z0-9.-]+)?', manifest.version) is None
                or len(manifest.version) > 50 or type(manifest.api_version) is not int or manifest.api_version != 1
                or not isinstance(manifest.description, str) or len(manifest.description) > 2000
                or not callable(factory)):
            raise ValueError('invalid mod manifest or factory')
        if manifest.id in self._registry:
            raise ValueError('duplicate mod id')
        self._registry[manifest.id] = (manifest, factory)
        if manifest.id in self._enabled:
            self._activate(manifest.id)

    def manifests(self) -> list:
        return [entry[0] for entry in self._registry.values()]

    def error(self, mod_id) -> str:
        return self._errors.get(mod_id, '')

    def is_enabled(self, mod_id) -> bool:
        return mod_id in self._running and not self._closed

    def _stop(self, mod_id):
        mod = self._running.pop(mod_id, None)
        if mod is not None:
            try:
                mod.stop()
            except Exception as error:
                self._errors[mod_id] = f'停止失败：{type(error).__name__}: {str(error)[:200]}'
                return False
        return True

    def _fault(self, mod_id, phase, error):
        self._enabled.discard(mod_id)
        self._stop(mod_id)
        self._errors[mod_id] = f'{phase}失败：{type(error).__name__}: {str(error)[:200]}'
        self._save()

    def _activate(self, mod_id):
        mod = None
        try:
            path = (self.data_dir / mod_id).resolve()
            path.relative_to(self.data_dir)
            path.mkdir(parents=True, exist_ok=True)
            mod = self._registry[mod_id][1](ModContext(path, lambda text: self._notify(mod_id, text)))
            self._running[mod_id] = mod
            mod.start()
            self._errors.pop(mod_id, None)
            return True
        except Exception as error:
            self._fault(mod_id, '启动', error)
            return False

    def set_enabled(self, mod_id, enabled) -> bool:
        if self._closed or mod_id not in self._registry or type(enabled) is not bool:
            return False
        if enabled:
            if self.is_enabled(mod_id):
                return True
            self._enabled.add(mod_id)
            if not self._save():
                self._enabled.discard(mod_id)
                return False
            return self._activate(mod_id)
        self._enabled.discard(mod_id)
        stopped = self._stop(mod_id)
        saved = self._save()
        return stopped and saved

    def create_widget(self, mod_id, parent=None):
        if not self.is_enabled(mod_id):
            return None
        try:
            return self._running[mod_id].create_widget(parent)
        except Exception as error:
            self._fault(mod_id, '界面', error)
            return None

    def _now(self):
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is not None:
            raise ValueError('clock must return local naive datetime')
        return now

    def tick(self):
        if self._closed:
            return
        try:
            now = self._now()
        except Exception:
            self.warning = '本地时间无法读取，本次暂停Mod更新。'
            return
        for mod_id, mod in list(self._running.items()):
            if not self.is_enabled(mod_id):
                continue
            try:
                mod.tick(now)
            except Exception as error:
                self._fault(mod_id, '更新', error)

    def get_policy(self) -> dict:
        return dict(self._policy)

    def set_policy(self, **values) -> bool:
        if self._closed or not set(values) <= set(_DEFAULT_POLICY):
            return False
        before = self._policy
        try:
            updated = _policy(dict(before, **values))
        except ValueError:
            return False
        self._policy = updated
        if self._save():
            return True
        self._policy = before
        return False

    def _notify(self, mod_id, text):
        if not self.is_enabled(mod_id) or self._notify_blocked or not isinstance(text, str):
            return False
        text = text.strip()
        if (not text or len(text) > 500 or re.search(r'[\x00-\x08\x0b-\x1f\x7f]', text)
                or re.search(r'<\s*/?\s*[a-zA-Z!][^>]*>', text)):
            return False
        try:
            now = self._now()
        except Exception:
            self.warning = '本地时间无法读取，已暂停提醒。'
            return False
        policy = self._policy
        start, end = policy['quiet_start'], policy['quiet_end']
        if policy['quiet_enabled'] and (start == end or
                (start <= now.hour < end if start < end else now.hour >= start or now.hour < end)):
            return False
        before = deepcopy(self._reminders)
        ledger = dict(before)
        today = now.date().isoformat()
        if ledger['day'] is None or today > ledger['day']:
            ledger.update(day=today, count=0)
        if ledger['count'] >= policy['daily_limit']:
            return False
        if ledger['last_sent'] is not None:
            previous = datetime.fromisoformat(ledger['last_sent'])
            if now - previous < timedelta(minutes=policy['min_interval_minutes']):
                return False
        ledger.update(count=ledger['count'] + 1, last_sent=now.isoformat())
        self._reminders = ledger
        # Reserve durably before showing anything: a crash must not reset limits.
        if not self._save():
            self._reminders = before
            self._notify_blocked = True
            return False
        try:
            delivered = self._deliver(text) is True
        except Exception:
            delivered = False
        if not delivered:
            self._reminders = before
            if not self._save():
                self._notify_blocked = True
            return False
        return True

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        changed = False
        for mod_id in list(self._running):
            if not self._stop(mod_id):
                self._enabled.discard(mod_id)
                changed = True
        if changed:
            self._save()
