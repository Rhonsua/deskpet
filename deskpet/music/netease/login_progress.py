"""The official QR page and an authenticated desktop session are separate steps."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

STATUS = {
    'opening': '正在打开官网的扫码窗口…',
    'page_reloading': '官网正在切换页面，正在重新读取本次登录状态。',
    'open_manually': '官网尚未显示登录框，可点击网页右上角的「登录」。',
    'waiting': '请用手机网易云音乐 App 扫描本窗口的二维码，并在手机上确认登录。',
    'waiting_checked': '官网仍在等待扫描当前二维码。若手机已经确认，可在官网登录框选择「其他登录模式」。',
    'poll_stalled': '二维码仍在显示，但已超过 25 秒没有收到官网的扫码状态。可在此窗口选择「其他登录模式」。',
    'scanned': '官网已收到扫码，请在手机上确认登录。',
    'scan_unconfirmed': '官网已收到扫码，正在等待手机确认结果。也可在此窗口选择官网提供的其他登录方式。',
    'confirmed': '官网已收到手机确认，正在等待网页登录生效。',
    'refresh_after_confirm': '官网已确认，正在刷新一次网页以接回账号。',
    'refresh_account_page': '官网已显示账号，正在重新读取「我的音乐」。',
    'confirmed_no_session': '官网已确认扫码，但「我的音乐」尚未显示登录账号。网页出现头像后，可在桌宠点「重新检测」。',
    'replacement_qr': '官网已更换二维码，请以当前网页的登录提示为准。',
    'site_rejected': '官网扫码请求被拒绝或需要验证，请在网页登录窗口完成验证或刷新二维码后重试。',
    'expired': '官网显示二维码已失效，请在网页登录窗口刷新二维码。',
    'checking': '正在重新检测官方网页登录状态。',
    'credential': '检测到登录凭据，正在官网的「我的音乐」确认当前账号。',
    'verification_session': '官网的「我的音乐」尚未显示登录账号。网页出现头像后，可在桌宠点「重新检测」。',
    'verification_rejected': '网易云暂未允许读取「我的音乐」。请按当前官网窗口的提示完成验证。',
    'verification_network': '官网的「我的音乐」页面暂时无法读取，稍后会重试。',
}

QR_STAGES = {800: 'expired', 801: 'waiting', 802: 'scanned', 803: 'confirmed'}

FAILURE_STEPS = {
    'startup': '启动 WebView2 登录窗口',
    'navigate': '打开网易云官网',
    'page': '读取官网页面',
    'cookie': '读取当前登录窗口的会话',
    'account': '核验网易云账号',
    'handoff': '将已核验的账号交给桌宠',
    'protect': '使用 Windows 加密本次登录',
}


def failure_message(event):
    description = FAILURE_STEPS.get(event.get('step'), '接收本次网页登录')
    location = event.get('at')
    detail = f'（W{location}）' if type(location) is int and 0 < location < 10000 else ''
    return f'网易云登录在「{description}」这一步失败{detail}。'


def record_login_progress(event, directory=None):
    """Retain just the latest public stage, including if the host predates detailed errors."""
    kind = event.get('type')
    if kind not in ('ready', 'status', 'fatal', 'timeout', 'session'):
        return
    data = {'state': kind, 'time': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if event.get('stage') in STATUS:
        data['stage'] = event['stage']
    if kind == 'fatal' and event.get('step') in FAILURE_STEPS:
        data['step'] = event['step']
        line = event.get('at')
        if type(line) is int and 0 < line < 10000:
            data['at'] = line
    temporary = None
    try:
        folder = Path(directory or tempfile.gettempdir())
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder, delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output)
        os.replace(temporary, folder / 'TianyiPet-NetEase-login.json')
    except OSError:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def qr_stage(result):
    if not isinstance(result, dict):
        return None
    code = result.get('code')
    if code in (200, None) and isinstance(result.get('data'), dict):
        code = result['data'].get('code', code)
    if type(code) is not int:
        return None
    return QR_STAGES.get(code, 'site_rejected' if code != 200 else None)


class WebScanProgress:
    def __init__(self):
        self.stage = 'waiting'
        self.since = None
        self.refreshed = None
        self.checked = False
        self.qr_visible_since = None
        self.last_poll = None

    def site_result(self, stage, now):
        if stage == 'new_code':
            self.qr_visible_since, self.last_poll = None, None
        else:
            self.last_poll = now
        self.observe(stage, now)

    def observe(self, stage, now):
        new_code = stage == 'new_code'
        if new_code:
            stage = 'replacement_qr' if self.stage == 'confirmed' else 'waiting'
            self.refreshed = None
            self.checked = False
        elif self.stage == 'confirmed' and stage in ('waiting', 'scanned', 'expired'):
            return
        elif self.stage in ('scanned', 'expired', 'replacement_qr', 'site_rejected') and stage == 'waiting':
            return
        if new_code or stage != self.stage or self.since is None:
            self.stage, self.since, self.checked = stage, now, False

    def without_session(self, now, manual=False, *, verification=None, qr_visible=False):
        """Choose one status until an account is verified, including when a cookie arrived first."""
        self.checked |= manual
        if not qr_visible:
            self.qr_visible_since = None
        elif self.qr_visible_since is None:
            self.qr_visible_since = now
        if self.stage == 'site_rejected' or verification == 'verification_rejected':
            return ('site_rejected' if self.stage == 'site_rejected' else verification), False
        if self.stage == 'confirmed':
            if self.refreshed is None and (now - self.since >= 8 or manual):
                self.refreshed = now
                return 'refresh_after_confirm', True
            if self.refreshed is not None:
                if now - self.refreshed >= 8:
                    return 'confirmed_no_session', False
                return verification or 'refresh_after_confirm', False
        if verification and self.stage not in ('expired', 'replacement_qr') and (not qr_visible or self.stage == 'confirmed'):
            return verification, False
        if self.stage == 'scanned' and (self.checked or now - self.since >= 25):
            return 'scan_unconfirmed', False
        if self.stage == 'waiting' and qr_visible:
            last_update = max(self.qr_visible_since, self.last_poll or 0)
            if now - last_update >= 25:
                return 'poll_stalled', False
        if self.stage == 'waiting' and (self.checked or self.since is not None and now - self.since >= 45):
            return 'waiting_checked', False
        return self.stage, False
