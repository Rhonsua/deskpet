import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch,Mock
from PySide6.QtWidgets import QApplication
from deskpet.chat.balance import BalanceBadge,parse_balance,supported,money,fetch_balance,NoRedirect,BALANCE_URL


def payload(total='12.3456',currency='CNY'):
    return {'is_available':True,'balance_infos':[{'currency':currency,'total_balance':total,
             'granted_balance':'2.00','topped_up_balance':'10.3456'}]}


class BalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_supported_host_and_strict_balance_format(self):
        for url in ('https://api.deepseek.com','https://api.deepseek.com/v1/chat/completions'):
            self.assertTrue(supported(url))
        for url in ('http://api.deepseek.com','https://api.deepseek.com.evil.test',
                    'https://key@api.deepseek.com','https://api.deepseek.com:444','https://proxy.test/v1'):
            self.assertFalse(supported(url))
        available,rows=parse_balance(payload())
        self.assertTrue(available);self.assertEqual(money(rows[0][1]),'12.3456')
        self.assertEqual(money(Decimal('0')),'0.00')
        for bad in (payload('NaN'),payload('Infinity'),payload('1e100'),payload(currency='BAD'),{},[] ):
            with self.assertRaises(ValueError):parse_balance(bad)

    def test_get_uses_only_official_endpoint_and_blocks_redirects(self):
        with patch('deskpet.chat.balance.build_opener') as opener:
            response=opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value=json.dumps(payload()).encode()
            fetch_balance('dummy-key')
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,BALANCE_URL)
            self.assertEqual(request.get_method(),'GET')
            self.assertEqual(request.get_header('Authorization'),'Bearer dummy-key')
            self.assertIsInstance(opener.call_args.args[0],NoRedirect)
            self.assertIsNone(NoRedirect().redirect_request(None,None,None,None,None,None))

    def test_badge_stale_results_refresh_throttle_and_provider_switch(self):
        config=NS(base_url='https://api.deepseek.com/v1',api_key='first')
        badge=BalanceBadge(lambda:config)
        jobs=[]
        def thread(**kwargs):
            return NS(start=lambda:jobs.append(kwargs['target']))
        with patch('deskpet.chat.balance.threading.Thread',side_effect=thread),patch('deskpet.chat.balance.fetch_balance',return_value=parse_balance(payload())):
            try:
                badge.show();self.app.processEvents()
                self.assertEqual(len(jobs),1)
                badge.refresh(force=True);self.assertEqual(len(jobs),1)
                jobs[0]();self.assertIn('¥12.3456',badge.text())
                badge.refresh(force=True);self.assertEqual(len(jobs),1)
                old=badge.generation
                config.api_key='second';badge.refresh(force=True)
                self.assertEqual(len(jobs),2);self.assertIsNone(badge.last_value)
                badge.finish(old,parse_balance(payload('99')),'')
                self.assertNotIn('99',badge.text())
                jobs[1]();self.assertIn('¥12.3456',badge.text())
                badge.finish(badge.generation,None,'Network error')
                self.assertIn('待更新',badge.text())
                config.base_url='https://custom.example/v1';badge.refresh(force=True)
                self.assertIn('暂不支持',badge.text());self.assertEqual(len(jobs),2)
                badge.shutdown();badge.finish(badge.generation,parse_balance(payload('88')),'')
                self.assertNotIn('88',badge.text())
            finally:badge.shutdown();badge.close();badge.deleteLater()

    def test_timeout_invalidates_late_result(self):
        config=NS(base_url='https://api.deepseek.com',api_key='key')
        badge=BalanceBadge(lambda:config)
        with patch('deskpet.chat.balance.threading.Thread'):
            try:
                badge.show();self.app.processEvents();ticket=badge.generation
                badge.timed_out();self.assertFalse(badge.busy)
                badge.finish(ticket,parse_balance(payload()),'')
                self.assertIn('查询失败',badge.text())
            finally:badge.shutdown();badge.close();badge.deleteLater()
