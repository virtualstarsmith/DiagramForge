"""Tests for the headless-Chromium icon engine (scripts/icon_browser.py).

This module is the Pillow-pipeline glyph animator; the E2E matrix uses the
browser renderer (which skips Pillow glyphs), so icon_browser needs its own
coverage. Validates that real Tabler icons render into RGBA frame sequences
and that the engine degrades gracefully when the browser is unavailable.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IconBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ib = load_module("icon_browser")
        # Only a handful of Tabler icons ship; pick one we know exists.
        cls.tabler = ROOT / "assets" / "icons" / "tabler"
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
            with sync_playwright() as p:
                b = p.chromium.launch()
                b.close()
            cls.browser_ok = True
        except Exception:
            cls.browser_ok = False

    def _has_icon(self, name):
        return (self.tabler / f"{name}.svg").is_file()

    def test_render_glyph_frames_returns_frames_for_known_icon(self):
        if not self.browser_ok:
            self.skipTest("browser unavailable")
        # find any bundled tabler icon
        icons = sorted(self.tabler.glob("*.svg"))
        self.assertGreater(len(icons), 0, "no tabler icons bundled")
        name = icons[0].stem
        result = self.ib.render_glyph_frames(
            requests=[(name, "#86b300")],
            glyph_px=48,
            frames=4,
            base_color="#e2e8f0",
            render_px=64,
        )
        # success yields one entry whose value is a non-empty RGBA frame list
        self.assertEqual(len(result), 1, msg=f"no frames for {name}")
        frames = result[(name, "#86b300")]
        self.assertEqual(len(frames), 4)
        for fr in frames:
            self.assertEqual(fr.mode, "RGBA")
            self.assertEqual(fr.size, (48, 48))

    def test_unknown_icon_returns_empty(self):
        if not self.browser_ok:
            self.skipTest("browser unavailable")
        result = self.ib.render_glyph_frames(
            requests=[("this-icon-does-not-exist-xyz", "#fff")],
            glyph_px=24,
            frames=2,
            base_color="#000",
            render_px=32,
        )
        # missing icon -> engine falls back, returns empty mapping
        self.assertEqual(result, {})

    def test_read_markup_handles_missing_file(self):
        # _read_markup is the internal resolver; a missing file must not crash
        markup = self.ib._read_markup("definitely-missing-icon")
        self.assertIsNone(markup)


if __name__ == "__main__":
    unittest.main()
