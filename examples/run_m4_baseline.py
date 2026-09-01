#!/usr/bin/env python3
"""
Runs the M4 benchmark baseline against the checked-in FastAPI samples using the
real agent traces in m4-public-traces.json, and prints the comparison summary.

Usage: python examples/run_m4_baseline.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.benchmark import evaluate_benchmark, load_agent_traces, load_benchmark_definition, summarize_benchmark
from analysis.task_exploration import SearchPolicy, TaskExplorer
from language_analyzers.python.graph import PythonGraphAnalyzer

EXAMPLES = Path(__file__).resolve().parent

REPOSITORIES = {
    ("https://github.com/nsidnev/fastapi-realworld-example-app", "029eb7781c60d5f563ee8990a0cbfb79b244538c"):
        EXAMPLES / "realworld_app",
    ("https://github.com/fastapi/full-stack-fastapi-template", "3000041090a94a2cbe1811ae5cbf97b6a8eb2094"):
        EXAMPLES / "official_template",
}


def main() -> None:
    definition = load_benchmark_definition(EXAMPLES / "m4-public-benchmarks.json")
    traces = load_agent_traces(EXAMPLES / "m4-public-traces.json")

    explorers = {}
    for key, project_path in REPOSITORIES.items():
        arch = PythonGraphAnalyzer(str(project_path)).analyze()
        explorers[key] = TaskExplorer(
            arch.nodes, arch.edges, project_path=arch.project_path,
            evaluation_relations=getattr(arch, "evaluation_relations", ()) or (),
        )

    results = evaluate_benchmark(definition, explorers, traces, tuple(SearchPolicy))
    for result in results:
        print(
            f"{result.task_id:28s} {result.policy.value:18s} "
            f"predicted_target={result.predicted_target_discovery_cost} "
            f"predicted_impact={result.predicted_impact_discovery_cost} "
            f"actual={result.trace_metrics.unique_open_token_cost if result.trace_metrics else None}"
        )

    summary = summarize_benchmark(results, k_values=(5, 10, 20))
    print(json.dumps(summary.to_dict(), indent=2))


if __name__ == "__main__":
    main()
