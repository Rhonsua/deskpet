"""Real Qt mod entry points and delivery, isolated storage and muted system sound."""
import json
import os
import shutil
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings, QDateTime
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox
from main import Pet
from visual_style import APPEARANCE_REVISION
from pet_mods.api import ModManifest


class Startup:
    supported = False
    def enabled(self): return False


app = QApplication([])
font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
fonts = QFontDatabase.applicationFontFamilies(font_id)
if fonts:
    app.setFont(QFont(fonts[0], 9))

with tempfile.TemporaryDirectory(prefix='mods-ui-') as temp, patch('pet_mods.host.QApplication.beep') as beep:
    root = Path(temp)
    package = root / 'mod-packages' / 'goals'
    package.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / 'pet_mods' / 'goals'
    for name in ('__init__.py', 'mod.py', 'store.py', 'widget.py'):
        shutil.copyfile(source / name, package / name)
    (package / 'mod.json').write_text(json.dumps(dict(id='goals', name='目标陪伴', version='0.1.0',
        description='手动记录目标和待办，在临期、逾期或未记录新进展时温柔提醒。', api_version=1)), encoding='utf-8')
    (package / 'entry.py').write_text('from .mod import GoalMod\nfactory = GoalMod\n', encoding='utf-8')
    settings = QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('character_selection', 'refined')
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    pet = Pet(data_dir=root, settings=settings, startup=Startup())
    try:
        host = pet.mod_host
        assert host is not None, pet.mod_startup_error
        assert not host.manager.is_enabled('goals')
        assert not (root / 'mods/goals/goals.db').exists()
        pet.open_mods()
        window = host.window
        assert window.isVisible() and not window.enabled.isChecked()
        assert window.sound.isChecked()
        window.enabled.setChecked(True)
        assert host.manager.is_enabled('goals'), window.status.text()
        editor = window.page_layout.itemAt(0).widget()
        editor.title_input.setText('整理作品集')
        editor.steps_input.setPlainText('选三份作品\n写一段介绍')
        editor.save_button.click()
        assert editor.current_id is not None, editor.status.text()
        mod = editor.mod
        assert len(mod.store.list_goals()) == 1
        now = datetime(2026, 10, 21, 12)
        mod.store.update(editor.current_id, '整理作品集', now - timedelta(hours=1), ['选三份作品', '写一段介绍'])
        editor.deadline_input.setDateTime(QDateTime(now - timedelta(hours=1)))
        editor.refresh_detail()
        before_growth = dict(pet.panel.store.pet())
        with patch.object(host.manager, '_clock', return_value=now):
            # Open tools, sleeping, existing dialogue, dragging and docking stay quiet.
            host.tick()
            assert beep.call_count == 0
            window.hide()
            pet.toolbar.hide()
            pet.panel.hide()
            pet.bubble.hide()
            pet.set_mode('sleep')
            host.tick()
            assert beep.call_count == 0
            pet.set_mode('idle')
            pet.behavior.layers.clear()
            pet.bubble.hide()
            pet.dragging = True
            host.tick()
            pet.dragging = False
            pet.dock_edge = 'left'
            host.tick()
            pet.dock_edge = ''
            assert beep.call_count == 0
            assert mod.store.get(editor.current_id)['last_reminded'] is None
            with patch.object(pet.bubble, 'say', wraps=pet.bubble.say) as say:
                host.tick()
                assert say.call_count == 1 and beep.call_count == 1
                assert '整理作品集' in say.call_args[0][0]
                assert pet.behavior.mode == 'idle' and not pet.behavior.layers
                host.tick()
                assert say.call_count == 1 and beep.call_count == 1
        assert dict(pet.panel.store.pet()) == before_growth
        window.sound.setChecked(False)
        window.save_policy()
        assert host.manager.get_policy()['sound_enabled'] is False
        first = editor.current_id
        mod.store.set_status(first, 'completed', now)
        other = mod.store.create('记录读书想法', now + timedelta(hours=1), now=now)
        pet.bubble.hide()
        with patch.object(host.manager, '_clock', return_value=now + timedelta(hours=3)):
            host.tick()
            assert mod.store.get(other)['last_reminded'] is not None
            assert beep.call_count == 1
        pet.open_mods()
        editor.refresh_list()
        app.processEvents()
        output = Path(__file__).resolve().parents[1] / 'preview'
        output.mkdir(exist_ok=True)
        assert window.grab().save(str(output / 'mods-window.png'))
        window.tabs.setCurrentIndex(1)
        assert window.grab().save(str(output / 'mods-reminders.png'))
        editor.title_input.setText('尚未保存的编辑')
        with patch('pet_mods.window.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as confirm:
            window.enabled.setChecked(False)
            assert confirm.call_count == 1
            assert host.manager.is_enabled('goals') and window.enabled.isChecked()
            assert editor.title_input.text() == '尚未保存的编辑'
        editor.title_input.setText('整理作品集')
        window.enabled.setChecked(False)
        assert not host.manager.is_enabled('goals')
        assert (root / 'mods/goals/goals.db').is_file()
        window.enabled.setChecked(True)
        editor = window.page_layout.itemAt(0).widget()
        assert len(editor.mod.store.list_goals()) == 2
        assert not window.sound.isChecked()
        persisted = json.loads((root / 'mods/settings.json').read_text(encoding='utf-8'))
        assert persisted['policy']['sound_enabled'] is False
        # Optional UI hooks and invalid plugin pages stay inside the host boundary.
        with patch.object(editor, 'has_unsaved_changes', side_effect=ValueError('broken hook')):
            with patch('pet_mods.window.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
                window.enabled.setChecked(False)
                assert host.manager.is_enabled('goals') and window.enabled.isChecked()
        for key, page, expected in [('headless', None, True), ('badui', 42, False)]:
            manifest = ModManifest(key, key, '1.0')
            factory = lambda ctx, page=page: SimpleNamespace(start=lambda: None, stop=lambda: None,
                tick=lambda now: None, create_widget=lambda parent=None: page)
            host.manager.register(manifest, factory)
            window.choice.addItem(key, key)
            window.choice.setCurrentIndex(window.choice.count() - 1)
            window.enabled.setChecked(True)
            assert host.manager.is_enabled(key) is expected
            assert window.enabled.isChecked() is expected
        print('PASS: real mod UI enable/create/persist; state-aware reminders; default sound and mute; no growth changes')
    finally:
        if pet.mod_host:
            pet.mod_host.shutdown()
            if pet.mod_host.window:
                pet.mod_host.window.hide()
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.bilibili.shutdown()
        pet.panel.shutdown_audio()
        pet.close_live2d()
        pet.tray.hide()
        pet.panel.store.close()
        pet.panel.hide()
        pet.hide()
