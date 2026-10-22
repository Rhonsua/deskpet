"""Native Windows click routing against a disposable test button, no user data."""
import ctypes
from ctypes import wintypes
import os

os.environ['QT_QPA_PLATFORM'] = 'windows'
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from music_lyrics.overlay import LyricsOverlay


def main():
    app = QApplication([])
    button = QPushButton('歌词穿透测试窗口')
    button.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    button.resize(620, 180)
    button.move(200, 200)
    button.show()
    button.raise_()
    overlay = LyricsOverlay()
    overlay.set_content('歌词菜单测试', 24, 580)
    overlay.move(220, 250)
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    original = QCursor.pos()
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    try:
        overlay.show()
        overlay.raise_()
        QTest.qWait(200)
        assert overlay.right_click.hook, 'right-click hook not installed'
        rect = wintypes.RECT()
        user32.GetWindowRect(int(overlay.winId()), ctypes.byref(rect))
        assert user32.SetCursorPos((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        QTest.qWait(40)
        position = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(position))
        target = user32.WindowFromPoint(position)
        assert target == int(button.winId()), ('unexpected test target', target, int(button.winId()),
                                               int(overlay.winId()), (position.x, position.y))
        user32.mouse_event(0x2, 0, 0, 0, 0)
        user32.mouse_event(0x4, 0, 0, 0, 0)
        QTest.qWait(150)
        assert clicks == [True], 'left click did not reach underlying button'
        menus = []
        def inspect_menu():
            menu = QApplication.activePopupWidget()
            if menu:
                menus.append([action.text() for action in menu.actions()])
                menu.close()
        QTimer.singleShot(200, inspect_menu)
        user32.mouse_event(0x8, 0, 0, 0, 0)
        user32.mouse_event(0x10, 0, 0, 0, 0)
        QTest.qWait(400)
        assert menus and '隐藏歌词' in menus[0], 'right click failed to open actual lyric menu'
        overlay.set_options('#66ccff', False)
        QTest.qWait(50)
        assert not overlay.right_click.hook
        overlay.set_options('#66ccff', True)
        QTest.qWait(50)
        assert overlay.right_click.hook
        overlay.hide()
        assert not overlay.right_click.hook, 'hidden lyric retained input hook'
        print('PASS: native left click reaches underlying window; right click opens actual menu; hook toggles and stops on hide')
    finally:
        overlay.close()
        button.close()
        QCursor.setPos(original)


if __name__ == '__main__':
    main()
