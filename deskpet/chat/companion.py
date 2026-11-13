"""UI-independent, fail-closed arbitration for optional proactive companionship.

Call from the UI thread. Invalidate pending tickets on every user interaction,
character change, explicit activity change, and chat request. Never execute model
text; actions are symbolic names resolved by a trusted presentation callback.
"""
from dataclasses import dataclass
import time


PROACTIVE_INTERVAL_KEY = 'companion/proactive_interval_minutes'
DEFAULT_PROACTIVE_INTERVAL = 5
MIN_PROACTIVE_INTERVAL = 1
MAX_PROACTIVE_INTERVAL = 120


def proactive_interval_minutes(value):
    """Read old/malformed settings without enabling a tight request loop."""
    try:
        if isinstance(value, bool):
            return DEFAULT_PROACTIVE_INTERVAL
        return max(MIN_PROACTIVE_INTERVAL, min(MAX_PROACTIVE_INTERVAL, int(value)))
    except (ValueError, TypeError, OverflowError):
        return DEFAULT_PROACTIVE_INTERVAL


def saved_proactive_interval(settings):
    return proactive_interval_minutes(settings.value(PROACTIVE_INTERVAL_KEY, DEFAULT_PROACTIVE_INTERVAL))


@dataclass(frozen=True)
class CompanionState:
    mode: str = 'idle'
    idle_seconds: float = 0.0
    dragging: bool = False
    interacting: bool = False
    chat_busy: bool = False
    has_action: bool = False
    playing: bool = False
    visible: bool = True

    def allows(self, minimum_idle):
        return (self.mode == 'idle' and self.visible
                and self.idle_seconds >= minimum_idle
                and not any((self.dragging, self.interacting, self.chat_busy,
                             self.has_action, self.playing)))


@dataclass(frozen=True)
class CompanionTicket:
    generation: int
    sequence: int


class CompanionCoordinator:
    # Deliberately excludes locomotion, mode changes, computer control and code.
    ACTIONS = frozenset(('happy', 'gentle', 'surprise'))

    def __init__(self, *, enabled=False, cooldown=180.0, minimum_idle=30.0,
                 clock=time.monotonic):
        self.enabled = bool(enabled)
        self.cooldown = max(1.0, float(cooldown))
        self.minimum_idle = max(0.0, float(minimum_idle))
        self.clock = clock
        self._generation = 0
        self._sequence = 0
        self._pending = None
        self._last_request = float('-inf')
        self._delivered = None

    def cancel(self):
        self._generation += 1
        self._pending = self._delivered = None

    def set_enabled(self, enabled):
        if self.enabled != bool(enabled):
            self.enabled = bool(enabled)
            self.cancel()

    def request(self, state):
        now = self.clock()
        if (not self.enabled or self._pending is not None
                or not state.allows(self.minimum_idle)
                or now - self._last_request < self.cooldown):
            return None
        self._sequence += 1
        ticket = CompanionTicket(self._generation, self._sequence)
        self._pending = ticket
        self._delivered = None
        self._last_request = now  # Failures also back off; never spin requests.
        return ticket

    def deliver(self, ticket, state):
        if ticket is None or ticket != self._pending:
            return False
        self._pending = None
        if (not self.enabled or ticket.generation != self._generation
                or not state.allows(self.minimum_idle)):
            return False
        self._delivered = ticket
        return True

    def execute_action(self, ticket, name, state_provider, callback):
        if (ticket is None or ticket != self._delivered or not self.enabled
                or ticket.generation != self._generation or name not in self.ACTIONS):
            return False
        self._delivered = None  # Exactly once, including a rejected late action.
        if not state_provider().allows(self.minimum_idle):
            return False
        callback(name)
        return True


PROACTIVE_PROMPT = (
    '现在是用户允许的空闲陪伴时刻，由你主动发起闲聊，而不是继续回答上一条用户消息。'
    '以当前角色人设的性格、喜好和口吻，自主选择此刻想聊的一个小话题，最多两句。'
    '你可以自然接续旧话题，也可以直接开启与最近对话无关的新话题，两种方式都可以。'
    '已有对话和记忆仅作可选背景，不是本轮选题的限制；不要每次都回顾、总结或追问上次的内容。'
    '可以分享一个符合人设的小念头、轻松的想象或好奇的问题，自然发挥，不用等待旧话题用完才另起话题。'
    '不要反复说“我会陪着你”“一起加油”等通用安慰句，不套用固定开场；'
    '最近主动说过的话只用于避免重复，不要求接续；不要总围绕同一种兴趣或反复索要投喂。'
    '不要催促用户回复，不声称看到了屏幕或知道'
    '用户在做什么，不制造共同经历，不提出任务或操作电脑。可以轻轻哼唱的文字描述，'
    '不要引用现有歌曲歌词。只输出聊天文字，不输出代码、工具调用或动作指令。'
)
