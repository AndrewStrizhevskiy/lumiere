# SPDX-License-Identifier: GPL-3.0-or-later
"""Design tokens + Qt stylesheet. One place for colours, type scale, spacing and motion so every screen stays consistent."""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QPalette

# ---- colour tokens. Two complete, semantic sets (dark = "private screening room", light = "ivory paper"); `apply()` picks one at start-up and
# copies it into this module's globals, so every screen keeps reading T.BG, T.TEXT, ... Contrast of every pair that matters is asserted in tests/test_theme.py.
#
# Brand colours (kept verbatim): charcoal #22211F, ivory #F1EDE4, burgundy #854B49, olive grey #85836F, soft white #EAE7E0, warm grey #AAA59F.
# Burgundy on charcoal is only 2.4:1, so it is a FILL (ACCENT_FILL, under ON_ACCENT text, 6:1) and never text/focus/progress on the dark theme;
# for those roles the dark theme derives ACCENT (a burgundy tint, 6.8:1). Warm grey on ivory is only 2.1:1, so the light theme derives darker secondary text.
THEMES = {
    "dark": dict(
        BG="#22211F", SURFACE="#2A2927", ELEVATED="#32302D", CANVAS="#0C0C0B",
        OUTLINE="#4A4742", OUTLINE_STRONG="#8C8780", EDGE="#55514B", HAIRLINE="#35332F", HOVER="#3A3835", PRESSED="#43403C",
        TEXT="#EAE7E0", TEXT2="#AAA59F", TEXT3="#9C978F",
        ACCENT="#D49A96", ACCENT_FILL="#854B49", ACCENT_HOVER="#9A5A57", ACCENT_PRESSED="#6F3F3D", ON_ACCENT="#F5F2EC", FOCUS="#E3B9B5", FOCUS_INNER="#F5F2EC",
        SECONDARY="#85836F", SUCCESS="#8DB596", WARNING="#D1AA63", DANGER="#E7786A", TRACK="#46433E", AVAILABLE="#85836F", PLAYED="#EAE7E0"),
    "light": dict(
        BG="#F1EDE4", SURFACE="#F8F5EE", ELEVATED="#FFFFFF", CANVAS="#0C0C0B",
        OUTLINE="#CFC8B9", OUTLINE_STRONG="#8A847A", EDGE="#B8AF9D", HAIRLINE="#D9D3C6", HOVER="#E8E3D8", PRESSED="#DDD6C8",
        TEXT="#22211F", TEXT2="#59554F", TEXT3="#6B665F",
        ACCENT="#854B49", ACCENT_FILL="#854B49", ACCENT_HOVER="#733F3D", ACCENT_PRESSED="#613331", ON_ACCENT="#FBF8F2", FOCUS="#22211F", FOCUS_INNER="#FBF8F2",
        SECONDARY="#6E6C58", SUCCESS="#3F7A52", WARNING="#8A6212", DANGER="#B13A2E", TRACK="#CFC8B9", AVAILABLE="#6E6C58", PLAYED="#22211F"),
}
THEME = "dark"
# placeholders so static analysers and early imports see the names; apply() below fills them
BG = SURFACE = ELEVATED = CANVAS = OUTLINE = OUTLINE_STRONG = EDGE = HAIRLINE = HOVER = PRESSED = ""
TEXT = TEXT2 = TEXT3 = ACCENT = ACCENT_FILL = ACCENT_HOVER = ACCENT_PRESSED = ON_ACCENT = FOCUS = FOCUS_INNER = ""
SECONDARY = SUCCESS = WARNING = DANGER = TRACK = AVAILABLE = PLAYED = ""


def apply(name: str | None = None) -> str:
    """Select the colour set. Order: explicit argument, LUMIERE_THEME (dark|light), default dark. Call once, before any widget is built:
    widgets read the tokens when they are constructed or painted, so there is no live switching (a Settings toggle is a proposal, see docs/design)."""
    import os
    global THEME
    name = (name or (os.environ.get("LUMIERE_THEME") or os.environ.get("KINO_STREAM_THEME")) or "dark").strip().lower()
    if name not in THEMES:
        name = "dark"
    THEME = name
    globals().update(THEMES[name])
    return name


def rgba(hex_: str, alpha: float) -> str:
    """'#RRGGBB' + 0..1 -> 'rgba(r,g,b,a)' for style sheets (overlays are derived from tokens, never hard-coded)."""
    h = hex_.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{round(alpha * 255)})"


# ---- spacing (4 px grid), radii, type scale (px)
S1, S2, S3, S4, S6, S8, S12 = 4, 8, 12, 16, 24, 32, 48
# Radii: a small system. Editorial surfaces (cards, drop zone) are nearly square; interactive controls are a little softer so they still read as pressable.
R_CARD, R_CTRL, R_PILL = 3, 5, 999
# Vertical rhythm by relationship, used the same way on Home, Continue Watching and Settings: between major blocks / between a heading and what it introduces / inside a group.
GAP_SECTION, GAP_GROUP, GAP_TIGHT = S8, S4, S2
FS_CAPTION, FS_SMALL, FS_BODY, FS_LEAD, FS_TITLE, FS_HERO, FS_SECTION = 12, 13, 14, 16, 22, 30, 20
FONT_FAMILIES = ["Inter", "Cantarell", "Noto Sans", "Ubuntu", "DejaVu Sans"]                   # interface: controls, menus, settings, technical text
# Editorial serif for the wordmark and a few headings only. None of these is bundled: the first installed one is used, so the look degrades gracefully to a
# generic serif on machines without them (see docs/design/LUMIERE_DESIGN.md for the bundling decision that is left to the maintainer).
SERIF_FAMILIES = ["Literata", "Source Serif 4", "EB Garamond", "Charis SIL", "Noto Serif", "Liberation Serif", "DejaVu Serif"]

# ---- motion (ms)
DUR_FAST, DUR_BASE, DUR_SLOW = 120, 200, 320


def serif_font(px: int = FS_TITLE, weight: int = 500) -> QFont:
    f = QFont()
    f.setFamilies(SERIF_FAMILIES)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(weight))
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def _serif_css() -> str:
    return ", ".join(f'"{f}"' for f in SERIF_FAMILIES) + ", serif"


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
                        (QPalette.ColorRole.Highlight, ACCENT_FILL), (QPalette.ColorRole.HighlightedText, ON_ACCENT),
                        (QPalette.ColorRole.PlaceholderText, TEXT3), (QPalette.ColorRole.Link, ACCENT)):
        p.setColor(role, QColor(color))
    return p


def qss(theme: str | None = None) -> str:
    """Application style sheet for the active theme, or for `theme` (the playback screen always renders with "dark": a viewing room is dark in either theme)."""
    if theme and theme != THEME:
        saved = THEME
        apply(theme)
        try:
            return _qss()
        finally:
            apply(saved)
    return _qss()


def _qss() -> str:
    serif = _serif_css()
    return f"""
* {{ outline: none; }}
QWidget {{ color: {TEXT}; font-size: {FS_BODY}px; }}
QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel[role="hero"] {{ font-family: {serif}; font-size: {FS_HERO + 10}px; font-weight: 500; }}
QLabel[role="title"] {{ font-family: {serif}; font-size: {FS_TITLE + 2}px; font-weight: 500; }}
QLabel[role="wordmark"] {{ font-family: {serif}; font-size: {FS_LEAD + 6}px; font-weight: 500; }}
QLabel[role="lead"] {{ font-size: {FS_LEAD}px; color: {TEXT2}; }}
QLabel[role="secondary"] {{ color: {TEXT2}; }}
QLabel[role="caption"] {{ color: {TEXT3}; font-size: {FS_CAPTION}px; }}
QLabel[role="sectionhead"] {{ font-family: {serif}; font-size: {FS_SECTION}px; font-weight: 500; }}
QLabel[role="emptyhint"] {{ font-family: {serif}; font-size: {FS_LEAD + 2}px; color: {TEXT2}; }}
QLabel[role="rowtitle"] {{ font-family: {serif}; font-size: {FS_LEAD + 2}px; font-weight: 500; }}
QLabel[role="section"] {{ color: {TEXT2}; font-size: {FS_SMALL}px; font-weight: 600; }}

QPushButton {{ background: {ELEVATED}; border: 1px solid {OUTLINE}; border-radius: {R_CTRL}px; padding: 8px 16px; min-height: 20px; }}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:pressed {{ background: {PRESSED}; }}
QPushButton:focus {{ border: 2px solid {FOCUS}; padding: 7px 15px; }}
QPushButton:disabled {{ color: {TEXT3}; background: {SURFACE}; border-color: {HAIRLINE}; }}
QPushButton[variant="primary"] {{ background: {ACCENT_FILL}; color: {ON_ACCENT}; border: 1px solid {ACCENT_FILL}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[variant="primary"]:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton[variant="primary"]:focus {{ border: 2px solid {FOCUS}; padding: 7px 15px; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[variant="ghost"]:hover {{ background: {HOVER}; }}
QPushButton[variant="ghost"]:focus {{ border: 2px solid {FOCUS}; }}
QPushButton[variant="danger"] {{ color: {DANGER}; }}
QPushButton[variant="icon"] {{ background: transparent; border: 1px solid transparent; padding: 6px; border-radius: {R_CTRL}px; min-height: 0; }}
QPushButton[variant="icon"]:hover {{ background: {HOVER}; }}
QPushButton[variant="icon"]:focus {{ border: 2px solid {FOCUS}; padding: 5px; }}
QPushButton[variant="segment"] {{ background: {ELEVATED}; border: 1px solid {OUTLINE_STRONG}; padding: 7px 14px; border-radius: {R_CTRL}px; }}
QPushButton[variant="segment"]:hover {{ background: {HOVER}; }}
QPushButton[variant="segment"]:checked {{ background: {ACCENT_FILL}; color: {ON_ACCENT}; border-color: {ACCENT_FILL}; font-weight: 600; }}
QPushButton[variant="segment"]:focus {{ border: 2px solid {FOCUS}; padding: 6px 13px; }}

QLineEdit {{ background: {SURFACE}; border: 1px solid {OUTLINE_STRONG}; border-radius: {R_CTRL}px; padding: 8px 12px; selection-background-color: {ACCENT_FILL}; selection-color: {ON_ACCENT}; }}
QLineEdit:focus {{ border: 2px solid {FOCUS}; padding: 7px 11px; }}
QFrame[card="true"] {{ background: {SURFACE}; border-radius: {R_CARD}px; }}
QFrame[card="outlined"] {{ background: {SURFACE}; border: 1px solid {EDGE}; border-radius: {R_CARD}px; }}
QFrame[role="divider"] {{ background: {HAIRLINE}; max-height: 1px; min-height: 1px; border: none; }}

QSlider::groove:horizontal {{ height: 4px; background: {TRACK}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; border: 2px solid {BG}; }}
QSlider::handle:horizontal:focus {{ border: 2px solid {FOCUS}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {TRACK}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QMenuBar {{ background: {BG}; color: {TEXT2}; }}
QMenuBar::item:selected {{ background: {HOVER}; color: {TEXT}; }}
QMenu {{ background: {ELEVATED}; border: 1px solid {OUTLINE}; border-radius: {R_CTRL}px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: {max(R_CTRL - 1, 2)}px; }}
QMenu::item:selected {{ background: {ACCENT_FILL}; color: {ON_ACCENT}; }}
QToolTip {{ background: {ELEVATED}; color: {TEXT}; border: 1px solid {OUTLINE_STRONG}; padding: 6px 8px; }}
QMessageBox {{ background: {SURFACE}; }}
"""


apply()          # default selection at import time (dark unless LUMIERE_THEME says otherwise); app start-up calls apply() again explicitly
