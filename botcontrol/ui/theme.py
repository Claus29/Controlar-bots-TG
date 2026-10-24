"""Tema oscuro y utilidades visuales."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from botcontrol.paths import resource_path
from botcontrol.process_manager import State

ACCENT = "#2AABEE"  # azul Telegram

STATE_COLORS = {
    State.STOPPED: "#7a8494",
    State.WAITING: "#e0b341",
    State.RUNNING: "#3ecf6e",
    State.STOPPING: "#e0b341",
    State.CRASHED: "#ef8a3c",
    State.FAILED: "#ef4f4f",
}

QSS = f"""
QWidget {{ font-size: 10pt; }}
QMainWindow, QDialog {{ background: #17212b; }}
QToolBar {{ background: #1e2a36; border: none; padding: 6px; spacing: 6px; }}
QToolBar QToolButton {{ color: #e6edf3; padding: 6px 10px; border-radius: 6px; }}
QToolBar QToolButton:hover {{ background: #2b3a4a; }}
QToolBar QToolButton:pressed {{ background: {ACCENT}; }}
QTableView {{
    background: #1b2631; alternate-background-color: #1f2c38; color: #e6edf3;
    gridline-color: transparent; border: 1px solid #2b3a4a; border-radius: 8px;
    selection-background-color: #2b5278; selection-color: #ffffff;
}}
QHeaderView::section {{
    background: #1e2a36; color: #9fb0c2; padding: 6px; border: none;
    border-bottom: 1px solid #2b3a4a; font-weight: 600;
}}
QPlainTextEdit {{
    background: #0f171f; color: #d6e2ee; border: 1px solid #2b3a4a; border-radius: 8px;
    font-family: Consolas, "Cascadia Mono", monospace; font-size: 9pt;
}}
QLineEdit, QSpinBox, QComboBox, QTimeEdit, QTextEdit {{
    background: #0f171f; color: #e6edf3; border: 1px solid #2b3a4a; border-radius: 6px; padding: 4px 6px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QPushButton {{
    background: #2b3a4a; color: #e6edf3; border: none; border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover {{ background: #35485c; }}
QPushButton:default, QPushButton[accent="true"] {{ background: {ACCENT}; color: white; }}
QPushButton:disabled {{ color: #6b7785; background: #222e3a; }}
QTabWidget::pane {{ border: 1px solid #2b3a4a; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ background: #1e2a36; color: #9fb0c2; padding: 7px 14px; border-top-left-radius: 6px;
               border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: #2b3a4a; color: #ffffff; }}
QGroupBox {{ color: #9fb0c2; border: 1px solid #2b3a4a; border-radius: 8px; margin-top: 12px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QLabel[hint="true"] {{ color: #8796a8; font-size: 9pt; }}
QStatusBar {{ background: #1e2a36; color: #9fb0c2; }}
QMenu {{ background: #1e2a36; color: #e6edf3; border: 1px solid #2b3a4a; }}
QMenu::item:selected {{ background: #2b5278; }}
QSplitter::handle {{ background: #17212b; }}
QCheckBox {{ color: #e6edf3; }}
QToolTip {{ background: #1e2a36; color: #e6edf3; border: 1px solid #2b3a4a; }}
QCheckBox::indicator, QTableView::indicator {{
    width: 15px; height: 15px; border: 1px solid #5b6b7c; border-radius: 4px; background: #0f171f;
}}
QCheckBox::indicator:hover, QTableView::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked, QTableView::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; image: url("{{check}}");
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 18px; border: none; background: #2b3a4a;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: #35485c; }}
QAbstractSpinBox::up-arrow {{ image: url("{{up}}"); width: 9px; height: 9px; }}
QAbstractSpinBox::down-arrow {{ image: url("{{down}}"); width: 9px; height: 9px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{{down}}"); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{ background: #1e2a36; color: #e6edf3; selection-background-color: #2b5278; }}
QCheckBox::indicator:disabled {{ background: #222e3a; border-color: #3a4756; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.Window: "#17212b", QPalette.WindowText: "#e6edf3", QPalette.Base: "#0f171f",
        QPalette.AlternateBase: "#1f2c38", QPalette.Text: "#e6edf3", QPalette.Button: "#2b3a4a",
        QPalette.ButtonText: "#e6edf3", QPalette.Highlight: "#2b5278", QPalette.HighlightedText: "#ffffff",
        QPalette.ToolTipBase: "#1e2a36", QPalette.ToolTipText: "#e6edf3", QPalette.PlaceholderText: "#6b7785",
        QPalette.Link: ACCENT,
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#6b7785"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#6b7785"))
    app.setPalette(palette)
    qss = QSS
    for name in ("check", "up", "down"):
        qss = qss.replace("{%s}" % name, resource_path(f"assets/{name}.png").as_posix())
    app.setStyleSheet(qss)


@lru_cache(maxsize=None)
def dot_icon(color: str, size: int = 12) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pix)


def app_icon() -> QIcon:
    for name in ("assets/icon.ico", "assets/icon.png"):
        path = resource_path(name)
        if path.exists():
            return QIcon(str(path))
    return dot_icon(ACCENT, 64)


def tray_icon(active: int) -> QIcon:
    """Icono de la bandeja con un punto verde si hay bots en marcha."""
    base = app_icon().pixmap(64, 64)
    if active:
        painter = QPainter(base)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#3ecf6e"))
        painter.setPen(QColor("#17212b"))
        painter.drawEllipse(38, 38, 24, 24)
        painter.end()
    return QIcon(base)

