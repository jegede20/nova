"""Visual language: a restrained dark desktop theme.

Neutral greys, one accent, flat surfaces, hairline borders. No gradients,
no glow, no oversized rounded cards.
"""

from __future__ import annotations

# --- palette ---
BG = "#111214"
SURFACE = "#17181b"
SURFACE_2 = "#1d1f23"
BORDER = "#2a2d33"
BORDER_STRONG = "#383c44"
TEXT = "#e8e9ec"
TEXT_DIM = "#9aa0aa"
TEXT_FAINT = "#6b7280"
ACCENT = "#5b8def"
ACCENT_DIM = "#3f6ec4"

OK = "#3fb950"
WARN = "#d29922"
ERROR = "#f04747"
BUSY = "#5b8def"
IDLE = "#6b7280"

STATE_COLORS = {
    "idle": IDLE,
    "ready": OK,
    "listening": OK,
    "recording": OK,
    "wake": OK,
    "thinking": BUSY,
    "planning": BUSY,
    "executing": WARN,
    "waiting_confirmation": WARN,
    "waiting": WARN,
    "speaking": BUSY,
    "paused": TEXT_FAINT,
    "failed": ERROR,
    "error": ERROR,
    "completed": OK,
    "running": BUSY,
    "cancelled": TEXT_FAINT,
    "pending": TEXT_FAINT,
    "stopped": TEXT_FAINT,
    "unauthorized": ERROR,
}

FONT = "'Segoe UI Variable Text', 'Segoe UI', Inter, system-ui, sans-serif"
MONO = "'Cascadia Mono', Consolas, monospace"

STYLESHEET = f"""
* {{
    font-family: {FONT};
    color: {TEXT};
    outline: none;
}}
QWidget#Root, QMainWindow {{
    background: {BG};
}}
QWidget#Sidebar {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}
QLabel#Wordmark {{
    font-size: 17px;
    font-weight: 700;
    letter-spacing: 3px;
    color: {TEXT};
    padding: 2px 0;
}}
QLabel#Tagline {{
    font-size: 10px;
    color: {TEXT_FAINT};
    letter-spacing: 1px;
}}
QPushButton#NavItem {{
    background: transparent;
    border: none;
    border-left: 2px solid transparent;
    text-align: left;
    padding: 9px 14px;
    font-size: 13px;
    color: {TEXT_DIM};
    border-radius: 0;
}}
QPushButton#NavItem:hover {{
    background: {SURFACE_2};
    color: {TEXT};
}}
QPushButton#NavItem:checked {{
    background: {SURFACE_2};
    border-left: 2px solid {ACCENT};
    color: {TEXT};
    font-weight: 600;
}}
QLabel#PageTitle {{
    font-size: 19px;
    font-weight: 600;
}}
QLabel#PageHint {{
    font-size: 12px;
    color: {TEXT_DIM};
}}
QLabel#SectionLabel {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.3px;
    color: {TEXT_FAINT};
}}
QFrame#Card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QFrame#Divider {{
    background: {BORDER};
    max-height: 1px;
    border: none;
}}
QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 7px 14px;
    font-size: 12px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #24272c; border-color: #454a53; }}
QPushButton:pressed {{ background: #1a1c20; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; background: {SURFACE}; }}
QPushButton#Primary {{
    background: {ACCENT}; border: 1px solid {ACCENT}; color: #ffffff; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT_DIM}; border-color: {ACCENT_DIM}; }}
QPushButton#Danger {{ border-color: #5c2b2b; color: #ff8080; }}
QPushButton#Danger:hover {{ background: #2a1919; }}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDoubleSpinBox {{
    background: {BG};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 7px 10px;
    font-size: 13px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER_STRONG};
    selection-background-color: {ACCENT_DIM};
}}
QCheckBox {{ font-size: 12px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 3px;
    border: 1px solid {BORDER_STRONG}; background: {BG};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QAbstractScrollArea {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #32363d; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #434851; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; }}
QScrollBar::handle:horizontal {{ background: #32363d; border-radius: 4px; }}
QProgressBar {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 3px;
    height: 5px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
QTableWidget {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px;
    gridline-color: {BORDER}; font-size: 12px;
}}
QHeaderView::section {{
    background: {SURFACE_2}; border: none; border-bottom: 1px solid {BORDER};
    padding: 8px; font-size: 11px; font-weight: 600; color: {TEXT_DIM};
}}
QTableWidget::item {{ padding: 7px; border-bottom: 1px solid {BORDER}; }}
QTableWidget::item:selected {{ background: {SURFACE_2}; color: {TEXT}; }}
QMenu {{
    background: {SURFACE_2}; border: 1px solid {BORDER_STRONG};
    padding: 5px; border-radius: 5px;
}}
QMenu::item {{ padding: 7px 26px 7px 14px; font-size: 12px; border-radius: 3px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QToolTip {{
    background: {SURFACE_2}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; padding: 5px;
}}
QSlider::groove:horizontal {{ height: 3px; background: {BORDER_STRONG}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {ACCENT}; width: 13px; height: 13px;
    margin: -5px 0; border-radius: 7px;
}}
"""


def state_color(state: str) -> str:
    return STATE_COLORS.get(str(state).lower(), IDLE)


def rgba(hex_color: str, alpha: float) -> str:
    """'#5b8def', 0.12 -> 'rgba(91,141,239,0.12)'. Qt stylesheets don't accept #RRGGBBAA."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"
