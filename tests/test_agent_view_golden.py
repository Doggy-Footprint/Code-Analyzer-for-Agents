"""Byte-for-byte golden checks for the agent-view graph of the bundled example repositories.

These guard changes that must not alter the output, such as the occurrence index
implementation, and surface any that do as a readable agent-view diff.
"""

import gzip
import json
import unittest

from agent_view import diff_agent_view
from agent_view.occurrence import OccurrenceIndex
from agent_view_golden_cases import GOLDEN_CASES, build_json, read_manifest, index_inputs


def _summarize(before, after) -> str:
    result = diff_agent_view(before, after)
    sections = {key: value for key, value in result.items() if key not in ("schema_version", "profile")}
    return json.dumps(sections, indent=2, sort_keys=True, ensure_ascii=False)[:4000]


class AgentViewGoldenTests(unittest.TestCase):
    def test_golden_graphs_are_reproduced_byte_for_byte(self):
        for case in GOLDEN_CASES:
            with self.subTest(case=case.name):
                expected = gzip.decompress(case.golden_path.read_bytes()).decode("utf-8")
                actual = build_json(case, read_manifest(case))

                if actual != expected:
                    self.fail(
                        f"{case.name} agent-view output changed.\n"
                        f"Regenerate with scripts/regen_agent_view_golden.py once the change is intended.\n"
                        f"{_summarize(json.loads(expected), json.loads(actual))}"
                    )

    def test_no_framework_link_carries_an_absolute_evidence_path(self):
        for case in GOLDEN_CASES:
            with self.subTest(case=case.name):
                graph = json.loads(gzip.decompress(case.golden_path.read_bytes()).decode("utf-8"))
                links = graph["framework_links"]

                absolute = sorted({
                    link["evidence_file"] for link in links
                    if link["evidence_file"].startswith("/")
                })

                self.assertGreater(len(links), 0)
                self.assertEqual(absolute, [])

    def test_index_lookup_matches_the_reference_scan_for_every_query_term(self):
        for case in GOLDEN_CASES:
            with self.subTest(case=case.name):
                graph = json.loads(gzip.decompress(case.golden_path.read_bytes()).decode("utf-8"))
                terms = sorted({node["term"] for node in graph["query_nodes"]})
                contents, nodes_by_file = index_inputs(case, read_manifest(case))
                index = OccurrenceIndex(contents, nodes_by_file)

                divergent = [term for term in terms if index.find(term) != index._scan(term)]

                self.assertGreater(len(terms), 0)
                self.assertEqual(divergent, [])


if __name__ == "__main__":
    unittest.main()
