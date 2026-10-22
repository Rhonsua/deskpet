"""Offscreen goal editor integration with isolated SQLite and no host or API."""
import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox
from pet_mods.goals.mod import GoalMod


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    app = QApplication([])
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    families = QFontDatabase.applicationFontFamilies(font_id)
    app.setFont(QFont(families[0] if families else 'Microsoft YaHei UI', 9))
    with tempfile.TemporaryDirectory(prefix='pet-goal-ui-') as directory:
        mod = GoalMod(SimpleNamespace(data_dir=Path(directory), notify=lambda text: False))
        mod.start()
        widget = mod.create_widget()
        widget.resize(800, 650)
        widget.show()
        app.processEvents()
        try:
            assert not widget.has_unsaved_changes()
            assert widget.deadline_input.calendarPopup()
            assert widget.deadline_input.dateTime().toPython() > datetime.now()
            widget.title_input.setText('完成第一首原创歌曲')
            widget.notes_input.setPlainText('先写一小段喜欢的旋律，慢慢来。')
            widget.steps_input.setPlainText('记录灵感\n写主歌\n录一段小样')
            assert widget.has_unsaved_changes()
            widget.save_button.click()
            song_id = widget.current_id
            assert song_id is not None and not widget.has_unsaved_changes()
            assert '0/3' in widget.summary.text() and '尚未记录' in widget.summary.text()
            widget.checklist.item(0).setCheckState(Qt.CheckState.Checked)
            assert mod.store.get(song_id)['steps'][0]['done']
            assert '1/3' in widget.summary.text()
            old_progress = mod.store.get(song_id)['last_progress']
            widget.notes_input.setPlainText('编辑备注不等于推进。')
            widget.steps_input.setPlainText('写主歌\n记录灵感\n重新录制小样')
            widget.save_button.click()
            assert mod.store.get(song_id)['last_progress'] == old_progress
            assert [step['done'] for step in mod.store.get(song_id)['steps']] == [False, True, False]
            with patch.object(mod.store, 'set_step_done', side_effect=sqlite3.OperationalError('test check write failure')):
                widget.checklist.item(0).setCheckState(Qt.CheckState.Checked)
            assert widget.checklist.item(0).checkState() == Qt.CheckState.Checked
            assert widget.has_unsaved_changes() and '未保存' in widget.status.text()
            widget.save_button.click()
            assert mod.store.get(song_id)['steps'][0]['done'] and not widget.has_unsaved_changes()
            widget.checklist.item(0).setCheckState(Qt.CheckState.Unchecked)
            widget.progress_button.click()
            assert [step['done'] for step in mod.store.get(song_id)['steps']] == [False, True, False]
            widget.pause_button.click()
            assert mod.store.get(song_id)['status'] == 'paused' and widget.pause_button.text() == '恢复'
            widget.pause_button.click()
            assert mod.store.get(song_id)['status'] == 'active'
            widget.complete_button.click()
            assert mod.store.get(song_id)['status'] == 'completed'
            widget.complete_button.click()
            assert mod.store.get(song_id)['status'] == 'active'
            widget.snooze_button.click()
            assert mod.store.get(song_id)['snoozed_until'] > datetime.now()
            assert '24 小时' in widget.status.text()
            widget.new_button.click()
            widget.title_input.setText('每周散步两次')
            widget.steps_input.clear()
            widget.notes_input.setPlainText('暂时不拆步骤，只记录最近的推进。')
            widget.save_button.click()
            walk_id = widget.current_id
            assert walk_id != song_id and '未设步骤' in widget.summary.text()
            assert '%' not in widget.summary.text()
            widget.title_input.setText('保存失败也不能丢的草稿')
            with patch.object(mod.store, 'update', side_effect=sqlite3.OperationalError('test disk full')):
                widget.save_button.click()
            assert widget.title_input.text() == '保存失败也不能丢的草稿'
            assert '未保存' in widget.status.text() and widget.has_unsaved_changes()
            # Switching goals restores the unsaved draft, without a database write.
            for row in range(widget.goal_list.count()):
                if widget.goal_list.item(row).data(Qt.ItemDataRole.UserRole) == song_id:
                    widget.goal_list.setCurrentRow(row)
            assert widget.has_unsaved_changes()
            for row in range(widget.goal_list.count()):
                if widget.goal_list.item(row).data(Qt.ItemDataRole.UserRole) == walk_id:
                    widget.goal_list.setCurrentRow(row)
            assert widget.title_input.text() == '保存失败也不能丢的草稿'
            widget.title_input.setText('每周散步两次')
            widget.save_button.click()
            assert not widget.has_unsaved_changes()
            # A background check never rebuilds editor fields or consumes their draft.
            widget.notes_input.setPlainText('尚未保存的临时备注')
            with patch.object(widget, 'refresh_list', side_effect=AssertionError('tick refreshed editor')):
                mod.tick(datetime.now() + timedelta(days=3))
            assert widget.notes_input.toPlainText() == '尚未保存的临时备注'
            widget.save_button.click()
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
                widget.delete_button.click()
            assert mod.store.get(walk_id)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                widget.delete_button.click()
            assert all(goal['id'] != walk_id for goal in mod.store.list_goals())
            assert not widget.has_unsaved_changes()
            for row in range(widget.goal_list.count()):
                if widget.goal_list.item(row).data(Qt.ItemDataRole.UserRole) == song_id:
                    widget.goal_list.setCurrentRow(row)
            app.processEvents()
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                assert widget.grab().save(str(args.screenshot))
            print('PASS: goal UI create/edit/check/progress/pause/reopen/snooze/delete; '
                  'failure and cross-selection draft protection; truthful progress; no tick refresh')
        finally:
            widget.close()
            mod.stop()


if __name__ == '__main__':
    main()
