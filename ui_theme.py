"""Explicit popup colours, including when Windows uses a dark system theme."""
from PySide6.QtGui import QColor, QPalette


CONTROL_STYLE = """
QComboBox { color: #263E4D; background: #FFFFFF; selection-color: #FFFFFF; selection-background-color: #28647D; }
QComboBox:disabled { color: #647582; background: #EDF1F4; }
QComboBox QAbstractItemView {
    color: #263E4D; background: #FFFFFF; alternate-background-color: #F2F6F8;
    selection-color: #FFFFFF; selection-background-color: #28647D;
    border: 1px solid #91AAB7; outline: none; padding: 3px;
}
QComboBox QAbstractItemView::item { min-height: 26px; padding: 3px 8px; }
QComboBox QAbstractItemView::item:selected { color: #FFFFFF; background: #28647D; }
QMenu { color: #263E4D; background: #FFFFFF; border: 1px solid #91AAB7; padding: 4px; }
QMenu::item { padding: 7px 20px; background: transparent; }
QMenu::item:selected { color: #FFFFFF; background: #28647D; }
QMenu::item:disabled { color: #647582; background: #F2F5F7; }
QMenu::separator { height: 1px; background: #D5E0E6; margin: 4px; }
QLineEdit { color: #263E4D; background: #FFFFFF; selection-color: #FFFFFF; selection-background-color: #28647D; }
QToolTip { color: #263E4D; background: #FFFFFF; border: 1px solid #91AAB7; }
"""


def style_combo(combo):
    # A dedicated list view avoids the native menu delegate's system-theme colours.
    from PySide6.QtWidgets import QListView
    view = QListView(combo)
    palette = view.palette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        for role, value in ((QPalette.ColorRole.Base, '#FFFFFF'),
                            (QPalette.ColorRole.Text, '#263E4D'),
                            (QPalette.ColorRole.Highlight, '#28647D'),
                            (QPalette.ColorRole.HighlightedText, '#FFFFFF')):
            palette.setColor(group, role, QColor(value))
    view.setPalette(palette)
    view.setStyleSheet(CONTROL_STYLE)
    combo.setView(view)

