"""Local companion boundaries, deliberately limited to explicit task patterns.

These rules complement prompts; they do not understand every paraphrase or language.
History filtering returns copies and never changes the conversation database.
"""
import re
import unicodedata


_MATH_REFUSAL = '[温柔]这道题我不太会解呀，就不装作懂了。做累了的话，我陪你歇一会儿。'
_CODE_REFUSAL = '[温柔]写程序我不太在行呀，怕越帮越忙。你忙累了的话，我可以陪你聊聊。'


def _normal(text):
    return unicodedata.normalize('NFKC', text).lower().strip()


_MATH = r'(?:积分|求导|导数|微分方程|定理|猜想|证明题|极限|矩阵|行列式|试卷|考试题)'
_ACTION = r'(?:帮.{0,6}(?:算|求|做|解(?!释)|证明)|求解|计算|算出|解答|解一下|做一下|求一下|求(?:这个|下)?(?:积分|极限)|证明一下|证明|求导|给.{0,8}(?:答案|步骤|解法)|写.{0,6}(?:答案|解法)|推导)'
_CODE = r'(?:代码|程序|脚本|爬虫|python|javascript|typescript|java\b|c\+\+|sql\b|rust\b|bug\b)'
_CODE_ACTION = r'(?:写(?:个|一个|段|一段)?|编写|实现|调试|修复|修改|排查|检查|解决|帮.{0,8}(?:改|看|查|修)|debug|implement|write|fix)'
_CODE_REQUEST = re.compile(r'(?:(?:帮我|请|能不能|可以)(?:再|先|一下|给我|帮我)?\s*(?:写|编写|实现|调试|修复|修改|排查|检查|解决|改|看看|看一下|查|修)|给我\s*(?:写|编写|实现|调试|修复)|怎么(?:写|改|修)|\b(?:write|fix|debug|implement)\b)')
_CONCEPT = re.compile(r'(?:是什么|什么意思|什么是|什么叫|有什么用|表示什么|代表什么|含义|概念)')
_CONTINUE = re.compile(r'^(?:请|那|再|接着|你)?\s*(?:继续(?:算|做|推导|求解|解|写|调试)?(?:一下|下去)?|给(?:我|出)?(?:详细)?(?:步骤|答案|解法)|详细步骤|答案呢|怎么算|怎么解)[呀啊吧呢嘛?？!！。\s]*$')
_FORMULA = re.compile(r'(?:\\int\b|\\int(?=[_^\s{0-9a-z])|∫)')


def _direct_task(text):
    # A concept question about notation is ordinary conversation, unless an
    # additional explicit solving request is present.
    concept = bool(_CONCEPT.search(text))
    explicit = bool(re.search(_ACTION, text))
    if re.search(r'^(?:please\s+)?(?:integrate|differentiate)\s+(?:[a-z]\b|sin\b|cos\b|exp\b|\\)', text):
        return True
    service = bool(re.search(r'(?:(?:帮|请|能不能).{0,8}(?:算|求|做题|解(?!释)|证明|推导|写|调试|修复|改代码)|给.{0,6}(?:答案|步骤|解法)|求这个|算一下|解一下)', text))
    if not concept and re.search(r'(?:^|[，。,:：])\s*(?:求导|求解|证明|计算|解微分方程)(?!(?:真的|实在|真|太)?(?:好烦|好难|好累|学不会|学不懂|听不懂|难受))', text):
        service = True
    emotional = bool(re.search(r'(?:学不会|不会学|好烦|好难|学不懂|听不懂|好累|崩溃|难受)', text))
    concept_task = bool(re.search(r'(?:(?:帮我|请|能不能)\s*(?:算|求导|求解|求这个|求一下|证明|推导)|给.{0,6}(?:答案|步骤|解法)|求这个|算一下|解一下)', text))
    code_requested = bool(re.search(_CODE, text) and _CODE_REQUEST.search(text))
    if concept and not concept_task and not code_requested:
        return False
    if emotional and not service and not _FORMULA.search(text):
        return False
    if _FORMULA.search(text) and not (concept and not explicit):
        return True
    if re.search(r'(?:d\s*/\s*dx|\\frac\s*\{d\}\s*\{dx\})\s*[^。?？]*[a-z0-9]', text):
        return not concept or explicit
    if (re.search(_MATH, text) and explicit):
        return True
    if re.search(r'(?:求导|求解微分方程|证明定理|解微分方程)', text):
        return not concept and not re.search(r'(?:学不会|不会学|好烦|好难|学不懂|听不懂)', text)
    if re.search(_CODE, text) and re.search(_CODE_ACTION, text):
        # "写代码好烦" describes an activity rather than asking for a service.
        emotional = re.search(r'(?:好烦|好累|好难|崩溃|难受|不想|学不会|学不懂)', text)
        requested = _CODE_REQUEST.search(text)
        command = re.search(r'^(?:请|麻烦)?\s*(?:写|编写|实现|调试|修复|修改|排查|检查|解决|用\s*(?:python|javascript|java|c\+\+)|debug|implement|write|fix)', text)
        return bool(requested or command) and (not emotional or bool(requested))
    return False


def _is_refusal(text):
    return bool(re.search(r'(?:不(?:太)?擅长|不太会解|不太在行|不在我擅长的范围|超出.{0,8}范围|不会.{0,8}(?:做|解|证明|写)|不能.{0,8}(?:代做|解题|写程序))', text))


def _declined_context(history):
    declined = False
    pending = False
    for item in history:
        if not isinstance(item, dict) or not isinstance(item.get('content'), str):
            continue
        text = _normal(item['content'])
        if item.get('role') == 'user':
            pending = _direct_task(text) or (declined and bool(_CONTINUE.fullmatch(text)))
            declined = False
        elif item.get('role') == 'assistant':
            declined = pending and _is_refusal(text)
            pending = False
    return declined


def request_refusal(user: str, history=()) -> str | None:
    text = _normal(user)
    direct = _direct_task(text)
    if direct or (_CONTINUE.fullmatch(text) and _declined_context(history)):
        if not direct:
            for item in reversed(history):
                if isinstance(item, dict) and item.get('role') == 'user' and isinstance(item.get('content'), str):
                    previous = _normal(item['content'])
                    if _direct_task(previous):
                        text = previous
                        break
        return _CODE_REFUSAL if re.search(_CODE, text) and not _FORMULA.search(text) else _MATH_REFUSAL
    return None


def response_refusal(text: str) -> str | None:
    value = _normal(text)
    if re.search(r'```\s*(?:python|py|javascript|js|typescript|ts|java|c\+\+|cpp|csharp|c#|sql|rust|go|bash|sh|powershell|html|css|ruby|php)\b', value):
        return _CODE_REFUSAL
    if re.search(r'\b(?:def\s+\w+\s*\(|function\s+\w*\s*\(|class\s+\w+\s*[:{(]|console\.log\s*\()', value):
        return _CODE_REFUSAL
    if _FORMULA.search(value) and re.search(r'(?:[a-z0-9][_^({]|[a-z]\s*(?:exp|sin|cos|dx|d\s*x)|[=^]|\\(?:frac|mathrm|left))', value):
        return _MATH_REFUSAL
    if re.search(r'(?:换元|令|设)\s*\$?\s*[uvt]\s*=', value):
        return _MATH_REFUSAL
    if re.search(r'(?:求导得|积分得|解得|因此|所以)[^。\n]{0,30}(?:[a-z]\s*[\x27′]\s*=|\\frac|=\s*[^。\n]*\^)', value):
        return _MATH_REFUSAL
    return None


def companion_history(history) -> list[dict]:
    kept = []
    pending = None
    prior = []
    for item in history:
        if not isinstance(item, dict) or not isinstance(item.get('content'), str):
            continue
        role = item.get('role')
        if role == 'user':
            pending = dict(role='user', content=item['content'])
        elif role == 'assistant' and pending is not None:
            reply = dict(role='assistant', content=item['content'])
            if request_refusal(pending['content'], prior) is None and response_refusal(reply['content']) is None:
                kept.extend((pending, reply))
            prior.extend((pending, reply))
            pending = None
    return kept
