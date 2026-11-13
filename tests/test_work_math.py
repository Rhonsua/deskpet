"""Exercise formula display in the same native text document the user reads."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage, QPixmap, QTextDocument
from PySide6.QtWidgets import QApplication

from deskpet.chat.conversation_view import ConversationView
from deskpet.chat.work_panel import WorkPanel


def image_names(document):
    names = []
    block = document.begin()
    while block.isValid():
        fragments = block.begin()
        while not fragments.atEnd():
            fmt = fragments.fragment().charFormat()
            if fmt.isImageFormat():
                names.append(fmt.toImageFormat().name())
            fragments += 1
        block = block.next()
    return names


class WorkMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def assert_formula_image(self, document, name):
        self.assertTrue(name.startswith("data:image/png;base64,"))
        resource = document.resource(QTextDocument.ImageResource, QUrl(name))
        image = resource.toImage() if isinstance(resource, QPixmap) else resource
        self.assertIsInstance(image, QImage)
        self.assertFalse(image.isNull())
        # A valid but fully transparent PNG would show the same blank formula.
        sample = image.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.assertTrue(any(sample.pixelColor(x, y).alpha() for y in range(sample.height())
                            for x in range(sample.width())))

    def test_probability_reply_renders_all_formulas_and_reopens_from_source(self):
        reply = r"""## 二、计数与概率估计

现在取 \(i\ge 0\)，得到区间 \[4i+1,4i+4m+2\]。

- 可行数为 $k^2+k+1$ 种。

\[
\sum_{i=0}^{k-2}(k-i-1)=\frac{k(k-1)}2
\]

$$
p\ge\frac{k^2+k+1}{\binom{4k+2}{2}}>\boxed{\frac18}
$$"""
        panel = WorkPanel(lambda: None)
        self.addCleanup(panel.deleteLater)
        self.addCleanup(panel.shutdown)
        panel.on_event({"type": "session.event", "event": {"type": "assistant/message",
                        "data": {"message": {"content": [{"type": "text", "text": reply}]}}}})
        saved = [dict(message) for message in panel.log.messages]
        self.assertEqual(saved[-1]["content"], reply)
        restored = ConversationView(assistant_markdown=True)
        self.addCleanup(restored.deleteLater)
        restored.set_messages(saved)
        for view in (panel.log, restored):
            with self.subTest(view=type(view).__name__):
                doc = view.document()
                self.assertEqual(doc.find("计数与概率估计").blockFormat().headingLevel(), 2)
                self.assertIsNotNone(doc.find("可行数为").currentList())
                names = image_names(doc)
                self.assertEqual(len(names), 5)
                self.assertEqual(len(set(names)), 5)
                for name in names:
                    self.assert_formula_image(doc, name)
                self.assertNotIn(r"\frac", doc.toPlainText())
                self.assertEqual(view.messages[-1]["content"], reply)

    def test_only_assistant_prose_is_typeset_and_code_keeps_its_delimiters(self):
        user = r"看看 \(x_0\) 和 $x^2$"
        inline_code = r"\(x^2\)"
        code = r"\[\boxed{\frac18}\]   $$x_1$$"
        reply = f"写法 `{inline_code}`，效果 $x^2$。\n\n```tex\n{code}\n```"
        view = ConversationView(assistant_markdown=True)
        self.addCleanup(view.deleteLater)
        view.append_message("user", user)
        view.append_message("assistant", reply)
        self.assertEqual(len(image_names(view.document())), 1)
        for literal in (user, inline_code, code):
            self.assertIn(literal, view.toPlainText())
        companion = ConversationView()
        self.addCleanup(companion.deleteLater)
        companion.append_message("assistant", user)
        self.assertIn(user, companion.toPlainText())
        self.assertEqual(image_names(companion.document()), [])

    def test_copying_equations_keeps_tex_in_plain_text(self):
        view = ConversationView(assistant_markdown=True)
        self.addCleanup(view.deleteLater)
        view.append_message("assistant", r"从 \(a_i\) 到 $\frac18$。")
        view.selectAll()
        copied = view.createMimeDataFromSelection().text()
        self.assertIn(r"从 \(a_i\) 到 \(\frac18\)。", copied)
