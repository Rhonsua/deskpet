"""Companion-window glue for independent sticker messages."""
from dataclasses import replace
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices, QPixmap


class StickerChat:
    def init_stickers(self, root):
        from .stickers import StickerCatalog
        from .sticker_service import StickerService
        self.stickers = StickerCatalog(root / 'stickers')
        self.selected_stickers = []
        self.pending_user_stickers = []
        self.sticker_drafts = {}
        self.sticker_search_reply = None
        self.sticker_picker = None
        self.sticker_service = StickerService(self.stickers, self.sticker_config, self)
        self.sticker_service.ready.connect(self.sticker_found)
        self.sticker_service.failed.connect(self.sticker_failed)
        self.sticker_service.status.connect(lambda text: self.status.setText(text) if self.sticker_search_reply else None)

    def sticker_config(self):
        model = self.vision_model_input.text().strip()
        return replace(self.config, model=model or self.config.model)

    def choose_sticker(self):
        if self.pending or self.testing:
            return
        from .sticker_picker import StickerPicker
        if self.sticker_picker:
            self.sticker_picker.close()
            self.sticker_picker.deleteLater()
        picker = self.sticker_picker = StickerPicker(self.stickers, self.sticker_config, self)
        picker.selected.connect(self.attach_sticker)
        picker.sent.connect(self.send_sticker)
        picker.open_at(self.sticker_button)

    def send_sticker(self, key):
        if self.stickers.get(key):
            self.send_message(text='', sticker_ids=[key])

    def attach_sticker(self, key):
        if not self.pending and not self.testing and self.stickers.get(key):
            self.selected_stickers = [key]
            self.update_sticker_draft()
            QTimer.singleShot(0, self.input.setFocus)

    def clear_sticker_draft(self):
        self.selected_stickers = []
        self.update_sticker_draft()

    def update_sticker_draft(self):
        description = self.stickers.describe(self.selected_stickers, self.name)
        item = self.stickers.get(self.selected_stickers[0]) if self.selected_stickers else None
        self.sticker_thumbnail.clear()
        if item:
            self.sticker_thumbnail.setPixmap(QPixmap(str(item.path)).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.sticker_thumbnail.setVisible(bool(item))
        self.sticker_draft.setText((item.title + ' · 与文字一起发送') if item else '')
        self.sticker_draft.setToolTip(description)
        self.sticker_draft.setVisible(bool(description))
        self.sticker_remove.setVisible(bool(description))

    def open_sticker_source(self, url):
        if url.scheme() in ('https', 'http') and not url.userName() and not url.password():
            QDesktopServices.openUrl(url)

    def sticker_found(self, key):
        request, self.sticker_search_reply = self.sticker_search_reply, None
        if request and self.pending == request[:2] and self.character == request[0] and self.companion_mode_enabled:
            from .stickers import SEARCH
            self.on_completed(SEARCH.sub(lambda _: '[表情:' + key + ']', request[2]))

    def sticker_failed(self, error):
        request, self.sticker_search_reply = self.sticker_search_reply, None
        if request and self.pending == request[:2]:
            self.on_failed(error)

    def show_sticker_bubble(self, sticker, text=''):
        show = getattr(self.pet.bubble, 'say_sticker', None)
        if callable(show):
            show(sticker.path, text, 8000)
        else:
            self.pet.bubble.say(text or ('[表情：' + sticker.title + ']'), 8000)
