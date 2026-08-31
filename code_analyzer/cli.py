"""
Command-line interface for the FastAPI Visualizer.
"""

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

from analysis import GraphAnalyzer
from language_analyzers.core.serialization import architecture_to_dict

from framework_analyzers.android.analyzer import AndroidAnalyzer
from framework_analyzers.android.graph import AndroidArchitectureGraphBuilder
from framework_analyzers.fastapi.analyzer import FastAPIAnalyzer
from framework_analyzers.fastapi.dynamic_analyzer import DynamicFastAPIAnalyzer
from framework_analyzers.fastapi.graph import ArchitectureGraphBuilder
from language_analyzers.python.graph import PythonGraphAnalyzer
from language_analyzers.typescript import TypeScriptAnalyzer
from renderers.html import HTMLRenderer

FRAMEWORK_LABELS = {"fastapi": "FastAPI", "android": "Android"}
LANGUAGE_LABELS = {"python": "Python", "typescript": "TypeScript/JavaScript"}


def parse_args():
    parser = argparse.ArgumentParser(
        prog="code-analyzer",
        description="Statically analyze a project and generate an interactive HTML architecture & dependency dashboard.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "project_path",
        nargs="?",
        default=".",
        help="Path to the project directory.",
    )
    parser.add_argument(
        "-f",
        "--framework",
        choices=sorted(FRAMEWORK_LABELS),
        default="fastapi",
        help="Which framework adapter to analyze the project with.",
    )
    parser.add_argument(
        "-l",
        "--language",
        choices=sorted(LANGUAGE_LABELS),
        help="Analyze a language directly without framework semantics.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="architecture.html",
        help="Output path for the generated interactive HTML report.",
    )
    parser.add_argument(
        "-e",
        "--entrypoint",
        default=None,
        help="[fastapi only] Optional entrypoint Python file (e.g. main.py or app/main.py).",
    )
    parser.add_argument(
        "--app",
        default=None,
        help="[fastapi only] Optional dynamic app import string (e.g. 'app.main:app') for runtime introspection if installed.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Custom title for the dashboard.",
    )
    parser.add_argument(
        "--no-models",
        action="store_true",
        help="Exclude schema-shaped nodes from the graph (Pydantic/SQLModel schemas for fastapi, Room entities for android).",
    )
    parser.add_argument(
        "--no-deps",
        action="store_true",
        help="Exclude dependency-injection-shaped nodes from the graph (FastAPI dependencies for fastapi, Hilt/Dagger modules and bindings for android).",
    )
    parser.add_argument(
        "--no-language-graph",
        action="store_true",
        help="[fastapi only] Exclude the underlying language symbol graph (modules, classes, functions, "
             "imports and calls) and show framework components only.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Automatically open the generated HTML report in the default web browser.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also export architecture graph metadata as a JSON file.",
    )
    parser.add_argument(
        "--mermaid",
        action="store_true",
        help="Print Mermaid diagram markdown to stdout.",
    )
    args = parser.parse_args()
    if (args.language or args.framework != "fastapi") and (args.entrypoint or args.app):
        parser.error("--entrypoint and --app are only supported with --framework fastapi")
    return args


def main():
    args = parse_args()
    project_path = Path(args.project_path).resolve()

    if not project_path.exists():
        print(f"[!] Error: Project path does not exist: {project_path}")
        sys.exit(1)

    analyzer_label = LANGUAGE_LABELS.get(args.language) or FRAMEWORK_LABELS[args.framework]
    print(f"[*] Analyzing {analyzer_label} project at: {project_path}")

    builder = None
    if args.language == "python":
        arch = PythonGraphAnalyzer(project_path).analyze()
        arch.stats["analysis"] = GraphAnalyzer().analyze(
            arch.nodes, arch.edges, project_path=arch.project_path
        )
    elif args.language == "typescript":
        arch = TypeScriptAnalyzer(project_path).analyze()
        arch.stats["analysis"] = GraphAnalyzer().analyze(
            arch.nodes, arch.edges, project_path=arch.project_path
        )
    elif args.framework == "android":
        analyzer = AndroidAnalyzer(str(project_path), entrypoint=args.entrypoint)
        arch = analyzer.analyze()
        builder = AndroidArchitectureGraphBuilder(
            include_models=not args.no_models,
            include_dependencies=not args.no_deps,
        )
        arch = builder.build_graph(arch)
    else:
        if args.app:
            print(f"[*] Attempting dynamic introspection with app import: {args.app}...")
            dyn_analyzer = DynamicFastAPIAnalyzer(str(project_path), args.app)
            arch = dyn_analyzer.analyze()
            if not arch:
                print("[!] Dynamic introspection failed. Falling back to static AST analysis...")
                analyzer = FastAPIAnalyzer(str(project_path), entrypoint=args.entrypoint)
                arch = analyzer.analyze()
        else:
            analyzer = FastAPIAnalyzer(str(project_path), entrypoint=args.entrypoint)
            arch = analyzer.analyze()

        builder = ArchitectureGraphBuilder(
            include_models=not args.no_models,
            include_dependencies=not args.no_deps,
            include_language_graph=not args.no_language_graph,
        )
        arch = builder.build_graph(arch)

    renderer = HTMLRenderer(title=args.title, framework_label=analyzer_label)
    output_html_path = renderer.render(arch, args.output)
    print(f"[✓] Generated interactive HTML dashboard: {output_html_path}")

    if args.json:
        json_output_path = output_html_path.with_suffix(".json")
        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(architecture_to_dict(arch), f, indent=2, ensure_ascii=False, default=str)
        print(f"[✓] Exported architecture JSON: {json_output_path}")

    if args.mermaid:
        if builder is None:
            print("[!] Mermaid output is currently available for framework analyzers only.")
            return
        mermaid_code = builder.generate_mermaid(arch)
        print("\n--- Mermaid Architecture Diagram ---")
        print(mermaid_code)
        print("------------------------------------\n")

    stats = arch.stats
    print(f"\n📊 Summary Statistics:")
    if "total_apps" in stats:
        print(f"  • Applications: {stats.get('total_apps', 0)}")
    for collection in arch.report_collections:
        print(f"  • {collection.label:<14}{len(collection.rows)}")
    if stats.get("methods_breakdown"):
        print(f"  • Methods:      {stats['methods_breakdown']}")
    top_cost = stats.get("analysis", {}).get("top_weighted_cost", [])
    if top_cost:
        print(f"  • Highest agent context cost: {top_cost[0]['label']} ({top_cost[0]['value']:.4f})")
    if arch.git_diff and arch.git_diff.is_git_repo:
        gd = arch.git_diff
        print(f"  • Git Diff:     {gd.total_files} file(s) changed (+{gd.total_additions}, -{gd.total_deletions}) [{gd.mode_description}]")
        for key, items in (gd.impacted_by_collection or {}).items():
            if items:
                print(f"  • Impacted {key}: {len(items)}")

    if args.open:
        print(f"[*] Opening {output_html_path} in default browser...")
        webbrowser.open(f"file://{output_html_path}")


if __name__ == "__main__":
    main()
