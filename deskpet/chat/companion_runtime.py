"""Low-frequency companion runtime, independent of manual chat requests."""
import time
import sqlite3
from PySide6.QtCore import QObject, QTimer
from .remote import ChatClient as RemoteChatClient
from .companion import (CompanionCoordinator, CompanionState, PROACTIVE_PROMPT,
                        PROACTIVE_INTERVAL_KEY, proactive_interval_minutes, saved_proactive_interval)
from .prompts import build_messages, parse_reply
from .scope import response_refusal


class CompanionRuntime(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pet = window.pet
        self.settings = self.pet.panel.settings
        self.enabled = bool(getattr(self.pet, 'companion_enabled', True))
        self.chat_enabled = self.settings.value('companion/proactive_chat', False, type=bool)
        self.actions_enabled = self.settings.value('companion/autonomous_actions', False, type=bool)
        self.coordinator = CompanionCoordinator(enabled=self.enabled,
            cooldown=saved_proactive_interval(self.settings) * 60, minimum_idle=45)
        self.client = RemoteChatClient(self)
        self.client.completed.connect(self._completed)
        self.client.failed.connect(lambda _: self.cancel())
        self.ticket = None
        self.voice_delivery = None
        self.voice_active = False
        self.started = time.monotonic()
        self.last_action = self.started
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(5000)

    def close(self):
        self.timer.stop()
        self.cancel()
        self.client.shutdown()

    @property
    def busy(self):
        return self.ticket is not None

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.coordinator.set_enabled(self.enabled)
        if not self.enabled:
            self.cancel()

    def set_chat_enabled(self, enabled):
        self.chat_enabled = bool(enabled)
        self.settings.setValue('companion/proactive_chat', self.chat_enabled)
        if not enabled:
            self.cancel()

    def set_actions_enabled(self, enabled):
        self.actions_enabled = bool(enabled)
        self.settings.setValue('companion/autonomous_actions', self.actions_enabled)

    def set_chat_interval(self, minutes):
        minutes = proactive_interval_minutes(minutes)
        self.settings.setValue(PROACTIVE_INTERVAL_KEY, minutes)
        # Reuse the last request timestamp. Changing the interval neither
        # restarts the countdown nor cancels a reply/voice already in flight.
        self.coordinator.cooldown = minutes * 60

    def release_voice(self):
        delivery = self.voice_delivery
        if delivery is not None:
            delivery()
        self.voice_active = False

    def cancel(self):
        if self.voice_delivery is not None or self.voice_active:
            self.window.speech.stop(preserve_warm=True)
        self.voice_delivery = None
        self.voice_active = False
        self.started = time.monotonic()
        self.coordinator.cancel()
        self.ticket = None
        self.client.cancel()

    def on_interaction(self):
        """Movement/petting can coexist with speech already accepted for delivery."""
        self.started = time.monotonic()
        if self.voice_delivery is not None or self.voice_active:
            return
        self.cancel()

    def state(self):
        pet, window = self.pet, self.window
        behavior = pet.behavior
        idle = time.monotonic() - max(self.started, getattr(pet, 'last_user_interaction', self.started))
        return CompanionState(mode=behavior.mode, idle_seconds=idle,
            dragging=bool(getattr(pet, 'dragging', False)),
            interacting=bool(getattr(pet, 'press_point', None) is not None
                             or getattr(pet, 'petting', False)
                             or getattr(pet, 'dock_edge', '')
                             or pet.panel.isVisible() or pet.toolbar.isVisible()
                             or window.isVisible()
                             or pet.bubble.isVisible()),
            chat_busy=bool(window.pending or window.testing or window.input.toPlainText().strip()
                           or not getattr(window, 'companion_mode_enabled', True)
                           or getattr(getattr(window, 'work_panel', None), 'is_running', False)),
            has_action=bool(behavior.layers), playing=bool(getattr(pet, 'playing', False)),
            visible=pet.isVisible())

    def tick(self):
        if not self.enabled or getattr(self.window, 'closed', False):
            return
        state = self.state()
        if not state.allows(45):
            if self.busy:
                self.on_interaction()
            return
        now = time.monotonic()
        if self.actions_enabled and not self.busy and now - self.last_action >= 90:
            self.last_action = now
            if self.state().allows(45):
                self.pet.react('happy', seconds=1.4, automatic=True)
            return
        if not self.chat_enabled or self.busy:
            return
        try:
            self.window.config.validate()
            ticket = self.coordinator.request(state)
            if ticket is None:
                return
            self.ticket = ticket
            self.character = self.window.character
            catalog = getattr(self.window, 'stickers', None)
            history = self.window.store.history(self.character, 12)
            if catalog is not None:
                history = catalog.history_for_api(history, self.window.name)
            messages = build_messages(self.window.persona_input.toPlainText(),
                self.window.memory_input.toPlainText(),
                history, PROACTIVE_PROMPT,
                '当前为空闲陪伴时刻，可以自主开启新话题。以下最近主动发言只用于避免重复，不要求接续：'
                + self.window.store.last_proactive(self.character), personality=self.window.personality,
                recalled=self.window.memory_context(proactive=True), character=self.character)
            if catalog is not None:
                messages[0]['content'] += catalog.instruction(self.window.name, online=False)
            self.client.start(self.window.config, messages)
        except (ValueError, RuntimeError, sqlite3.Error):
            self.cancel()

    def _completed(self, text):
        ticket = self.ticket
        if (ticket is None or self.window.character != getattr(self, 'character', None)
                or not self.enabled or not self.chat_enabled or not self.state().allows(45)):
            self.cancel()
            return
        from .stickers import reply_parts, text_from_parts
        catalog = getattr(self.window, 'stickers', None)
        parts, search, error = reply_parts(text, catalog)
        keys = [p['id'] for p in parts if p['type'] == 'sticker']
        sticker = catalog.get(keys[-1]) if keys else None
        visible = text_from_parts(parts)
        if search or error or (keys and '[动作:' in text):
            self.cancel()
            return
        if (not visible and not sticker) or response_refusal(visible):
            self.cancel()
            return
        visible = visible[:240]
        accepted_state = self.state()
        def delivery():
            if self.voice_delivery is not delivery or self.ticket != ticket:
                return False
            self.voice_delivery = None
            self.ticket = None
            if (not self.enabled or not self.chat_enabled or self.window.closed
                    or self.window.character != self.character
                    or not self.coordinator.deliver(ticket, accepted_state if self.voice_active else self.state())):
                self.coordinator.cancel()
                return False
            try:
                self.window.store.add_proactive(self.character, visible + (' [表情：' + sticker.description(self.window.name) + ']' if sticker else ''))
            except sqlite3.Error:
                self.cancel()
                return False
            if sticker:
                self.window.show_sticker_bubble(sticker, visible)
            else:
                self.pet.bubble.say(visible, 8000)
            return True
        self.voice_delivery = delivery
        if visible and self.window.reply_voice_enabled():
            self.voice_active = True
            if self.window.speech.speak(visible, deliver=delivery):
                return
            self.voice_active = False
        delivery()
