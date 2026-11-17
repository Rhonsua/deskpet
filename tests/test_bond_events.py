"""Invitations stay optional, varied and factual, with an in-memory save."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from deskpet.mods.bond.events import Events
from deskpet.mods.bond.store import BondStore


class InvitationTests(unittest.TestCase):
    def setUp(self):
        self.store=BondStore(':memory:')
        self.store.db.execute('UPDATE state SET affinity=40');self.store.refresh()
        self.snapshot=dict(busy=False,hunger=100,notes=0,state='idle')
        self.mod=SimpleNamespace(active=True,store=self.store,refresh=Mock(),activity_open=lambda:False,
            services=SimpleNamespace(snapshot=lambda:self.snapshot,library=lambda:[],act=Mock()),
            context=SimpleNamespace(notify=Mock(return_value=True)))
        self.events=Events(self.mod)
        self.now=datetime.now()

    def tearDown(self):self.store.close()

    def trigger(self,kind='headpat',clock=1000,now=None):
        self.events.last_check=0
        with patch('deskpet.mods.bond.events.time.monotonic',return_value=clock),\
             patch('deskpet.mods.bond.events.random.choice',side_effect=lambda choices:next(c for c in choices if c[0]==kind)):
            self.events.tick(now or self.now)

    def test_invitation_window_and_late_response(self):
        self.trigger()
        self.assertEqual(self.events.active['deadline'],1120)
        self.assertNotIn('秒',self.events.summary())
        with patch('deskpet.mods.bond.events.time.monotonic',return_value=1119):self.events.event('headpat',{})
        self.assertIn('need:headpat',{r['id'] for r in self.store.memories()})
        self.trigger('gaze',1200)
        with patch('deskpet.mods.bond.events.time.monotonic',return_value=1320):
            self.events.event('action',{'action':'mouse_wave'})
        self.assertIsNone(self.events.active)
        self.assertNotIn('need:gaze',{r['id'] for r in self.store.memories()})

    def test_quiet_waits_fifteen_seconds_and_busy_cancels(self):
        self.trigger('quiet')
        self.assertEqual(self.events.active['deadline'],1015)
        self.snapshot['busy']=True
        with patch('deskpet.mods.bond.events.time.monotonic',return_value=1005):self.events.tick(self.now)
        self.assertIsNone(self.events.active)
        self.assertNotIn('need:quiet',{r['id'] for r in self.store.memories()})

    def test_defer_survives_recreation_and_does_not_award(self):
        self.trigger()
        self.assertTrue(self.events.defer())
        before=self.store.value['affinity']
        self.assertEqual(self.store.db.execute('SELECT status FROM notices').fetchone()[0],'dismissed')
        resumed=Events(self.mod)
        self.assertTrue(resumed.paused(datetime.now()+timedelta(minutes=29)))
        self.assertFalse(resumed.paused(datetime.now()+timedelta(minutes=31)))
        self.assertNotIn('need:headpat',{r['id'] for r in self.store.memories()})
        self.assertEqual(self.store.value['affinity'],before)

    def test_today_quiet_crosses_midnight_and_malformed_preference(self):
        self.trigger()
        self.events.defer(today=True)
        self.assertTrue(Events(self.mod).paused(datetime.now()))
        self.assertFalse(self.events.paused(datetime.now()+timedelta(days=1)))
        self.store.configure('needs_paused_day','')
        self.store.configure('needs_snoozed_until','bad-date')
        self.assertFalse(self.events.paused(datetime.now()))

    def test_daily_variety_and_no_impossible_invitation(self):
        self.store.configure('needs_per_day',5)
        picked=[]
        for i in range(5):
            self.events.last_check=0
            with patch('deskpet.mods.bond.events.time.monotonic',return_value=1000+i*180),\
                 patch('deskpet.mods.bond.events.random.choice',side_effect=lambda choices:choices[0]):
                self.events.tick(self.now)
            if self.events.active:
                picked.append(self.events.active['kind']);self.events.end(False)
        self.assertEqual(set(picked),{'headpat','gaze','quiet'})
        self.assertEqual(len(picked),len(set(picked)))
        self.assertEqual(self.mod.context.notify.call_count,3)

    def test_busy_or_rejected_delivery_never_consumes_invitation(self):
        self.snapshot['busy']=True;self.trigger()
        self.assertIsNone(self.events.active)
        self.snapshot['busy']=False;self.mod.context.notify.return_value=False;self.trigger()
        self.assertIsNone(self.events.active)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM notices').fetchone()[0],0)


if __name__=='__main__':unittest.main()
