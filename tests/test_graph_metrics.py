import tempfile
import unittest
from pathlib import Path

from analysis import GraphAnalyzer
from framework_helpers.fastapi.models import GraphEdge, GraphNode


class TestGraphAnalyzer(unittest.TestCase):
    def test_centrality_and_hop_costs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.py"
            source.write_text(
                "def first():\n    return 1\n\ndef second():\n    return first()\n\ndef third():\n    return second()\n",
                encoding="utf-8",
            )
            nodes = [
                GraphNode(
                    id=node_id,
                    label=node_id,
                    group="symbol",
                    category="symbol",
                    metadata={"file_path": str(source), "line_number": line},
                )
                for node_id, line in (("first", 1), ("second", 4), ("third", 7))
            ]
            edges = [
                GraphEdge(from_id="first", to_id="second", relation="CALLS"),
                GraphEdge(from_id="second", to_id="third", relation="CALLS"),
            ]

            report = GraphAnalyzer().analyze(nodes, edges, directory)
            metrics = report["node_metrics"]

            self.assertGreater(metrics["third"]["pagerank"], metrics["second"]["pagerank"])
            self.assertGreater(metrics["second"]["betweenness_centrality"], 0)
            self.assertEqual(metrics["first"]["hop_2_node_count"], 2)
            self.assertEqual(metrics["first"]["hop_3_node_count"], 2)
            self.assertGreater(metrics["first"]["token_cost"], 0)
            self.assertEqual(nodes[0].metadata["analysis"], metrics["first"])

    def test_empty_graph(self):
        report = GraphAnalyzer().analyze([], [])

        self.assertEqual(report["node_metrics"], {})
        self.assertEqual(report["total_token_cost"], 0)


if __name__ == "__main__":
    unittest.main()
