import unittest
from types import SimpleNamespace as NS
from deskpet.chat.companion_runtime import CompanionRuntime
from deskpet.chat.store import ChatStore

class RuntimeTests(unittest.TestCase):
    def runtime(self):
        hidden=NS(isVisible=lambda:False)
        pet=NS(behavior=NS(mode='idle',layers=[]),dragging=False,press_point=None,
               petting=False,dock_edge='',panel=hidden,toolbar=hidden,bubble=hidden,
               playing=False,isVisible=lambda:True)
        window=NS(pending=None,testing=False,input=NS(toPlainText=lambda:''),
                  isVisible=lambda:False,companion_mode_enabled=True,work_panel=NS(is_running=False))
        # Exercise state without constructing a network worker or Qt window.
        runtime=NS(pet=pet,window=window,started=0)
        return runtime

    def test_runtime_admission(self):
        runtime=self.runtime()
        self.assertTrue(CompanionRuntime.state(runtime).allows(45))
        for field,value in [('press_point',object()),('petting',True),('dock_edge','left')]:
            setattr(runtime.pet,field,value)
            self.assertFalse(CompanionRuntime.state(runtime).allows(45))
            setattr(runtime.pet,field,None if field=='press_point' else False)
        runtime.window.work_panel.is_running=True
        self.assertFalse(CompanionRuntime.state(runtime).allows(45))
        runtime.window.work_panel.is_running=False
        runtime.window.companion_mode_enabled=False
        self.assertFalse(CompanionRuntime.state(runtime).allows(45))

    def test_proactive_memory_does_not_forge_user(self):
        store=ChatStore(':memory:')
        store.add_proactive('tianyi','一起安静待一会儿吧。')
        self.assertEqual(store.history('tianyi'),[])
        self.assertIn('一起安静',store.last_proactive('tianyi'))
        store.clear_history('tianyi')
        self.assertEqual(store.last_proactive('tianyi'),'')
        store.close()
