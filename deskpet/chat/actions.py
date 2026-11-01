"""Trusted dispatch for direct requests and validated API presentation actions."""
from dataclasses import dataclass
import re
import unicodedata


COMMANDS = {
    'music_local': r'(?:播放|切换到|切换成|切到|切回|切|换成|换到|换回|改用)本地(?:的)?(?:歌单|音乐|歌曲|播放)?',
    'music_bilibili': r'(?:播放|切换到|切换成|切到|切回|切|换成|换到|换回|改用)(?:B站|b站|Ｂ站|哔哩哔哩)(?:的)?(?:歌单|音乐|歌曲|播放)?',
    'music_play': r'播放音乐|放首歌|放歌|播放歌单',
    'music_pause': r'暂停(?:音乐|歌曲|播放)|暂停',
    'music_resume': r'继续(?:听歌|播放|音乐)|恢复播放',
    'music_next': r'下一首|切(?:到)?下一首|换(?:一)?首歌',
    'music_previous': r'上一首|切(?:到)?上一首',
    'music_stop': r'停止(?:音乐|播放)|关闭音乐|别放歌了',
    'help': r'你会什么动作|你能做什么动作|动作帮助|有哪些动作',
    'wave': r'挥挥手|挥一下手|挥手|招招手|招手|跟我打个招呼|打个招呼',
    'happy': r'笑一个|笑一笑|笑一下|开心一下',
    'celebrate': r'庆祝一下|庆祝|做个庆祝动作',
    'sleep': r'去睡觉|睡觉|睡一会儿?|躺下睡觉|盖(?:上)?被子睡觉|去休息|休息一下',
    'wake': r'起床|醒醒|醒过来|起来|别睡了|不要睡了',
    'phone': r'玩手机|看手机|躺着玩手机|熬夜玩手机',
    'sing': r'拿(?:起)?麦克风唱歌|拿麦唱歌|唱歌|唱一下|唱(?:一)?首歌|唱个歌|唱给我听',
    'listen': r'收麦|收起麦克风|别唱了|不要唱了|停止唱歌|陪我听歌',
    'turn': r'转个身|转身|侧一下身|侧侧身',
    'eat': r'做个吃东西的动作|吃东西的动作|表演吃东西|吃东西',
    'work': r'做个工作的动作|工作动作|预览工作动作|做个打字的动作|表演打字',
    'stop_work': r'停止工作动作|停止工作预览|停止预览|结束工作动作',
    'stop_action': r'停止动作|停止所有动作|回到待机|回到正常状态',
    'walk_left': r'(?:再)?(?:往|向)?左(?:边)?(?:走一走|走走|走一下|走几步|走|散步|动一点|移一点|挪一点|移动一点|走一点|一点|挪一下|移动一下)',
    'walk_right': r'(?:再)?(?:往|向)?右(?:边)?(?:走一走|走走|走一下|走几步|走|散步|动一点|移一点|挪一点|移动一点|走一点|一点|挪一下|移动一下)',
    'move_up': r'(?:再)?(?:往|向)?上(?:面)?(?:走一点|走一下|动一点|移一点|挪一点|移动一点|一点|挪一下|移动一下|走|移动)',
    'move_down': r'(?:再)?(?:往|向)?下(?:面)?(?:走一点|走一下|动一点|移一点|挪一点|移动一点|一点|挪一下|移动一下|走|移动)',
    'walk': r'散个步|去散步|散步|走一走|走走',
    'stop_walk': r'停下|停一下|停止散步|别走了|不要走了|站住',
    'petting_info': r'摸摸(?:头|你)?|摸摸头|摸头|让我摸摸头',
    'teleport': r'瞬移|瞬移一下',
    'teleport_up': r'(?:再)?(?:(?:往|向)上|(?:往|向)?上瞬移|瞬移到上(?:面|方))',
    'teleport_down': r'(?:再)?(?:(?:往|向)下|(?:往|向)?下瞬移|瞬移到下(?:面|方))',
    'unsupported': r'跳舞|跳个舞|跳一下|翻跟头|转个圈',
}


def recognize_action(text, name='洛天依'):
    """Only whole, direct requests qualify; quotes, stories and negations don't."""
    value = unicodedata.normalize('NFKC', text).strip()
    names = sorted({name, '天依', '洛天依'}, key=len, reverse=True)
    address = '(?:' + '|'.join(re.escape(n) for n in names if n) + ')'
    prefix = rf'(?:{address}[,，、\s]*)?(?:(?:请|麻烦你|能不能|你能不能|可以|你可以|帮我|给我|我想看你|你|先)\s*){{0,3}}'
    suffix = r'(?:一下|一会儿?|吧|呀|啦|哦|好吗|好不好|可以吗|行吗)?[。.!！?？~～\s]*'
    for action, pattern in COMMANDS.items():
        if re.fullmatch(prefix + '(?:' + pattern + ')' + suffix, value):
            return action
    return None


@dataclass(frozen=True)
class ActionResult:
    message: str
    executed: bool = False


def supports(pet, activity):
    renderer = getattr(pet, 'live2d_renderer', None)
    if renderer is not None:
        motions = getattr(renderer, 'motions', None)
        if motions is None:
            return False
        group = motions.group_for(activity)
        return group != 'Idle' and group in motions.references
    state = {'happy': 'happy', 'level_up':'happy', 'eat': 'eat', 'sleep': 'sleep', 'phone': 'phone',
             'sing': 'sing-front', 'turn': 'sing-front'}.get(activity)
    return bool(state and state in getattr(pet, 'scaled_frames', {}))


def available_actions(pet):
    from .action_protocol import ACTIONS
    activities = {'wave':'mouse_wave', 'happy':'happy', 'celebrate':'level_up', 'eat':'eat', 'sleep':'sleep',
                  'phone':'phone', 'sing':'sing', 'turn':'turn'}
    available = []
    for action in ACTIONS:
        if action.startswith('music_'):
            from .music_actions import supported
            if not supported(pet):
                continue
        if action in activities and not supports(pet, activities[action]):
            continue
        if action in ('walk', 'walk_left', 'walk_right') and not pet.walk_supported():
            continue
        if action.startswith('teleport') and not callable(getattr(pet, '_start_teleport', None)):
            continue
        if action == 'work' and not getattr(getattr(pet, 'live2d_renderer', None), 'work_available', False):
            continue
        available.append(action)
    return available


def perform_action(pet, action, parameters=None):
    """Dispatch to existing trusted methods; never execute code, reward or files."""
    if action == 'help':
        from .action_protocol import ACTIONS
        return ActionResult('现在可以做：' + '、'.join(ACTIONS[a] for a in available_actions(pet)) + '。可以直接用自己的话让我做；摸头和拖起仍由鼠标互动控制。')
    if action == 'petting_info':
        return ActionResult('想摸摸头的话，从控制面板点“摸摸”就可以啦，右键退出。')
    from .action_protocol import ACTIONS
    if action == 'unsupported' or action not in ACTIONS:
        return ActionResult('这个动作目前还没有做好呢。可以问我“你会什么动作”。')
    if action.startswith('music_'):
        from .music_actions import perform
        return perform(pet, action, parameters)
    if (not pet.isVisible() or getattr(pet, 'dragging', False)
            or getattr(pet, 'press_point', None) is not None
            or getattr(pet, 'petting', False)
            or getattr(getattr(pet, 'active_petting', None), 'strength', 0) > .01):
        return ActionResult('先等眼前的互动结束，再叫我做这个动作吧。')
    behavior = pet.behavior
    from deskpet.pet.behavior import ActionPriority
    if any(a.priority == ActionPriority.PHYSICAL for a in behavior.layers):
        return ActionResult('等放下后的动作结束，再叫我吧。')
    if action == 'stop_action':
        pet.stop_roaming()
        pet.work_preview_until = 0
        pet.work_visual_suppressed = True
        pet.set_mode('listen' if pet.playing else 'idle')
        from deskpet.animation.work_visual import sync_preview_control
        sync_preview_control(pet)
        running = getattr(getattr(getattr(pet, 'chat_window', None), 'work_panel', None), 'is_running', False)
        return ActionResult('临时动作停好啦，工作页的任务还在继续哦。' if running else '好啦，回到平常的样子。', True)
    if action == 'stop_work':
        from deskpet.animation.work_visual import preview_active, sync_preview_control
        if not preview_active(pet):
            return ActionResult('现在没有工作动作预览；实际工作任务需要在工作页停止哦。')
        pet.work_preview_until = 0
        sync_preview_control(pet)
        pet.update()
        return ActionResult('工作动作预览停好啦。', True)
    if action == 'stop_walk':
        if getattr(getattr(pet, 'teleport_controller', None), 'active', False):
            pet.stop_teleport()
            return ActionResult('停好啦，就在这里陪你。', True)
        if getattr(pet,'chat_move_animation',None) is not None:
            from .movement import stop_move
            stop_move(pet)
            return ActionResult('停好啦，就在这里陪你。',True)
        if getattr(getattr(pet, 'walk_controller', None), 'active', False):
            pet.stop_walk()
            return ActionResult('停好啦，就在这里陪你。', True)
        return ActionResult('我现在没有在散步呀，就在这里陪你。')
    from deskpet.animation.work_visual import preempt_automatic
    preempt_automatic(pet)
    if action.startswith(('walk','move_')) and behavior.activity in ('walk-left','walk-right','move'):
        from .movement import stop_move
        stop_move(pet)
        pet.stop_walk()
    if behavior.layers:
        return ActionResult('我正做着一个动作，等它结束再叫我吧；散步时也可以说“停止散步”。')
    if action == 'work':
        from deskpet.animation.work_visual import preview_active
        if not getattr(getattr(pet, 'live2d_renderer', None), 'work_available', False):
            return ActionResult('当前模型还没有工作动作。')
        if behavior.mode not in ('idle', 'listen') or pet.playing:
            return ActionResult('先叫我起床、暂停音乐，再看工作的动作吧。')
        if not preview_active(pet):
            pet.preview_work_animation()
        return ActionResult('这就摆出认真工作的样子，演示一会儿给你看～', True)
    if action.startswith('teleport'):
        start = getattr(pet, '_start_teleport', None)
        if callable(start) and start(automatic=False, direction={'teleport_up':-1, 'teleport_down':1}.get(action)):
            return ActionResult('烟雾准备好啦，换个位置陪你～', True)
        return ActionResult('现在还不能瞬移，先回到空闲状态，并留出足够的上下空间吧。')
    if action in ('move_up','move_down'):
        from .movement import move_vertical
        if move_vertical(pet,-1 if action=='move_up' else 1):
            return ActionResult('好呀，往'+('上' if action=='move_up' else '下')+'挪一点。',True)
        return ActionResult('现在挪不开啦，可能已经到边缘，或还在休息、听歌。')
    if action.startswith('walk'):
        if not pet.walk_supported():
            return ActionResult('当前这个模型还没有散步动作呢。')
        direction = {'walk_left': -1, 'walk_right': 1}.get(action)
        # Explicit user intent bypasses ONLY automatic roaming cooldown.
        if pet.start_walk(automatic=False, direction=direction, cycles=2, chat_command=True):
            side = {'walk_left': '往左', 'walk_right': '往右'}.get(action, '')
            return ActionResult(f'好呀，我{side}走一小段。', True)
        return ActionResult('现在还走不开呢，先停止听歌、回到空闲状态，离开屏幕边缘并收起其他操作窗口再试试吧。')
    if action in ('wave', 'happy', 'celebrate', 'eat') and (behavior.mode not in ('idle', 'listen') or pet.playing):
        return ActionResult('我现在还在休息或听歌，先叫我醒来、暂停音乐，再做这个小动作吧。')
    if action == 'turn' and behavior.mode not in ('idle', 'listen', 'sing'):
        return ActionResult('先叫我醒来，再转个身给你看吧。')
    activity = {'wave': 'mouse_wave', 'happy': 'happy', 'turn': 'turn',
                'sleep': 'sleep', 'phone': 'phone', 'sing': 'sing', 'eat':'eat', 'celebrate':'level_up'}.get(action)
    if activity and not supports(pet, activity):
        return ActionResult('当前这个模型还没有这个动作，换个动作试试吧。')
    if action in ('wave', 'happy', 'celebrate', 'turn', 'eat'):
        pet.react(activity, seconds=4.8 if action == 'turn' else 2.8 if action == 'eat' else 2.0)
        return ActionResult({'wave': '挥挥手，看见你啦～', 'happy': '嘿嘿，和你待在一起很开心呀。',
                             'turn': '换个角度给你看～', 'celebrate':'好耶，一起庆祝一下！',
                             'eat':'啊呜，表演吃一口～'}[action], True)
    modes = {'sleep': 'sleep', 'wake': 'idle', 'phone': 'phone', 'sing': 'sing', 'listen': 'listen'}
    pet.set_mode(modes[action])
    pet.reveal_dock()
    return ActionResult({'sleep': '被子盖好啦，我先睡一会儿。', 'wake': '醒来啦，继续陪你！',
                         'phone': '那就看一小会儿手机～',
                         'sing': '麦克风拿好啦～我先做唱歌的动作，音乐要从歌单播放哦。',
                         'listen': '麦克风收好啦，安静陪你听歌。'}[action], True)
