"""Bounded account verification outside the page's JavaScript environment."""
import json
import hashlib
import queue
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .direct import prepare_request


class AccountProbe:
    """One background request at a time; results belong to an exact cookie set."""
    def __init__(self, verify=None):
        self.verify = verify or verify_browser_cookie
        self.results = queue.Queue()
        self.busy = False
        self.next_attempt = 0
        self.fingerprint = None

    def poll(self, cookie, retry=False):
        fingerprint = hashlib.sha256(cookie.encode()).digest()
        if retry or fingerprint != self.fingerprint:
            self.next_attempt = 0
            self.fingerprint = fingerprint
        try:
            owner, profile, stage = self.results.get_nowait()
            self.busy = False
            if owner == fingerprint:
                return profile, stage
        except queue.Empty:
            pass
        if not self.busy and time.monotonic() >= self.next_attempt:
            self.busy = True
            self.next_attempt = time.monotonic() + 15
            def work():
                try:
                    profile, stage = self.verify(cookie)
                except Exception:
                    profile, stage = None, 'verification_response'
                self.results.put((fingerprint, profile, stage))
            threading.Thread(target=work, daemon=True).start()
            return None, 'verification_native'
        return None, None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify_browser_cookie(cookie):
    """Return only verified identity + a fixed diagnostic, never raw responses."""
    try:
        address, values, header = prepare_request(
            'https://music.163.com/api/w/nuser/account/get', {}, cookie)
        request = Request(address, data=urlencode(values).encode('ascii'), headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json', 'Referer': 'https://music.163.com/',
            'User-Agent': 'Mozilla/5.0', 'Cookie': header,
        })
        # No cookie jar, no redirects and normal system certificate checks.
        with build_opener(NoRedirect()).open(request, timeout=8) as response:
            raw = response.read(256 * 1024 + 1)
            if response.status != 200 or len(raw) > 256 * 1024:
                return None, 'verification_response'
        result = json.loads(raw)
        if not isinstance(result, dict):
            return None, 'verification_response'
        data = result.get('data') if isinstance(result.get('data'), dict) else result
        code = result.get('code', data.get('code'))
        if code in (301, 401):
            return None, 'verification_session'
        if code != 200:
            return None, 'verification_rejected'
        profile = data.get('profile')
        if not isinstance(profile, dict):
            return None, 'verification_session'
        uid = str(profile.get('userId', ''))
        if not uid.isascii() or not uid.isdigit() or not 0 < len(uid) <= 19 or uid.startswith('0'):
            return None, 'verification_response'
        nickname = profile.get('nickname')
        return dict(userId=uid, nickname=nickname[:200] if isinstance(nickname, str) else ''), 'verified'
    except HTTPError:
        return None, 'verification_rejected'
    except (URLError, TimeoutError, OSError):
        return None, 'verification_network'
    except Exception:
        return None, 'verification_response'
