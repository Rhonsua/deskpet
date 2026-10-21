"""White surfaces and black text, independent of the Windows colour scheme."""
from PySide6.QtGui import QColor, QPalette


CONTROL_STYLE = """
QComboBox { color: #000000; background: #FFFFFF; selection-color: #000000; selection-background-color: #FFFFFF; }
QComboBox:disabled { color: #000000; background: #FFFFFF; }
QComboBox QAbstractItemView {
    color: #000000; background: #FFFFFF; alternate-background-color: #FFFFFF;
    selection-color: #000000; selection-background-color: #FFFFFF;
    border: 1px solid #91AAB7; outline: none; padding: 3px;
}
QComboBox QAbstractItemView::item { min-height: 26px; padding: 3px 8px; }
QComboBox QAbstractItemView::item:selected { color: #000000; background: #FFFFFF; border: 1px solid #000000; }
QMenu { color: #000000; background: #FFFFFF; border: 1px solid #91AAB7; padding: 4px; }
QMenu::item { padding: 7px 20px; background: transparent; }
QMenu::item:selected { color: #000000; background: #FFFFFF; border: 1px solid #000000; }
QMenu::item:disabled { color: #000000; background: #FFFFFF; }
QMenu::separator { height: 1px; background: #D5E0E6; margin: 4px; }
QLineEdit { color: #000000; background: #FFFFFF; selection-color: #000000; selection-background-color: #E0E0E0; }
QToolTip { color: #000000; background: #FFFFFF; border: 1px solid #91AAB7; }
"""


def apply_light_palette(widget):
    palette = widget.palette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base,
                     QPalette.ColorRole.AlternateBase, QPalette.ColorRole.Button,
                     QPalette.ColorRole.ToolTipBase, QPalette.ColorRole.Highlight):
            palette.setColor(group, role, QColor('#FFFFFF'))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                     QPalette.ColorRole.ButtonText, QPalette.ColorRole.ToolTipText,
                     QPalette.ColorRole.HighlightedText, QPalette.ColorRole.PlaceholderText):
            palette.setColor(group, role, QColor('#000000'))
    widget.setPalette(palette)


def style_combo(combo):
    # A dedicated list view avoids the native menu delegate's system-theme colours.
    from PySide6.QtWidgets import QListView
    view = QListView(combo)
    apply_light_palette(combo)
    apply_light_palette(view)
    view.setStyleSheet(CONTROL_STYLE)
    combo.setView(view)

