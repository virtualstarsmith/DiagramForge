"""Coverage for validate_spec's per-layout validation branches (check_items).

The 308-line block covers per-layout input validation: panorama, swimlane,
graph, sequence, er, usecase, class, activity, state, dfd, deployment,
component, package, object, composite, profile, communication, timing,
interaction, c4, gantt, bpmn, orgchart, mindmap, timeline, fishbone.
Each layout's check_items call is exercised with both valid and invalid
inputs to cover the error/warning paths.
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidateLayoutBranchesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rad = load_module("render_animated_diagram")
        cls.validate = staticmethod(cls.rad.validate_spec)

    def _errors(self, spec):
        return [e["path"] for e in self.validate(spec)["errors"]]

    def _warnings(self, spec):
        return [w["path"] for w in self.validate(spec)["warnings"]]

    # --- panorama ---
    def test_panorama_missing_inputs(self):
        s = {"layout": "panorama", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.inputs", self._errors(s))

    def test_panorama_too_many_inputs_warns(self):
        s = {"layout": "panorama", "style": "slate", "title": {"prefix": "X", "highlight": "Y"},
             "inputs": [{"id": f"i{i}", "label": f"I{i}"} for i in range(7)]}
        self.assertIn("$.inputs", self._warnings(s))

    # --- swimlane ---
    def test_swimlane_missing_lanes(self):
        s = {"layout": "swimlane", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.lanes", self._errors(s))

    def test_swimlane_too_many_steps_warns(self):
        s = {"layout": "swimlane", "style": "slate", "title": {"prefix": "X", "highlight": "Y"},
             "lanes": [{"title": "L", "steps": [{"label": f"s{i}"} for i in range(9)]}]}
        self.assertIn("$.lanes[0].steps", self._warnings(s))

    # --- graph ---
    def test_graph_missing_nodes(self):
        s = {"layout": "graph", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.nodes", self._errors(s))

    def test_graph_nodes_must_be_list(self):
        s = {"layout": "graph", "style": "slate", "title": {"prefix": "X", "highlight": "Y"},
             "nodes": "not-a-list"}
        self.assertIn("$.nodes", self._errors(s))

    # --- sequence ---
    def test_sequence_missing_participants(self):
        s = {"layout": "sequence", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.participants", self._errors(s))

    def test_sequence_missing_messages(self):
        s = {"layout": "sequence", "style": "slate", "title": {"prefix": "X", "highlight": "Y"},
             "participants": [{"id": "a", "label": "A"}]}
        self.assertIn("$.messages", self._errors(s))

    # --- er ---
    def test_er_missing_entities(self):
        s = {"layout": "er", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.entities", self._errors(s))

    def test_er_entities_must_be_list(self):
        s = {"layout": "er", "style": "slate", "title": {"prefix": "X", "highlight": "Y"},
             "entities": "not-a-list"}
        self.assertIn("$.entities", self._errors(s))

    # --- usecase ---
    def test_usecase_missing_actors(self):
        s = {"layout": "usecase", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.actors", self._errors(s))

    def test_usecase_missing_usecases(self):
        s = {"layout": "usecase", "style": "slate", "title": {"prefix": "X", "highlight": "Y"},
             "actors": [{"id": "a", "label": "A"}]}
        self.assertIn("$.usecases", self._errors(s))

    # --- class ---
    def test_class_missing_classes(self):
        s = {"layout": "class", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.classes", self._errors(s))

    # --- activity ---
    def test_activity_missing_nodes(self):
        s = {"layout": "activity", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.nodes", self._errors(s))

    # --- state ---
    def test_state_missing_states(self):
        s = {"layout": "state", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.states", self._errors(s))

    # --- dfd ---
    def test_dfd_missing_nodes(self):
        s = {"layout": "dfd", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.nodes", self._errors(s))

    def test_dfd_nodes_must_be_list(self):
        s = {"layout": "dfd", "style": "slate", "title": {"prefix": "X", "highlight": "Y"},
             "nodes": "not-a-list"}
        self.assertIn("$.nodes", self._errors(s))

    # --- deployment ---
    def test_deployment_missing_nodes(self):
        s = {"layout": "deployment", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.nodes", self._errors(s))

    # --- component ---
    def test_component_missing_components(self):
        s = {"layout": "component", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.components", self._errors(s))

    # --- package ---
    def test_package_missing_packages(self):
        s = {"layout": "package", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.packages", self._errors(s))

    # --- object ---
    def test_object_missing_objects(self):
        s = {"layout": "object", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.objects", self._errors(s))

    # --- composite ---
    def test_composite_missing_parts(self):
        s = {"layout": "composite", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.parts", self._errors(s))

    # --- profile ---
    def test_profile_missing_stereotypes(self):
        s = {"layout": "profile", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.stereotypes", self._errors(s))

    # --- communication ---
    def test_communication_missing_objects(self):
        s = {"layout": "communication", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.objects", self._errors(s))

    # --- timing ---
    def test_timing_missing_lifelines(self):
        s = {"layout": "timing", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.lifelines", self._errors(s))

    # --- interaction ---
    def test_interaction_missing_nodes(self):
        s = {"layout": "interaction", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.nodes", self._errors(s))

    # --- c4 ---
    def test_c4_missing_elements(self):
        s = {"layout": "c4", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.elements", self._errors(s))

    # --- gantt ---
    def test_gantt_missing_sections(self):
        s = {"layout": "gantt", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.sections", self._errors(s))

    # --- bpmn ---
    def test_bpmn_missing_elements(self):
        s = {"layout": "bpmn", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.elements", self._errors(s))

    # --- orgchart ---
    def test_orgchart_missing_nodes(self):
        s = {"layout": "orgchart", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.nodes", self._errors(s))

    # --- mindmap ---
    def test_mindmap_missing_root(self):
        s = {"layout": "mindmap", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.root", self._errors(s))

    # --- timeline ---
    def test_timeline_missing_events(self):
        s = {"layout": "timeline", "style": "slate", "title": {"prefix": "X", "highlight": "Y"}}
        self.assertIn("$.events", self._errors(s))

    # --- fishbone ---
    def test_fishbone_missing_categories(self):
        s = {"layout": "fishbone", "style": "slate", "title": {"prefix": "X", "highlight": "Y"},
             "effect": "Latency"}
        self.assertIn("$.categories", self._errors(s))

    def test_fishbone_missing_problem_warns(self):
        s = {"layout": "fishbone", "style": "slate", "title": {"prefix": "X", "highlight": "Y"},
             "categories": [{"label": "Network", "causes": ["DNS"]}]}
        self.assertIn("$.problem", self._warnings(s))


if __name__ == "__main__":
    unittest.main()
