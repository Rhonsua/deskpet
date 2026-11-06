"""Temporary work presentation; never writes the user's saved activity mode."""
import time
import math
from deskpet.pet.behavior import ActionPriority


def preview_active(pet):
    return time.monotonic() < getattr(pet, 'work_preview_until', 0)


def sync_preview_control(pet):
    active = preview_active(pet)
    if not active:
        pet.work_preview_until = 0
    panel = getattr(getattr(pet, 'chat_window', None), 'work_panel', None)
    button = getattr(panel, 'preview_button', None)
    label = '停止预览' if active else '预览工作动作'
    if button is not None and button.text() != label:
        button.setText(label)


def requested(pet):
    panel = getattr(getattr(pet, 'chat_window', None), 'work_panel', None)
    running = bool(panel and panel.is_running and not getattr(panel, 'terminal_state', None))
    return (running and not getattr(pet, 'work_visual_suppressed', False)) or preview_active(pet)


def preempt_automatic(pet):
    """Only discard autonomous presentation; keep manual actions and saved intent."""
    if any(layer.priority <= ActionPriority.AUTOMATIC for layer in pet.behavior.layers):
        pet.stop_roaming()
        pet.behavior.discard_automatic()


def reconcile(pet):
    sync_preview_control(pet)
    panel = getattr(getattr(pet, 'chat_window', None), 'work_panel', None)
    if not panel or not panel.is_running:
        pet.work_visual_suppressed = False
    if requested(pet):
        preempt_automatic(pet)


def idle_parameters(seconds):
    """Breathing and short blinks continue even while approval pauses typing."""
    phase = seconds % 5.3
    blink = (max(0.0, 1 - abs(phase - 1.15) / .12)
             if phase < 2 else max(0.0, 1 - abs(phase - 4.75) / .10))
    return {'ParamWorkBlink': blink,
            'ParamWorkBreath': .5 - .5 * math.cos(seconds * math.tau / 3.8)}


def supported(pet):
    renderer = getattr(pet, 'live2d_renderer', None)
    if renderer is not None:
        return bool(getattr(renderer, 'work_available', False))
    pack = getattr(pet, 'character_pack', None)
    return bool(pack and 'work' in pack.states)


def activity(pet):
    if not supported(pet) or not requested(pet):
        return None
    if (pet.behavior.mode not in ('idle', 'listen') or pet.behavior.layers
            or pet.dragging or pet.petting or pet.press_point is not None
            or pet.playing or pet.dock_edge
            or pet.active_petting.strength > .01):
        return None
    panel = getattr(getattr(pet, 'chat_window', None), 'work_panel', None)
    return 'work-wait' if panel and panel.approval_id is not None else 'work'
