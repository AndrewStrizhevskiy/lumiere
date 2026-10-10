# SPDX-License-Identifier: GPL-3.0-or-later
"""Design system: both themes are complete, every text/control pair that matters meets WCAG contrast, the brand name is a display-only switch, and the
brand artwork renders at icon sizes. (Offscreen Qt; no engine involved.)"""
import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LC_NUMERIC", "C")
_xdg = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = _xdg
os.environ["XDG_STATE_HOME"] = _xdg

from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from kino_stream_ui import brand, theme as T  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# (foreground, background, minimum): 4.5 = normal text, 3.0 = large text and non-text UI parts (WCAG 2.1 AA)
TEXT_PAIRS = [("TEXT", "BG", 4.5), ("TEXT", "SURFACE", 4.5), ("TEXT", "ELEVATED", 4.5), ("TEXT", "HOVER", 4.5), ("TEXT2", "BG", 4.5), ("TEXT2", "SURFACE", 4.5),
              ("TEXT3", "BG", 4.5), ("TEXT3", "SURFACE", 4.5), ("ON_ACCENT", "ACCENT_FILL", 4.5), ("ON_ACCENT", "ACCENT_HOVER", 4.5), ("ON_ACCENT", "ACCENT_PRESSED", 4.5),
              ("ACCENT", "BG", 4.5), ("ACCENT", "SURFACE", 4.5), ("SUCCESS", "SURFACE", 4.5), ("WARNING", "SURFACE", 4.5), ("DANGER", "SURFACE", 4.5)]
UI_PAIRS = [("FOCUS", "BG", 3.0), ("FOCUS", "ELEVATED", 3.0), ("OUTLINE_STRONG", "BG", 3.0), ("OUTLINE_STRONG", "SURFACE", 3.0),
            ("OUTLINE_STRONG", "ELEVATED", 3.0), ("ACCENT", "TRACK", 3.0), ("AVAILABLE", "TRACK", 1.5)]


class Tokens(unittest.TestCase):
    def tearDown(self):
        T.apply("dark")

    def test_both_themes_define_exactly_the_same_tokens_as_valid_colours(self):
        self.assertEqual(set(T.THEMES["dark"]), set(T.THEMES["light"]))
        for name, tokens in T.THEMES.items():
            for k, v in tokens.items():
                self.assertRegex(v, r"^#[0-9A-Fa-f]{6}$", f"{name}.{k}")

    def test_text_contrast_meets_wcag_aa_in_both_themes(self):
        for name, t in T.THEMES.items():
            for fg, bg, need in TEXT_PAIRS:
                self.assertGreaterEqual(contrast(t[fg], t[bg]), need, f"{name}: {fg} on {bg} = {contrast(t[fg], t[bg]):.2f}")

    def test_control_boundaries_and_focus_meet_non_text_contrast(self):
        for name, t in T.THEMES.items():
            for fg, bg, need in UI_PAIRS:
                self.assertGreaterEqual(contrast(t[fg], t[bg]), need, f"{name}: {fg} on {bg} = {contrast(t[fg], t[bg]):.2f}")

    def test_focus_ring_against_the_primary_button_fill(self):
        # dark: 3:1 or better. light: a dark ring on a burgundy fill cannot reach 3:1 without leaving the brand colour; it is >= 2:1 here (2.37) and
        # 13:1+ against the page the ring is drawn on (documented limitation in docs/design/LUMIERE_DESIGN.md)
        self.assertGreaterEqual(contrast(T.THEMES["dark"]["FOCUS"], T.THEMES["dark"]["ACCENT_FILL"]), 3.0)
        self.assertGreaterEqual(contrast(T.THEMES["light"]["FOCUS"], T.THEMES["light"]["ACCENT_FILL"]), 2.0)

    def test_the_playback_canvas_is_neutral_and_dark_in_both_themes(self):
        for name, t in T.THEMES.items():
            r, g, b = (int(t["CANVAS"][i:i + 2], 16) for i in (1, 3, 5))
            self.assertLess(max(r, g, b), 24, name)                     # nearly black
            self.assertLessEqual(max(r, g, b) - min(r, g, b), 3, name)   # no colour cast on the film

    def test_brand_colours_are_kept_verbatim(self):
        d, l = T.THEMES["dark"], T.THEMES["light"]
        self.assertEqual((d["BG"], d["ACCENT_FILL"], d["TEXT"], d["TEXT2"], d["SECONDARY"]), ("#22211F", "#854B49", "#EAE7E0", "#AAA59F", "#85836F"))
        self.assertEqual((l["BG"], l["ACCENT_FILL"]), ("#F1EDE4", "#854B49"))

    def test_the_proposed_burgundy_alone_is_not_usable_as_text_on_charcoal(self):
        # documents why derived tokens exist: if this ever becomes true the derivation can be simplified
        self.assertLess(contrast("#854B49", "#22211F"), 3.0)

    def test_apply_switches_and_unknown_names_fall_back_to_dark(self):
        self.assertEqual(T.apply("light"), "light")
        self.assertEqual((T.THEME, T.BG, T.TEXT), ("light", "#F1EDE4", "#22211F"))
        self.assertEqual(T.apply("nonsense"), "dark")
        self.assertEqual(T.BG, "#22211F")

    def test_env_var_selects_theme_and_stylesheets_render_for_both(self):
        os.environ["KINO_STREAM_THEME"] = "light"
        try:
            self.assertEqual(T.apply(), "light")
        finally:
            os.environ.pop("KINO_STREAM_THEME")
        for name in ("dark", "light"):
            css = T.qss(name)
            self.assertIn(T.THEMES[name]["BG"], css)
            self.assertNotIn("{", re.sub(r"\{[^{}]*\}", "", css).replace("\n", ""), "unbalanced braces")
        self.assertEqual(T.THEME, "light" if False else T.THEME)       # qss(theme) must not leave another theme active
        T.apply("dark")
        T.qss("light")
        self.assertEqual(T.THEME, "dark")

    def test_overlays_are_derived_from_tokens(self):
        self.assertEqual(T.rgba("#0C0C0B", 1.0), "rgba(12,12,11,255)")
        self.assertEqual(T.rgba("#FFFFFF", 0.0), "rgba(255,255,255,0)")

    def test_no_stray_colour_literals_in_screens(self):
        for f in (ROOT / "kino_stream_ui").glob("*.py"):
            if f.name in ("theme.py",):
                continue
            hits = re.findall(r"#[0-9A-Fa-f]{6}\b|rgba?\(\s*\d", f.read_text())
            self.assertEqual(hits, [], f"{f.name}: colours belong in theme.py")


class Brand(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("KINO_STREAM_BRAND", None)

    def test_the_product_name_is_lumiere_and_the_old_name_is_one_switch_away(self):
        self.assertEqual(brand.product_name(), "Lumière")
        os.environ["KINO_STREAM_BRAND"] = "kino"
        self.assertEqual(brand.product_name(), "Kino Stream")
        os.environ["KINO_STREAM_BRAND"] = "lumiere"
        self.assertEqual(brand.product_name(), "Lumière")

    def test_tr_applies_the_display_name_but_no_technical_identifier_follows_it(self):
        from kino_stream_ui.messages import tr
        self.assertIn("Lumière", tr("Welcome to Kino Stream"))
        os.environ["KINO_STREAM_BRAND"] = "kino"
        self.assertIn("Kino Stream", tr("Welcome to Kino Stream"))                   # reversible display switch
        os.environ.pop("KINO_STREAM_BRAND")
        import kino_stream, kino_stream_ui
        self.assertEqual((kino_stream.__name__, kino_stream_ui.__name__), ("kino_stream", "kino_stream_ui"))
        from kino_stream.settings import config_dir, state_dir
        self.assertTrue(str(config_dir()).endswith("kino-stream") and str(state_dir()).endswith("kino-stream"))
        desktop = (ROOT / "packaging" / "kino-stream.desktop.in").read_text()
        self.assertIn("Name=Lumière", desktop)                           # display name only: the file name, Exec, Icon and StartupWMClass keep the technical id
        self.assertIn("Icon=kino-stream", desktop)
        self.assertIn("StartupWMClass=kino-stream", desktop)

    def test_symbol_renders_at_icon_sizes_and_in_one_colour(self):
        for size in (16, 24, 32, 64):
            img = brand.symbol_pixmap(size, "#EAE7E0", "#EAE7E0", dpr=1.0).toImage()
            opaque = sum(1 for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 128)
            self.assertGreater(opaque / (size * size), 0.18, f"{size}px: symbol too faint")
            self.assertLess(opaque / (size * size), 0.75, f"{size}px: symbol too heavy")

    def test_app_icon_is_text_free_so_it_survives_either_name(self):
        svg = (ROOT / "packaging" / "kino-stream.svg").read_text()
        self.assertNotIn("<text", svg)
        self.assertNotIn("Kino", svg.replace("<title>Frame symbol (concept)</title>", ""))


class SmallSizeLegibility(unittest.TestCase):
    """Measured on the shipped artwork at sizes desktops really use. Thresholds are the values measured after the 2026-10 geometry fix (heavier 2.6-unit
    stroke, larger panel, near full-bleed tile); the first version measured 0 solid frame pixels at 16 px and 8 lit-panel pixels."""

    @staticmethod
    def _lum(c):
        f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(c.red() / 255) + 0.7152 * f(c.green() / 255) + 0.0722 * f(c.blue() / 255)

    def _ratio(self, a, b):
        hi, lo = sorted((self._lum(a), self._lum(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    def render_icon(self, size):
        from PyQt6.QtCore import QByteArray, QRectF, Qt
        from PyQt6.QtGui import QImage, QPainter
        from PyQt6.QtSvg import QSvgRenderer
        im = QImage(size, size, QImage.Format.Format_ARGB32)
        im.fill(Qt.GlobalColor.transparent)
        q = QPainter(im)
        QSvgRenderer(QByteArray((ROOT / "packaging" / "kino-stream.svg").read_bytes())).render(q, QRectF(0, 0, size, size))
        q.end()
        return im

    def icon_metrics(self, size):
        im = self.render_icon(size)
        frame, lit = QColor("#EAE7E0"), QColor("#D49A96")
        solid = litpx = 0
        for x in range(size):
            for y in range(size):
                c = im.pixelColor(x, y)
                if c.alpha() < 250:
                    continue
                if self._ratio(c, frame) < 1.12:
                    solid += 1
                if max(abs(c.red() - lit.red()), abs(c.green() - lit.green()), abs(c.blue() - lit.blue())) < 26:
                    litpx += 1
        return solid, litpx

    def test_icon_keeps_a_solid_frame_and_a_visible_lit_panel_at_16_to_48_px(self):
        for size, min_frame, min_lit in ((16, 10, 10), (22, 40, 20), (24, 44, 28), (32, 110, 55), (48, 250, 130)):
            solid, litpx = self.icon_metrics(size)
            self.assertGreaterEqual(solid, min_frame, f"{size}px: only {solid} solid frame pixels")
            self.assertGreaterEqual(litpx, min_lit, f"{size}px: only {litpx} lit-panel pixels")



class Packaging(unittest.TestCase):
    def test_installer_ships_the_brand_module_and_the_new_icon(self):
        import shutil
        import subprocess
        home = Path(tempfile.mkdtemp(prefix="ks-theme-home-"))
        self.addCleanup(shutil.rmtree, home, True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_") and k != "KINO_STREAM_BIN"}
        env.update(HOME=str(home))
        r = subprocess.run([str(ROOT / "packaging" / "install.sh"), "--no-desktop-db"], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((home / ".local/share/kino-stream/app/kino_stream_ui/brand.py").exists())
        self.assertFalse((home / ".local/share/kino-stream/app/kino_stream_ui/assets").exists(), "no artwork is shipped")
        self.assertEqual((home / ".local/share/icons/hicolor/scalable/apps/kino-stream.svg").read_text(), (ROOT / "packaging" / "kino-stream.svg").read_text())
        subprocess.run([str(ROOT / "packaging" / "uninstall.sh"), "--no-desktop-db"], env=env, capture_output=True, timeout=120)


if __name__ == "__main__":
    unittest.main()
