"""Windows right-click access for an otherwise input-transparent lyric window."""
import ctypes
import sys
import weakref
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication


class RightClickAccess(QObject):
    requested = Signal(int, int)

    def __init__(self, window):
        super().__init__(window)
        self.window = weakref.ref(window)
        self.hook = None
        self.callback = None
        self.pressed = False

    def start(self):
        if self.hook:
            return True
        if sys.platform != 'win32' or QGuiApplication.platformName() != 'windows':
            return False
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        class MouseData(ctypes.Structure):
            _fields_ = [('pt', wintypes.POINT), ('mouseData', wintypes.DWORD),
                        ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                        ('dwExtraInfo', ctypes.c_size_t)]
        self.mouse_data = MouseData
        self.user32.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
        self.user32.SetWindowsHookExW.restype = wintypes.HANDLE
        self.user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self.user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
        self.user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetWindowRect.restype = wintypes.BOOL
        self.callback = callback_type(self._event)
        self.hook = self.user32.SetWindowsHookExW(14, self.callback, None, 0)
        return bool(self.hook)

    def _event(self, code, message, pointer):
        # Left presses, movement, wheel and unrelated right clicks are untouched.
        try:
            if code >= 0 and message in (0x204, 0x205):
                window = self.window()
                if message == 0x205 and self.pressed:
                    self.pressed = False
                    if window is not None and window.isVisible():
                        from PySide6.QtGui import QCursor
                        point = QCursor.pos()
                        self.requested.emit(point.x(), point.y())
                    return 1
                if (message == 0x204 and window is not None and window.isVisible()
                        and not window.menu_open and not window.dialog_open):
                    point = ctypes.cast(pointer, ctypes.POINTER(self.mouse_data)).contents.pt
                    rect = wintypes.RECT()
                    if (self.user32.GetWindowRect(int(window.winId()), ctypes.byref(rect))
                            and rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom):
                        self.pressed = True
                        return 1
        except Exception:
            # Never block unrelated input if the lyric window is being destroyed.
            self.pressed = False
        return self.user32.CallNextHookEx(self.hook, code, message, pointer)

    def stop(self):
        if self.hook:
            self.user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
        self.pressed = False
