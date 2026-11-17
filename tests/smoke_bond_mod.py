"""Real desktop host and optional package UI, offline with disposable data."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import zipfile
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM']='offscreen'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog
from deskpet.app import Pet
from deskpet.ui.appearance import APPEARANCE_REVISION


class Startup:
    supported=False
    def enabled(self):return False


app=QApplication([])
font_id=QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
families=QFontDatabase.applicationFontFamilies(font_id)
app.setFont(QFont(families[0] if families else 'Microsoft YaHei UI',9))
spec=importlib.util.spec_from_file_location('bond_builder',ROOT/'packaging/build_bond_mod.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
output=ROOT/'local-work/reports/bond-preview';output.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='bond-smoke-') as temp, patch('deskpet.mods.host.QApplication.beep'):
    root=Path(temp)
    with zipfile.ZipFile(builder.build(root/'bond.zip')) as archive:archive.extractall(root/'mod-packages')
    settings=QSettings(str(root/'settings.ini'),QSettings.IniFormat)
    settings.setValue('character_selection','refined')
    settings.setValue('appearance_revision',APPEARANCE_REVISION)
    settings.setValue('random_walk',False)
    pet=Pet(data_dir=root,settings=settings,startup=Startup())
    try:
        host=pet.mod_host
        assert host is not None,pet.mod_startup_error
        assert not host.manager.is_enabled('bond')
        pet.open_mods();window=host.window
        window.enabled.setChecked(True)
        assert host.manager.is_enabled('bond'),host.manager.error('bond')
        widget=window.page_layout.itemAt(0).widget()
        window.resize(760,850);app.processEvents()
        assert window.grab().save(str(output/'daily.png'))
        for destination in ('control','food','music'):
            assert widget.mod.services.present(destination)
            app.processEvents()
            assert widget.mod.store.value['affinity']==0
        pet.toolbar.hide();pet.panel.hide()
        old=pet.panel.store.db.execute('SELECT level,xp FROM pet').fetchone()
        pet.reward_pat()
        pet.panel.store.feed('小包子')
        host.services.emit('chat')
        widget.mod.finish_game('离屏验证',100,1)
        app.processEvents()
        assert pet.panel.store.pet()['stage']=='熟悉'
        assert widget.mod.store.value['affinity']==40
        dialogs=widget.findChildren(QDialog)
        assert any(d.isVisible() for d in dialogs)
        for dialog in dialogs:dialog.close()
        host.services.invoke('bond','rhythm');app.processEvents()
        direct=widget.mod.direct.widget
        assert direct.tabs.currentIndex()==1
        host.services.invoke('bond','album');app.processEvents()
        assert direct.tabs.currentIndex()==2
        book=direct._book_window
        assert book.isVisible() and not widget.mod.direct.isVisible()
        direct.album.canvas.animation.stop();direct.album.canvas._finish();app.processEvents()
        assert book.grab().save(str(output/'album.png'))
        direct.album.set_section('growth')
        direct.album.canvas.animation.stop();direct.album.canvas._finish();app.processEvents()
        assert book.grab().save(str(output/'album-growth.png'))
        direct.album.back.click();app.processEvents()
        assert widget.mod.direct.isVisible()
        direct.tabs.setCurrentIndex(1)
        direct.difficulty.setCurrentIndex(1);direct.input_mode.setCurrentIndex(1)
        direct.play();app.processEvents()
        game=widget.mod.games[-1]
        game.sound.setChecked(False)
        game.elapsed=next((n['at']-.8 for n in game.chart['notes'] if n['type']=='hold'),2.4)
        game.round.combo=20;game.stage.update();app.processEvents()
        assert game.grab().save(str(output/'rhythm.png'))
        pet.toolbar.show();pet.toolbar.adjustSize();app.processEvents()
        assert pet.toolbar.grab().save(str(output/'panel.png'))
        from deskpet.mods.bond.activities import WeeklyShow
        show=WeeklyShow(widget.mod);show.show();app.processEvents()
        assert show.grab().save(str(output/'show.png'));show.close()
        window.enabled.setChecked(False);app.processEvents()
        assert not host.manager.is_enabled('bond')
        import shiboken6
        assert not shiboken6.isValid(game) or (not game.isVisible() and not game.timer.isActive())
        assert tuple(pet.panel.store.db.execute('SELECT level,xp FROM pet').fetchone())==tuple(old)
        assert 'stage' not in pet.panel.store.pet()
        window.enabled.setChecked(True)
        assert pet.panel.store.pet()['affinity']==40
        print('PASS: actual host/UI, first stage presentation, rhythm window, disable cleanup, original growth and Mod save restored')
    finally:
        host.shutdown()
        if host.window:host.window.hide()
        pet.timer.stop();pet.panel.progress_timer.stop()
        pet.panel.bilibili.shutdown();pet.panel.shutdown_audio();pet.close_live2d()
        pet.tray.hide();pet.panel.store.close();pet.panel.hide();pet.hide()
