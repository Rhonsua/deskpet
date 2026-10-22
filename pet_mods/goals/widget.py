"""White, manual-only goal editor. No refresh loop and no network access."""
from datetime import datetime, timedelta
import sqlite3

from PySide6.QtCore import Qt, QDateTime, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                               QListWidgetItem, QLabel, QLineEdit, QPlainTextEdit,
                               QDateTimeEdit, QSpinBox, QPushButton, QFormLayout,
                               QMessageBox, QSplitter)
from ui_theme import apply_light_palette, CONTROL_STYLE


class GoalWidget(QWidget):
    def __init__(self, mod, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.current_id = None
        self.editor_drafts = {}
        self.pending_steps = {}
        self.loading = False
        self.initialized = False
        self.setMinimumHeight(600)
        apply_light_palette(self)
        self.setStyleSheet('QWidget { background: white; color: black; } '
                          'QLineEdit,QPlainTextEdit,QListWidget,QDateTimeEdit,QSpinBox { '
                          'background: white; color: black; border: 1px solid #AFC8D3; padding: 4px; } '
                          'QListWidget::item:selected { background: #EDF6F9; color: black; } '
                          'QLineEdit,QDateTimeEdit,QSpinBox { min-height: 22px; } '
                          'QPushButton { padding: 6px 9px; }' + CONTROL_STYLE)
        outer = QVBoxLayout(self)
        notice = QLabel('进展由你手动记录，不监控屏幕，也不影响桌宠成长。\n'
                        '仅在程序运行且 Mod 启用时检查提醒；睡眠、免扰和每日上限由桌宠统一安排。')
        notice.setWordWrap(True)
        outer.addWidget(notice)
        splitter = QSplitter()
        outer.addWidget(splitter, 1)
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 4, 0)
        self.goal_list = QListWidget()
        self.goal_list.setMinimumWidth(120)
        self.goal_list.currentItemChanged.connect(self.select_goal)
        side.addWidget(self.goal_list)
        self.new_button = QPushButton('新建目标')
        self.new_button.clicked.connect(self.new_goal)
        side.addWidget(self.new_button)
        splitter.addWidget(sidebar)
        detail = QWidget()
        layout = QVBoxLayout(detail)
        layout.setContentsMargins(4, 0, 0, 0)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        form = QFormLayout()
        self.title_input = QLineEdit()
        self.title_input.setMaxLength(120)
        form.addRow('目标', self.title_input)
        self.deadline_input = QDateTimeEdit()
        self.deadline_input.setDisplayFormat('yyyy-MM-dd HH:mm')
        self.deadline_input.setCalendarPopup(True)
        form.addRow('截止时间', self.deadline_input)
        self.stagnation_input = QSpinBox()
        self.stagnation_input.setRange(1, 30)
        self.stagnation_input.setSuffix(' 天未记录新进展后提醒')
        form.addRow('停滞间隔', self.stagnation_input)
        layout.addLayout(form)
        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText('备注（最多 4000 字符；修改备注不计为进展）')
        self.notes_input.setMaximumHeight(65)
        layout.addWidget(self.notes_input)
        layout.addWidget(QLabel('编辑待办：每行一条，最多 50 条，每条 200 字符'))
        self.steps_input = QPlainTextEdit()
        self.steps_input.setMaximumHeight(85)
        layout.addWidget(self.steps_input)
        self.save_button = QPushButton('保存目标与待办')
        self.save_button.clicked.connect(self.save_goal)
        layout.addWidget(self.save_button)
        layout.addWidget(QLabel('已保存的待办：勾选即记录进展'))
        self.checklist = QListWidget()
        self.checklist.itemChanged.connect(self.toggle_step)
        layout.addWidget(self.checklist, 1)
        row = QHBoxLayout()
        self.progress_button = QPushButton('今天推进了')
        self.progress_button.clicked.connect(lambda: self.perform('progress'))
        row.addWidget(self.progress_button)
        self.pause_button = QPushButton('暂停')
        self.pause_button.clicked.connect(lambda: self.perform('pause'))
        row.addWidget(self.pause_button)
        self.complete_button = QPushButton('完成目标')
        self.complete_button.clicked.connect(lambda: self.perform('complete'))
        row.addWidget(self.complete_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.snooze_button = QPushButton('暂缓提醒 1 小时')
        self.snooze_button.clicked.connect(lambda: self.perform('snooze'))
        row.addWidget(self.snooze_button)
        self.delete_button = QPushButton('删除目标')
        self.delete_button.clicked.connect(self.delete_goal)
        row.addWidget(self.delete_button)
        layout.addLayout(row)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        outer.addWidget(self.status)
        self.refresh_list()
        if self.goal_list.count():
            self.goal_list.setCurrentRow(0)
        else:
            self.new_goal()
        self.initialized = True

    def store(self):
        if self.mod.store is None:
            raise ValueError('目标陪伴已停用，请重新启用后再操作。')
        return self.mod.store

    def error(self, error):
        self.status.setText('操作未保存，编辑内容已保留：' + str(error))

    def draft(self):
        return (self.title_input.text(), self.deadline_input.dateTime().toPython(),
                self.steps_input.toPlainText(), self.stagnation_input.value(),
                self.notes_input.toPlainText())

    def remember_draft(self):
        if not self.loading and self.initialized:
            self.editor_drafts[self.current_id] = self.draft()

    def has_unsaved_changes(self):
        if any(self.pending_steps.values()):
            return True
        drafts = dict(self.editor_drafts)
        drafts[self.current_id] = self.draft()
        try:
            for goal_id, draft in drafts.items():
                title, deadline, steps, days, notes = draft
                if goal_id is None:
                    if title.strip() or steps.strip() or notes.strip():
                        return True
                    continue
                goal = self.store().get(goal_id)
                lines = [line.strip() for line in steps.splitlines() if line.strip()]
                if (title.strip(), deadline, lines, days, notes) != (
                        goal['title'], goal['deadline'], [step['text'] for step in goal['steps']],
                        goal['stagnation_days'], goal['notes']):
                    return True
            return False
        except (ValueError, OSError, sqlite3.Error):
            # A failed read must not authorize silently discarding editor contents.
            return True

    def set_draft(self, draft):
        title, deadline, steps, days, notes = draft
        self.title_input.setText(title)
        self.deadline_input.setDateTime(QDateTime(deadline))
        self.steps_input.setPlainText(steps)
        self.stagnation_input.setValue(days)
        self.notes_input.setPlainText(notes)

    def new_goal(self, checked=False, remember=True):
        if remember:
            self.remember_draft()
        self.current_id = None
        with QSignalBlocker(self.goal_list):
            self.goal_list.setCurrentRow(-1)
        self.set_draft(self.editor_drafts.get(None, ('', datetime.now() + timedelta(days=7), '', 2, '')))
        self.refresh_detail()
        self.status.setText('填写目标和截止时间；没有待办时不显示百分比。')
        self.title_input.setFocus()

    def select_goal(self, item, previous):
        if self.loading or item is None:
            return
        self.remember_draft()
        goal_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            goal = self.store().get(goal_id)
            self.current_id = goal_id
            self.set_draft(self.editor_drafts.get(goal_id, (
                goal['title'], goal['deadline'], '\n'.join(step['text'] for step in goal['steps']),
                goal['stagnation_days'], goal['notes'])))
            self.refresh_detail()
            self.status.setText('编辑待办后请保存；勾选状态和“今天推进了”直接保存。')
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)

    def refresh_list(self):
        try:
            goals = self.store().list_goals()
            with QSignalBlocker(self.goal_list):
                self.goal_list.clear()
                for goal in goals:
                    label = {'active': '进行中', 'paused': '暂停', 'completed': '已完成'}[goal['status']]
                    item = QListWidgetItem(goal['title'] + '\n' + label)
                    item.setData(Qt.ItemDataRole.UserRole, goal['id'])
                    self.goal_list.addItem(item)
                    if goal['id'] == self.current_id:
                        self.goal_list.setCurrentItem(item)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)

    def refresh_detail(self):
        goal = self.store().get(self.current_id) if self.current_id is not None else None
        self.loading = True
        try:
            self.checklist.clear()
            if goal:
                for index, step in enumerate(goal['steps']):
                    item = QListWidgetItem(step['text'])
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setData(Qt.ItemDataRole.UserRole, index)
                    done = self.pending_steps.get(self.current_id, {}).get(index, step['done'])
                    item.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
                    self.checklist.addItem(item)
                total = len(goal['steps'])
                done = sum(step['done'] for step in goal['steps'])
                progress = f'步骤 {done}/{total}（{done / total:.0%}）' if total else '未设步骤'
                last = goal['last_progress'].strftime('%m-%d %H:%M') if goal['last_progress'] else '尚未记录'
                self.summary.setText(progress + ' · 最近记录进展：' + last)
            else:
                self.summary.setText('新目标 · 未设步骤')
            for button in (self.progress_button, self.pause_button, self.complete_button,
                           self.snooze_button, self.delete_button):
                button.setEnabled(goal is not None)
            self.pause_button.setText('恢复' if goal and goal['status'] == 'paused' else '暂停')
            self.pause_button.setEnabled(bool(goal and goal['status'] != 'completed'))
            self.complete_button.setText('重新打开' if goal and goal['status'] == 'completed' else '完成目标')
        finally:
            self.loading = False

    def save_goal(self):
        title, deadline, steps, days, notes = self.draft()
        lines = [line for line in steps.splitlines() if line.strip()]
        try:
            store = self.store()
            if self.current_id is None:
                self.current_id = store.create(title, deadline, lines, days, notes=notes)
                self.editor_drafts.pop(None, None)
            else:
                # Retry failed check writes against the saved ordering before editing steps.
                for position, done in list(self.pending_steps.get(self.current_id, {}).items()):
                    store.set_step_done(self.current_id, position, done)
                    self.pending_steps[self.current_id].pop(position, None)
                store.update(self.current_id, title, deadline, lines, days, notes=notes)
            self.editor_drafts.pop(self.current_id, None)
            self.refresh_list()
            self.refresh_detail()
            self.status.setText('目标已保存；编辑名称、备注或时间不会计为进展。')
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)

    def toggle_step(self, item):
        if self.loading or self.current_id is None:
            return
        position = item.data(Qt.ItemDataRole.UserRole)
        done = item.checkState() == Qt.CheckState.Checked
        try:
            self.store().set_step_done(self.current_id, position, done)
            self.pending_steps.get(self.current_id, {}).pop(position, None)
            self.refresh_detail()
            self.status.setText('待办状态已保存。')
        except (ValueError, OSError, sqlite3.Error) as error:
            self.pending_steps.setdefault(self.current_id, {})[position] = done
            self.error(error)

    def perform(self, action):
        if self.current_id is None:
            return
        try:
            store = self.store()
            goal = store.get(self.current_id)
            if action == 'progress':
                store.record_progress(self.current_id)
            elif action == 'pause':
                store.set_status(self.current_id, 'active' if goal['status'] == 'paused' else 'paused')
            elif action == 'complete':
                store.set_status(self.current_id, 'active' if goal['status'] == 'completed' else 'completed')
            elif action == 'snooze':
                store.snooze(self.current_id)
            self.refresh_list()
            self.refresh_detail()
            if action == 'progress':
                self.status.setText('已记录最近进展，步骤进度不变。')
            elif action == 'snooze':
                self.status.setText('已暂缓 1 小时；之后恢复检查，仍受单目标 24 小时冷却和全局提醒间隔约束。')
            else:
                self.status.setText('目标状态已保存。')
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)

    def delete_goal(self):
        if self.current_id is None:
            return
        if QMessageBox.question(self, '删除目标', '删除这个目标和全部待办？此操作不能撤销。') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store().delete(self.current_id)
            self.editor_drafts.pop(self.current_id, None)
            self.pending_steps.pop(self.current_id, None)
            self.current_id = None
            self.refresh_list()
            self.new_goal(remember=False)
            self.status.setText('目标已删除。')
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)
