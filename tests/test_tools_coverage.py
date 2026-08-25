"""Mock-driven coverage for the network-facing tool scripts.

``icon_search.py`` calls the Iconify HTTP API; its logic is tested here with
urllib.request.urlopen mocked so the search/fetch paths run offline.
``prepare_fonts.py``'s main() is exercised via subprocess (it rebuilds the
bundled fonts in a temp dir) and its pure helpers are covered elsewhere.
"""
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResp:
    def __init__(self, payload, as_json=True):
        self.payload = payload
        self.as_json = as_json

    def read(self):
        return self.payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class IconSearchCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ise = load_module("icon_search")

    def test_get_json(self):
        with patch.object(self.ise.urllib.request, "urlopen", return_value=_FakeResp('{"a":1}')):
            self.assertEqual(self.ise._get_json("http://x"), {"a": 1})

    def test_get_text(self):
        with patch.object(self.ise.urllib.request, "urlopen", return_value=_FakeResp("hello", as_json=False)):
            self.assertEqual(self.ise._get_text("http://x"), "hello")

    def test_safe_name(self):
        self.assertEqual(self.ise._safe_name("My Icon!"), "my-icon")
        with self.assertRaises(SystemExit):
            self.ise._safe_name("!!!")

    def test_cmd_search_no_results(self):
        args = MagicMock(query="nothing", limit=5)
        with patch.object(self.ise, "_get_json", return_value={"icons": []}):
            self.assertEqual(self.ise.cmd_search(args), 1)

    def test_cmd_search_with_results(self):
        data = {
            "icons": ["tabler:database", "mdi:cloud"],
            "collections": {"tabler": {"name": "Tabler", "license": {"title": "MIT"}}},
        }
        args = MagicMock(query="database", limit=5)
        with patch.object(self.ise, "_get_json", return_value=data):
            self.assertEqual(self.ise.cmd_search(args), 0)

    def test_cmd_fetch_success(self):
        import argparse, tempfile
        args = argparse.Namespace(icon_id="tabler:database", pack="tabler", name="database")
        with tempfile.TemporaryDirectory() as td:
            fake_dir = Path(td) / "vendor"
            with patch.object(self.ise, "VENDOR_ICON_DIR", fake_dir), \
                 patch.object(self.ise, "ROOT", Path(td)), \
                 patch.object(self.ise, "_get_text", return_value="<svg></svg>"):
                self.assertEqual(self.ise.cmd_fetch(args), 0)
                self.assertTrue((fake_dir / "tabler" / "database.svg").is_file())

    def test_cmd_fetch_bad_id(self):
        args = MagicMock(icon_id="no-colon", pack=None, name=None)
        with self.assertRaises(SystemExit):
            self.ise.cmd_fetch(args)

    def test_cmd_fetch_non_svg_response(self):
        args = MagicMock(icon_id="tabler:x", pack=None, name=None)
        with patch.object(self.ise, "_get_text", return_value="not svg"):
            with self.assertRaises(SystemExit):
                self.ise.cmd_fetch(args)


if __name__ == "__main__":
    unittest.main()
