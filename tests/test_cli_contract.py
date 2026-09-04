import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import analysis
from code_analyzer.cli import parse_args


class RemovedCliArgumentsTests(unittest.TestCase):
    def test_removed_arguments_are_rejected_by_argparse(self):
        removed_arguments = [
            ["--diagnostics"],
            ["--diagnostics-output", "diagnostics.json"],
            ["--graph-cost-config", "costs.json"],
        ]

        for arguments in removed_arguments:
            with self.subTest(arguments=arguments):
                stderr = io.StringIO()
                with patch.object(sys, "argv", ["code-analyzer", ".", *arguments]):
                    with contextlib.redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as raised:
                            parse_args()
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("unrecognized arguments", stderr.getvalue())
                self.assertIn(arguments[0], stderr.getvalue())


class RemovedDiagnosticsApiTests(unittest.TestCase):
    def test_analysis_only_exports_graph_metrics(self):
        self.assertEqual(analysis.__all__, ["GraphAnalyzer", "GraphAnalysisConfig"])

    def test_removed_analysis_apis_are_not_attributes(self):
        removed_names = [
            "DiagnosticKind",
            "DiagnosticsConfig",
            "DiagnosticsReport",
            "Finding",
            "FrictionDiagnoser",
            "ImprovementCandidate",
            "diagnostics_collection",
            "diagnostics_to_dict",
            "ExplorationCostAnalyzer",
            "TaskDefinition",
            "TaskDifficultyAnalyzer",
            "RepositoryCostDiff",
            "diff_repository_cost",
        ]

        for name in removed_names:
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    getattr(analysis, name)

    def test_removed_analysis_modules_and_git_diff_core_are_unavailable(self):
        removed_modules = [
            "analysis.friction_diagnostics",
            "analysis.exploration_cost",
            "analysis.task_difficulty",
            "analysis.cost_diff",
            "language_analyzers.core.git_diff_core",
        ]
        root = Path(__file__).resolve().parents[1]

        for module_name in removed_modules:
            with self.subTest(module_name=module_name):
                self.assertIsNone(importlib.util.find_spec(module_name))
                self.assertFalse((root / Path(*module_name.split("."))).with_suffix(".py").exists())


if __name__ == "__main__":
    unittest.main()
