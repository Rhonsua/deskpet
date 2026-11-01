import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import QRect
from PySide6.QtTest import QTest
from deskpet.pet.behavior import PetBehavior
from deskpet.chat.movement import move_vertical,stop_move
from deskpet.chat.actions import recognize_action

class MovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_direct_variants_not_negations_or_quotes(self):
        for text,action in [('向上挪一点','move_up'),('往下移动一点','move_down'),('再往左走一点','walk_left'),('右动一点','walk_right'),
                            ('往上','teleport_up'),('往下','teleport_down'),
                            ('向上','teleport_up'),('向下','teleport_down'),
                            ('再往上','teleport_up'),('请往下吧','teleport_down'),
                            ('天依，往上','teleport_up'),('往上瞬移','teleport_up'),
                            ('下瞬移','teleport_down'),('瞬移到上面','teleport_up')]:
            self.assertEqual(recognize_action(text),action)
        for text in ['不要向上挪一点','他说往下移动一点','“右动一点”',
                     '不要往上','别往下','他说往上','“往下”','往上是什么意思',
                     '如果我说往上你会怎么样','上','下']:
            self.assertIsNone(recognize_action(text))
    def test_vertical_moves_finishes_clamps_and_can_interrupt(self):
        p=QWidget();p.resize(100,100);p.move(100,100)
        p.behavior=PetBehavior();p.playing=False;p.dock_edge='';p.scale=1
        p.screen_bounds=lambda:QRect(0,0,400,400);p.save_position=lambda:None
        self.assertTrue(move_vertical(p,-1));QTest.qWait(750)
        self.assertEqual(p.y(),20);self.assertFalse(p.behavior.layers)
        self.assertTrue(move_vertical(p,-1));QTest.qWait(750)
        self.assertEqual(p.y(),0);self.assertFalse(move_vertical(p,-1))
        self.assertTrue(move_vertical(p,1));QTest.qWait(100);stop_move(p)
        y=p.y();QTest.qWait(700);self.assertEqual(p.y(),y)
        self.assertFalse(p.behavior.layers);p.close()
