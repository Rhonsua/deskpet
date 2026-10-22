"""Local goal companion: no network, screen monitoring, or automatic progress."""
from datetime import datetime, timedelta
import sqlite3

from pet_mods.api import ModManifest
from .store import GoalStore, timestamp


MANIFEST = ModManifest('goals', '目标陪伴', '0.1.0',
                       '手动记录目标和待办，在临期、逾期或未记录新进展时温柔提醒。')


class GoalMod:
    def __init__(self, context):
        self.context = context
        self.store = None
        self.last_error = ''
        self._delivered = {}

    def start(self):
        if self.store is None:
            self.context.data_dir.mkdir(parents=True, exist_ok=True)
            self.store = GoalStore(self.context.data_dir / 'goals.db')
        self.last_error = ''

    def stop(self):
        if self.store is not None:
            self.store.close()
            self.store = None

    def tick(self, now: datetime):
        if self.store is None:
            return
        try:
            timestamp(now)
            candidates = []
            for goal in self.store.list_goals():
                if goal['status'] != 'active':
                    continue
                if goal['snoozed_until'] and now < goal['snoozed_until']:
                    continue
                reminders = [value for value in (self._delivered.get(goal['id']), goal['last_reminded']) if value]
                last_reminded = max(reminders) if reminders else None
                if last_reminded and now - last_reminded < timedelta(hours=24):
                    continue
                delta = goal['deadline'] - now
                if delta.total_seconds() <= 0:
                    priority, reason = 0, '截止时间已经到了。想调整计划，或者先挑一件小事做吗？'
                elif delta <= timedelta(hours=24):
                    priority, reason = 1, '将在 24 小时内到期。愿意看一眼下一步，或调整时间吗？'
                elif now - max(goal['last_progress'] or goal['created_at'], goal['resumed_at']) >= timedelta(days=goal['stagnation_days']):
                    priority, reason = 2, f'已经 {goal["stagnation_days"]} 天未记录新进展了。这不代表你没有努力，要不要记下最近做过的小事？'
                else:
                    continue
                candidates.append((priority, goal['deadline'], goal['id'], reason, goal))
            if not candidates:
                return
            _, _, _, reason, goal = min(candidates, key=lambda item: item[:3])
            if self.context.notify('目标「' + goal['title'] + '」' + reason):
                self._delivered[goal['id']] = now
                self.store.mark_reminded(goal['id'], now)
            self.last_error = ''
        except (ValueError, OSError, sqlite3.Error) as error:
            self.last_error = '目标提醒暂时无法保存：' + str(error)
            raise

    def create_widget(self, parent=None):
        if self.store is None:
            raise ValueError('请先启用目标陪伴。')
        from .widget import GoalWidget
        return GoalWidget(self, parent)
