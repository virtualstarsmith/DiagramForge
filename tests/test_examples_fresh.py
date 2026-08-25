"""Example freshness gate.

Every bundled example spec is a published promise. This suite runs all of them
through validation (always) and a real browser render (when Chromium is
available), so a renderer or schema change that breaks an example fails here
instead of shipping silently.

No golden images: validity + structural checks only.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "assets" / "examples"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def example_specs():
    for path in sorted(EXAMPLES.glob("*.json")):
        yield path, json.loads(path.read_text(encoding="utf-8"))


class ExampleValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = load_module("render_animated_diagram")
        cls.spec_graph = load_module("spec_graph")

    def test_every_example_validates_clean(self):
        problems = []
        for path, spec in example_specs():
            result = self.renderer.validate_spec(spec, spec_dir=path.parent)
            if not result["ok"]:
                problems.append(f"{path.name}: {[e['message'] for e in result['errors']]}")
        self.assertEqual([], problems)

    def test_graph_and_swimlane_examples_pass_structural_lint(self):
        problems = []
        for path, spec in example_specs():
            if spec.get("layout") not in ("graph", "swimlane"):
                continue
            report = self.spec_graph.lint(spec)
            errors = [i for i in report["issues"] if i["severity"] == "error"]
            if errors:
                problems.append(f"{path.name}: {[i['message'] for i in errors]}")
        self.assertEqual([], problems)


class ExampleRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svg_renderer = load_module("svg_renderer")
        if not cls.svg_renderer.is_available():
            raise unittest.SkipTest("browser renderer unavailable; needs Chromium")
        cls.renderer = load_module("render_animated_diagram")

    def test_every_example_renders_a_clean_png(self):
        from PIL import Image

        problems = []
        with tempfile.TemporaryDirectory(dir=ROOT / "out") as tmp:
            for path, spec in example_specs():
                try:
                    result = self.renderer.write_outputs_browser(
                        spec, Path(tmp), path.stem, formats=("png",)
                    )
                    png = Path(result["png"])
                    if not png.is_file() or png.stat().st_size < 3000:
                        problems.append(f"{path.name}: png missing or too small")
                        continue
                    with Image.open(png) as im:
                        w, h = im.size
                    canvas = result["canvas"]
                    if (w, h) != (canvas["width"], canvas["height"]):
                        problems.append(
                            f"{path.name}: png {w}x{h} != canvas {canvas['width']}x{canvas['height']}"
                        )
                except Exception as exc:
                    problems.append(f"{path.name}: {type(exc).__name__}: {str(exc)[:200]}")
        self.assertEqual([], problems)


if __name__ == "__main__":
    unittest.main()
