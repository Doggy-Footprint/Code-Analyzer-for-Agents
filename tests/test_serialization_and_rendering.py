import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from language_analyzers.core.graph_models import (
    Confidence,
    GraphEdge,
    GraphNode,
    NodeCost,
    Resolution,
    SourceSpan,
)
from language_analyzers.core.report_schema import ColumnSpec, ReportCollection
from language_analyzers.core.serialization import SCHEMA_VERSION, architecture_to_dict
from renderers.html import HTMLRenderer
from renderers.html.renderer import CONFIDENCE_STYLES


def sample_architecture():
    node = GraphNode(
        id="py:mod#run",
        label="run",
        group="function",
        category="function",
        kind="function",
        language="python",
        span=SourceSpan("mod.py", 3, 8),
        cost=NodeCost(token_estimate=42, char_count=168, line_count=6),
        signature="def run(value: int) -> int",
        docstring="Runs.",
        exported=True,
        symbol_path="mod.run",
        flags=["dynamic_attr"],
        provenance="python-core",
        metadata={"module": "mod"},
    )
    other = GraphNode(id="py:mod#helper", label="helper", group="function", category="function")
    edge = GraphEdge(
        from_id="py:mod#run",
        to_id="py:mod#helper",
        relation="CALLS",
        confidence=Confidence.STATIC_INFERRED,
        resolution=Resolution.AMBIGUOUS,
        evidence=SourceSpan("mod.py", 5, 5),
        candidates=["py:other#helper"],
        weight=3.0,
    )
    collection = ReportCollection(
        key="symbols",
        label="Symbols",
        columns=[ColumnSpec("symbol_path", "Symbol", "mono")],
        rows=[{"id": node.id, "symbol_path": "mod.run"}],
    )
    return SimpleNamespace(
        project_name="sample",
        project_path="/project",
        stats={"total_symbols": 2},
        nodes=[node, other],
        edges=[edge],
        report_collections=[collection],
    )


class TestSerialization(unittest.TestCase):
    def test_typed_node_fields_reach_the_neutral_schema(self):
        payload = architecture_to_dict(sample_architecture())
        node = payload["nodes"][0]

        self.assertEqual(SCHEMA_VERSION, "5")
        self.assertEqual(payload["schema_version"], "5")
        self.assertEqual(node["display_label"], "")
        self.assertNotIn("evaluation_relations", payload)
        self.assertEqual(node["span"], {
            "file_path": "mod.py", "start_line": 3, "end_line": 8, "start_col": 0, "end_col": 0,
        })
        self.assertEqual(node["cost"]["token_estimate"], 42)
        self.assertEqual(node["signature"], "def run(value: int) -> int")
        self.assertEqual(node["flags"], ["dynamic_attr"])
        self.assertEqual(node["provenance"], "python-core")
        self.assertTrue(node["exported"])

    def test_typed_edge_fields_reach_the_neutral_schema(self):
        edge = architecture_to_dict(sample_architecture())["edges"][0]

        self.assertEqual(edge["from_id"], "py:mod#run")
        self.assertEqual(edge["confidence"], "static_inferred")
        self.assertEqual(edge["resolution"], "ambiguous")
        self.assertEqual(edge["evidence"]["start_line"], 5)
        self.assertEqual(edge["candidates"], ["py:other#helper"])
        self.assertEqual(edge["weight"], 3.0)

    def test_confidence_is_serialized_as_a_plain_string(self):
        payload = json.loads(json.dumps(architecture_to_dict(sample_architecture()), default=str))

        self.assertIsInstance(payload["edges"][0]["confidence"], str)
        self.assertEqual(payload["edges"][0]["confidence"], "static_inferred")

    def test_nodes_without_the_new_fields_still_serialize(self):
        architecture = sample_architecture()
        architecture.nodes = [SimpleNamespace(id="a", label="A", category="thing", metadata={})]

        node = architecture_to_dict(architecture)["nodes"][0]

        self.assertIsNone(node["span"])
        self.assertIsNone(node["cost"])
        self.assertEqual(node["flags"], [])
        self.assertEqual(node["kind"], "thing")

    def test_legacy_evaluation_relations_are_not_serialized(self):
        architecture = sample_architecture()
        architecture.evaluation_relations = [{"cost": 4.0}]

        self.assertNotIn("evaluation_relations", architecture_to_dict(architecture))

    def test_mapping_edges_are_normalized_to_from_id_and_to_id(self):
        architecture = sample_architecture()
        architecture.edges = [{"from": "a", "to": "b", "relation": "CALLS"}]

        edge = architecture_to_dict(architecture)["edges"][0]

        self.assertEqual((edge["from_id"], edge["to_id"]), ("a", "b"))
        self.assertNotIn("from", edge)


class TestRendering(unittest.TestCase):
    def _payload(self, architecture):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.html"
            HTMLRenderer(title="Sample").render(architecture, str(report))
            document = report.read_text(encoding="utf-8")
        match = re.search(
            r'<script id="architecture-data" type="application/json">(.*?)</script>',
            document,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1).replace("\\u003c", "<")), document

    def test_dashboard_payload_carries_the_typed_node_fields(self):
        payload, _ = self._payload(sample_architecture())
        node = payload["nodes"][0]

        self.assertEqual(node["span"]["start_line"], 3)
        self.assertEqual(node["cost"]["token_estimate"], 42)
        self.assertEqual(node["flags"], ["dynamic_attr"])
        self.assertEqual(node["symbol_path"], "mod.run")

    def test_dashboard_edges_keep_both_the_vis_keys_and_the_typed_fields(self):
        payload, _ = self._payload(sample_architecture())
        edge = payload["edges"][0]

        self.assertEqual(edge["from"], "py:mod#run")
        self.assertEqual(edge["to"], "py:mod#helper")
        self.assertEqual(edge["confidence"], "static_inferred")
        self.assertEqual(edge["evidence"]["start_line"], 5)

    def test_confidence_drives_the_line_style(self):
        architecture = sample_architecture()
        architecture.edges = [
            GraphEdge("py:mod#run", "py:mod#helper", "CALLS", confidence=level)
            for level in ("static_certain", "static_inferred", "dynamic_required")
        ]

        payload, _ = self._payload(architecture)
        by_confidence = {edge["confidence"]: edge for edge in payload["edges"]}

        self.assertFalse(by_confidence["static_certain"]["dashes"])
        self.assertEqual(by_confidence["static_inferred"]["dashes"], CONFIDENCE_STYLES["static_inferred"]["dashes"])
        self.assertEqual(by_confidence["dynamic_required"]["dashes"], CONFIDENCE_STYLES["dynamic_required"]["dashes"])
        self.assertNotEqual(
            by_confidence["static_certain"]["color"]["color"],
            by_confidence["dynamic_required"]["color"]["color"],
        )

    def test_edge_tooltip_explains_confidence_and_evidence(self):
        payload, _ = self._payload(sample_architecture())

        title = payload["edges"][0]["title"]
        self.assertIn("confidence: static_inferred", title)
        self.assertIn("resolution: ambiguous", title)
        self.assertIn("evidence: mod.py:5", title)
        self.assertIn("other candidates: 1", title)
        self.assertIn("occurrences: 3", title)

    def test_an_explicit_edge_colour_is_not_overridden_by_confidence(self):
        architecture = sample_architecture()
        architecture.edges = [
            GraphEdge("py:mod#run", "py:mod#helper", "ROUTES", color="#10B981",
                      confidence=Confidence.FRAMEWORK_INFERRED)
        ]

        payload, _ = self._payload(architecture)

        self.assertEqual(payload["edges"][0]["color"]["color"], "#10B981")

    def test_the_style_table_is_shipped_to_the_dashboard(self):
        payload, _ = self._payload(sample_architecture())

        self.assertEqual(payload["confidence_styles"], CONFIDENCE_STYLES)

    def test_assets_stay_in_sibling_files(self):
        _, document = self._payload(sample_architecture())

        self.assertNotIn("<style", document)
        self.assertIn("report_assets/app.js", document)


if __name__ == "__main__":
    unittest.main()
