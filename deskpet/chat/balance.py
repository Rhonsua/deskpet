"""Read-only DeepSeek balance badge; HTTP runs off the GUI thread."""
import json
import threading
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QPushButton

BALANCE_URL = 'https://api.deepseek.com/user/balance'


def supported(base_url):
    try:
        url=urlsplit(base_url.strip())
        return (url.scheme=='https' and url.hostname=='api.deepseek.com'
                and url.port in (None,443) and not url.username and not url.password
                and not url.query and not url.fragment)
    except ValueError:
        return False


def parse_balance(data):
    if not isinstance(data,dict) or type(data.get('is_available')) is not bool:
        raise ValueError('余额响应格式不正确')
    items=data.get('balance_infos')
    if not isinstance(items,list) or not 1<=len(items)<=2:
        raise ValueError('余额响应格式不正确')
    amounts=[];seen=set()
    try:
        for item in items:
            currency=item['currency']
            if currency not in ('CNY','USD') or currency in seen:raise ValueError()
            seen.add(currency)
            values=[]
            for key in ('total_balance','granted_balance','topped_up_balance'):
                raw=item[key]
                if not isinstance(raw,str) or len(raw)>40:raise ValueError()
                value=Decimal(raw)
                if not value.is_finite() or abs(value)>Decimal('1e12'):raise ValueError()
                values.append(value)
            amounts.append((currency,*values))
    except (ValueError,TypeError,KeyError,InvalidOperation):
        raise ValueError('余额响应格式不正确') from None
    return data['is_available'],amounts


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None  # Never forward the API key to another endpoint.


def fetch_balance(key):
    if not key or '\r' in key or '\n' in key:raise ValueError('请先保存有效的 API Key')
    request=Request(BALANCE_URL,headers={'Authorization':'Bearer '+key,'Accept':'application/json'})
    try:
        with build_opener(NoRedirect()).open(request,timeout=10) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('余额响应过大')
            return parse_balance(json.loads(raw))
    except HTTPError as error:
        message={401:'API Key 无效或已过期',403:'无权查询余额',429:'查询过于频繁，请稍后刷新'}.get(error.code,'余额服务暂不可用')
        raise ValueError(message) from None
    except (URLError,OSError,UnicodeError):
        raise ValueError('余额查询失败，请检查网络后刷新') from None
    except (ValueError,TypeError):
        raise ValueError('余额响应无效，请稍后刷新') from None


def money(value):
    text=format(value,'.4f')
    return text.rstrip('0').ljust(text.index('.')+3,'0')


class BalanceBadge(QPushButton):
    received=Signal(int,object,str)

    def __init__(self,config_provider,parent=None):
        super().__init__('余额：未配置',parent)
        self.config_provider=config_provider
        self.identity=None;self.generation=0;self.busy=False;self.closed=False
        self.last_attempt=0.;self.last_value=None;self.last_time=''
        self.setStyleSheet('QPushButton { padding: 3px 8px; border: none; color: #365F70; }')
        self.setToolTip('显示当前 DeepSeek API 账号总余额；点击刷新。')
        self.clicked.connect(lambda:self.refresh(force=True))
        self.received.connect(self.finish)
        self.poll=QTimer(self);self.poll.setInterval(60000)
        self.poll.timeout.connect(self.refresh);self.poll.start()
        self.deadline=QTimer(self);self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.timed_out)

    def showEvent(self,event):
        super().showEvent(event)
        QTimer.singleShot(0,self.refresh)

    def refresh(self,force=False):
        if self.closed:return
        config=self.config_provider()
        identity=(config.base_url,config.api_key)
        if identity!=self.identity:
            self.generation+=1;self.deadline.stop();self.busy=False
            self.identity=identity;self.last_attempt=0.;self.last_value=None;self.last_time=''
            self.setText('余额：待查询')
        if not config.base_url or not config.api_key:
            self.setText('余额：未配置');self.setToolTip('请先保存 API 地址和 Key。');return
        if not supported(config.base_url):
            self.setText('余额：暂不支持');self.setToolTip('目前支持 DeepSeek 官方账号余额；自定义或中转接口不自动查询。');return
        if not self.isVisible() or self.busy:return
        now=time.monotonic()
        if now-self.last_attempt < (5 if force else 15):return
        self.last_attempt=now;self.busy=True;self.generation+=1
        ticket=self.generation;key=config.api_key
        self.setText(self.last_value+' ↻' if self.last_value else '余额：查询中…')
        self.deadline.start(12000)
        def run():
            try:result,error=fetch_balance(key),''
            except Exception as exc:
                result=None
                error=str(exc) if isinstance(exc,ValueError) else '余额查询失败，请稍后刷新'
            try:self.received.emit(ticket,result,error)
            except RuntimeError:pass  # Window was destroyed while the request finished.
        threading.Thread(target=run,daemon=True).start()

    def timed_out(self):
        ticket=self.generation
        self.finish(ticket,None,'余额查询超时，点击重试')
        self.generation+=1

    def finish(self,ticket,result,error):
        if self.closed or ticket!=self.generation:return
        config=self.config_provider()
        if (config.base_url,config.api_key)!=self.identity:return
        self.deadline.stop();self.busy=False
        if error:
            self.setText(self.last_value+'（待更新）' if self.last_value else '余额：查询失败')
            self.setToolTip(error+('\n上次成功更新：'+self.last_time if self.last_value else '')+'\n点击刷新。')
            return
        available,amounts=result
        self.last_value='余额：'+' / '.join(('¥' if c=='CNY' else '$')+money(total) for c,total,_,_ in amounts)
        self.last_time=datetime.now().strftime('%H:%M:%S')
        self.setText(self.last_value)
        detail=['DeepSeek 账号总余额（含赠金和充值），不是本次对话消费。']
        detail += [f'{c}：总余额 {money(total)}；赠金 {money(granted)}；充值 {money(topped)}' for c,total,granted,topped in amounts]
        if not available:detail.append('当前账户无可用余额供 API 调用。')
        detail.append('更新于 '+self.last_time+'；页面显示时每分钟更新，也可点击刷新。')
        self.setToolTip('\n'.join(detail))

    def shutdown(self):
        self.closed=True;self.generation+=1;self.poll.stop();self.deadline.stop()
