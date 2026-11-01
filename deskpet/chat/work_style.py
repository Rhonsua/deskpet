"""Native, translucent work-chat surfaces; the window owns the background."""

WORK_STYLE = '''
QWidget#workspaces, QWidget#workPanel { background: transparent; color: #243541; }
QFrame#workspaceSidebar { background: rgba(226,234,241,185); border: 1px solid rgba(162,181,194,85); border-radius: 12px; }
QFrame#workspaceMain { background: rgba(250,252,255,85); border: 1px solid rgba(162,181,194,75); border-radius: 12px; }
QLabel#workspaceTitle { background: transparent; font-size: 17px; font-weight: 600; padding: 0; }
QLabel#workspacePath, QLabel#workspaceNotice, QLabel#workHint { background: transparent; color: #637886; font-size: 11px; padding: 0; }
QLabel#sidebarTitle { background: transparent; font-size: 15px; font-weight: 600; padding: 4px; }
QTreeWidget#workspaceTree { background: transparent; border: none; outline: none; padding: 0; show-decoration-selected: 0; }
QTreeWidget#workspaceTree::item { color: #344C5C; min-height: 23px; padding: 5px 4px; border-radius: 7px; }
QTreeWidget#workspaceTree::item:hover { background: rgba(255,255,255,130); }
QTreeWidget#workspaceTree::item:selected { background: rgba(255,255,255,225); color: #15576C; }
QTreeWidget#workspaceTree::branch { background: transparent; }
QSplitter#workspaceSplitter::handle { background: transparent; width: 7px; }
QFrame#workComposer { background: rgba(255,255,255,225); border: 1px solid rgba(137,166,183,145); border-radius: 17px; }
QPlainTextEdit#workPrompt { background: transparent; border: none; border-radius: 0; padding: 2px; font-size: 13px; }
QPushButton#workSend { background: #276B80; color: #FFFFFF; border: none; border-radius: 9px; padding: 8px 18px; }
QPushButton#workSend:hover { background: #357F94; }
QPushButton#workSend:disabled { background: #A0B7C0; color: #F4F8FA; }
QPushButton#workStop { background: rgba(255,241,233,235); color: #8D4930; border: 1px solid #DAB7A7; border-radius: 9px; }
QFrame#workOptions, QFrame#workDetails { background: rgba(244,249,252,205); border: 1px solid rgba(158,183,196,120); border-radius: 9px; }
QFrame#workOptions QLabel, QLabel#workState { background: transparent; }
QFrame#workApproval { background: rgba(255,247,227,240); border: 1px solid #D9BE83; border-radius: 10px; }
QFrame#workApproval QLabel { background: transparent; color: #77562B; }
QPlainTextEdit#workEvents, QPlainTextEdit#workApprovalText { background: transparent; border: none; padding: 3px; }
QToolButton#workDetailsToggle, QToolButton#workOptionsToggle { background: transparent; border: none; padding: 4px 7px; }
QToolButton#workDetailsToggle:hover, QToolButton#workOptionsToggle:hover { background: rgba(215,233,243,185); }
'''
