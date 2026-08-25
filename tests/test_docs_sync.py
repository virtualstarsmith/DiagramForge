"""Docs synchronization gate.

The SKILL.md frontmatter description is the only text an agent sees *before*
deciding to load the skill: if a layout's trigger words are not in it, the
skill never fires for that request. This module keeps the routing surface,
the referenced files, and the example catalog in sync with the ground truth
(the layout enum in references/spec-format.md).

Rules enforced:

1. Every layout in the spec-format enum has both an English and a Chinese
   lexical hook in the SKILL.md description (see LAYOUT_TRIGGERS).
2. Major feature vocabulary is present (import formats, output formats).
3. Every repo path named in backticks in SKILL.md / references/*.md exists,
   and relative Markdown links in references/*.md resolve.
4. Every example spec's layout is in the enum, and every layout has at least
   one example.
5. SKILL.md stays under MAX_SKILL_BYTES measured on LF-normalized bytes —
   when it approaches the cap, cut body prose or move detail into
   references/, never the description (ADR-0004 discipline).
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
SPEC_FORMAT = ROOT / "references" / "spec-format.md"
EXAMPLES = ROOT / "assets" / "examples"

MAX_SKILL_BYTES = 40_000

# Authoritative routing contract: layout id -> (English hook, Chinese hook).
# Hooks are matched case-insensitively against the SKILL.md description.
# Adding a layout to the spec-format enum fails this suite until the map and
# the description are updated — routing surface is never traded away.
LAYOUT_TRIGGERS = {
    "panorama": ("panorama", "全景"),
    "swimlane": ("swimlane", "泳道图"),
    "graph": ("workflow", "动态流程图"),
    "grid": ("grid", "网格目录"),
    "sequence": ("sequence", "时序图"),
    "er": ("er", "er 图"),
    "usecase": ("use case", "用例图"),
    "class": ("class", "类图"),
    "activity": ("activity", "活动图"),
    "state": ("state", "状态机图"),
    "dfd": ("dfd", "数据流图"),
    "deployment": ("deployment", "部署图"),
    "component": ("component", "构件图"),
    "package": ("package", "包图"),
    "object": ("object", "对象图"),
    "composite": ("composite", "组合结构图"),
    "profile": ("profile", "profile 图"),
    "communication": ("communication", "通信图"),
    "timing": ("timing", "定时图"),
    "interaction": ("interaction", "交互概览图"),
    "c4": ("c4", "c4 图"),
    "gantt": ("gantt", "甘特图"),
    "bpmn": ("bpmn", "bpmn"),
    "orgchart": ("org chart", "组织架构图"),
    "mindmap": ("mindmap", "思维导图"),
    "timeline": ("timeline", "时间轴"),
    "fishbone": ("fishbone", "鱼骨图"),
}

FEATURE_HOOKS = ("mermaid", "excalidraw", "gif", "mp4", "interactive html", "sketch")

PATH_REF_RE = re.compile(r"`((?:assets|scripts|references|agents)/[^`\s]+?|requirements[\w.-]*\.txt)`")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def load_skill_text():
    return SKILL.read_text(encoding="utf-8")


def load_description():
    text = load_skill_text()
    match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    assert match, "SKILL.md frontmatter must contain a one-line description"
    return match.group(1)


def load_layout_enum():
    text = SPEC_FORMAT.read_text(encoding="utf-8")
    match = re.search(r'"layout":\s*"([^"]+)"', text, re.DOTALL)
    assert match, "spec-format.md must declare the layout enum"
    # The enum is a JSON string with escaped \n continuations.
    value = match.group(1).replace("\\n", " ").replace("\n", " ")
    return {part.strip() for part in value.split("|") if part.strip()}


class RoutingSurfaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.description = load_description().lower()
        cls.layouts = load_layout_enum()

    def test_trigger_map_covers_exactly_the_enum(self):
        self.assertEqual(
            set(LAYOUT_TRIGGERS),
            self.layouts,
            "LAYOUT_TRIGGERS and the spec-format enum drifted apart; update both",
        )

    def test_every_layout_has_en_and_zh_hooks(self):
        missing = []
        for layout, (en, zh) in sorted(LAYOUT_TRIGGERS.items()):
            if en.lower() not in self.description:
                missing.append(f"{layout}: EN hook {en!r}")
            if zh.lower() not in self.description:
                missing.append(f"{layout}: ZH hook {zh!r}")
        self.assertEqual([], missing, "description lost trigger words: " + "; ".join(missing))

    def test_feature_vocabulary_present(self):
        missing = [hook for hook in FEATURE_HOOKS if hook not in self.description]
        self.assertEqual([], missing, f"description lost feature vocabulary: {missing}")


class PathReferenceTest(unittest.TestCase):
    def _check_file(self, path):
        text = path.read_text(encoding="utf-8")
        problems = []
        for ref in sorted(set(PATH_REF_RE.findall(text))):
            if "<" in ref:
                continue  # template placeholder such as assets/icons/tabler/<name>.svg
            if not (ROOT / ref).exists():
                problems.append(f"{path.name}: `{ref}` does not exist")
        if path.parent.name == "references":
            for link in sorted(set(MD_LINK_RE.findall(text))):
                if link.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target = (path.parent / link.split("#")[0]).resolve()
                if not target.exists():
                    problems.append(f"{path.name}: link {link!r} does not resolve")
        return problems

    def test_skill_md_paths_exist(self):
        self.assertEqual([], self._check_file(SKILL))

    def test_reference_docs_paths_exist(self):
        problems = []
        for doc in sorted((ROOT / "references").glob("*.md")):
            problems.extend(self._check_file(doc))
        self.assertEqual([], problems)


class ExampleCatalogTest(unittest.TestCase):
    def test_every_example_layout_is_in_enum(self):
        layouts = load_layout_enum()
        problems = []
        for spec_path in sorted(EXAMPLES.glob("*.json")):
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            if spec.get("layout") not in layouts:
                problems.append(f"{spec_path.name}: unknown layout {spec.get('layout')!r}")
        self.assertEqual([], problems)

    def test_every_layout_has_an_example(self):
        layouts = load_layout_enum()
        covered = set()
        for spec_path in sorted(EXAMPLES.glob("*.json")):
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            covered.add(spec.get("layout"))
        self.assertEqual([], sorted(layouts - covered), "layouts without any example spec")


class SkillSizeTest(unittest.TestCase):
    def test_skill_md_under_byte_cap(self):
        raw = SKILL.read_bytes().replace(b"\r\n", b"\n")
        self.assertLess(
            len(raw),
            MAX_SKILL_BYTES,
            f"SKILL.md is {len(raw)} bytes (cap {MAX_SKILL_BYTES}); cut body prose or move "
            "detail into references/ — never shrink the frontmatter description",
        )


if __name__ == "__main__":
    unittest.main()
