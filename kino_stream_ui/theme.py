"""Design tokens + Qt stylesheet. One place for colours, type scale, spacing and motion so every screen stays consistent."""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QPalette

# ---- colour tokens (dark, cinema-friendly). Contrast on BG/SURFACE: TEXT 16:1, TEXT2 7.5:1, TEXT3 5.6:1, ACCENT 10.5:1
BG = "#0E0F12"
SURFACE = "#16181D"
ELEVATED = "#1D2026"
OUTLINE = "#343945"          # visible control outlines (3:1 against BG)
HAIRLINE = "#252932"         # decorative dividers only
TEXT = "#ECEEF2"
TEXT2 = "#A3A9B6"
TEXT3 = "#8A91A1"
ACCENT = "#F2B544"
ACCENT_HOVER = "#F7C566"
ACCENT_PRESSED = "#D99E31"
ON_ACCENT = "#1B1405"
SUCCESS = "#4CC9A6"
WARNING = "#F2B544"
DANGER = "#FF6B6B"
TRACK = "#3A3F4B"            # slider/progress track (visible against SURFACE)
AVAILABLE = "#7A8294"        # "already on disk" part of the seek bar

# ---- spacing (4 px grid), radii, type scale (px)
S1, S2, S3, S4, S6, S8, S12 = 4, 8, 12, 16, 24, 32, 48
R_CTRL, R_CARD, R_PILL = 8, 12, 999
FS_CAPTION, FS_SMALL, FS_BODY, FS_LEAD, FS_TITLE, FS_HERO = 12, 13, 14, 16, 22, 30
FONT_FAMILIES = ["Inter", "Cantarell", "Noto Sans", "Ubuntu", "DejaVu Sans"]

# ---- motion (ms)
DUR_FAST, DUR_BASE, DUR_SLOW = 120, 200, 320


def app_font() -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(FS_BODY)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def palette() -> QPalette:
    p = QPalette()
    for role, color in ((QPalette.ColorRole.Window, BG), (QPalette.ColorRole.Base, SURFACE), (QPalette.ColorRole.AlternateBase, ELEVATED),
                        (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.WindowText, TEXT), (QPalette.ColorRole.ButtonText, TEXT),
                        (QPalette.ColorRole.Button, ELEVATED), (QPalette.ColorRole.ToolTipBase, ELEVATED), (QPalette.ColorRole.ToolTipText, TEXT),
                        (QPalette.ColorRole.Highlight, ACCENT), (QPalette.ColorRole.HighlightedText, ON_ACCENT),
                        (QPalette.ColorRole.PlaceholderText, TEXT3), (QPalette.ColorRole.Link, ACCENT)):
        p.setColor(role, QColor(color))
    return p


def qss() -> str:
    return f"""
* {{ outline: none; }}
QWidget {{ color: {TEXT}; font-size: {FS_BODY}px; }}
QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: {FS_TITLE}px; font-weight: 600; }}
QLabel[role="hero"] {{ font-size: {FS_HERO}px; font-weight: 600; }}
QLabel[role="lead"] {{ font-size: {FS_LEAD}px; color: {TEXT2}; }}
QLabel[role="secondary"] {{ color: {TEXT2}; }}
QLabel[role="caption"] {{ color: {TEXT3}; font-size: {FS_CAPTION}px; }}
QLabel[role="section"] {{ color: {TEXT2}; font-size: {FS_SMALL}px; font-weight: 600; }}

QPushButton {{ background: {ELEVATED}; border: 1px solid {OUTLINE}; border-radius: {R_CTRL}px; padding: 8px 16px; min-height: 20px; }}
QPushButton:hover {{ background: #252A33; }}
QPushButton:pressed {{ background: #2C323D; }}
QPushButton:focus {{ border: 2px solid {ACCENT}; padding: 7px 15px; }}
QPushButton:disabled {{ color: {TEXT3}; background: {SURFACE}; border-color: {HAIRLINE}; }}
QPushButton[variant="primary"] {{ background: {ACCENT}; color: {ON_ACCENT}; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[variant="primary"]:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton[variant="primary"]:focus {{ border: 2px solid {TEXT}; padding: 7px 15px; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[variant="ghost"]:hover {{ background: {ELEVATED}; }}
QPushButton[variant="ghost"]:focus {{ border: 2px solid {ACCENT}; }}
QPushButton[variant="danger"] {{ color: {DANGER}; }}
QPushButton[variant="icon"] {{ background: transparent; border: 1px solid transparent; padding: 6px; border-radius: {R_CTRL}px; min-height: 0; }}
QPushButton[variant="icon"]:hover {{ background: {ELEVATED}; }}
QPushButton[variant="icon"]:focus {{ border: 2px solid {ACCENT}; padding: 5px; }}
QPushButton[variant="segment"] {{ background: {ELEVATED}; border: 1px solid {OUTLINE}; padding: 7px 14px; border-radius: {R_CTRL}px; }}
QPushButton[variant="segment"]:checked {{ background: {ACCENT}; color: {ON_ACCENT}; border-color: {ACCENT}; font-weight: 600; }}
QPushButton[variant="segment"]:focus {{ border: 2px solid {TEXT}; padding: 6px 13px; }}

QLineEdit {{ background: {BG}; border: 1px solid {OUTLINE}; border-radius: {R_CTRL}px; padding: 8px 12px; selection-background-color: {ACCENT}; selection-color: {ON_ACCENT}; }}
QLineEdit:focus {{ border: 2px solid {ACCENT}; padding: 7px 11px; }}
QFrame[card="true"] {{ background: {SURFACE}; border-radius: {R_CARD}px; }}
QFrame[card="outlined"] {{ background: {SURFACE}; border: 1px solid {HAIRLINE}; border-radius: {R_CARD}px; }}
QFrame[role="divider"] {{ background: {HAIRLINE}; max-height: 1px; min-height: 1px; border: none; }}

QSlider::groove:horizontal {{ height: 4px; background: {TRACK}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; border: 2px solid {BG}; }}
QSlider::handle:horizontal:focus {{ border: 2px solid {ACCENT}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {TRACK}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QMenuBar {{ background: {BG}; color: {TEXT2}; }}
QMenuBar::item:selected {{ background: {ELEVATED}; color: {TEXT}; }}
QMenu {{ background: {ELEVATED}; border: 1px solid {OUTLINE}; border-radius: {R_CTRL}px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT}; color: {ON_ACCENT}; }}
QToolTip {{ background: {ELEVATED}; color: {TEXT}; border: 1px solid {OUTLINE}; padding: 6px 8px; }}
QMessageBox {{ background: {SURFACE}; }}
"""
