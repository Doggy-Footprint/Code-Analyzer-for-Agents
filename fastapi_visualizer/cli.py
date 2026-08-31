"""
Command-line interface for the FastAPI Visualizer.
"""

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

from .analyzer import FastAPIAnalyzer
from .dynamic_analyzer import DynamicFastAPIAnalyzer
from .graph import ArchitectureGraphBuilder
from .renderer import HTMLRenderer


def parse_args():
    parser = argparse.ArgumentParser(
        prog="fastapi-visualizer",
        description="Statically analyze FastAPI applications and generate an interactive HTML architecture & dependency dashboard.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "project_path",
        nargs="?",
        default=".",
        help="Path to the FastAPI project directory.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="fastapi_architecture.html",
        help="Output path for the generated interactive HTML report.",
    )
    parser.add_argument(
        "-e",
        "--entrypoint",
        default=None,
        help="Optional entrypoint Python file (e.g. main.py or app/main.py).",
    )
    parser.add_argument(
        "--app",
        default=None,
        help="Optional dynamic app import string (e.g. 'app.main:app') for runtime introspection if installed.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Custom title for the dashboard.",
    )
    parser.add_argument(
        "--no-models",
        action="store_true",
        help="Exclude Pydantic / SQLModel schema nodes from the graph.",
    )
    parser.add_argument(
        "--no-deps",
        action="store_true",
        help="Exclude dependency injection nodes from the graph.",
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
    return parser.parse_args()


def main():
    args = parse_args()
    project_path = Path(args.project_path).resolve()

    if not project_path.exists():
        print(f"[!] Error: Project path does not exist: {project_path}")
        sys.exit(1)

    print(f"[*] Analyzing FastAPI project at: {project_path}")

    # 1. Analysis Phase
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

    # 2. Graph Building Phase
    builder = ArchitectureGraphBuilder(
        include_models=not args.no_models,
        include_dependencies=not args.no_deps,
    )
    arch = builder.build_graph(arch)

    # 3. HTML Rendering Phase
    renderer = HTMLRenderer(title=args.title)
    output_html_path = renderer.render(arch, args.output)
    print(f"[✓] Generated interactive HTML dashboard: {output_html_path}")

    # 4. Optional JSON Export
    if args.json:
        from dataclasses import asdict
        json_output_path = output_html_path.with_suffix(".json")
        json_data = {
            "project_name": arch.project_name,
            "project_path": arch.project_path,
            "stats": arch.stats,
            "nodes": [n.__dict__ for n in arch.nodes],
            "edges": [e.__dict__ for e in arch.edges],
            "endpoints": [asdict(ep) for ep in arch.endpoints],
            "routers": [asdict(r) for r in arch.routers],
            "dependencies": [asdict(d) for d in arch.dependencies],
            "schemas": [asdict(s) for s in arch.schemas],
            "git_diff": asdict(arch.git_diff) if arch.git_diff else None,
        }
        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False, default=str)
        print(f"[✓] Exported architecture JSON: {json_output_path}")

    # 5. Optional Mermaid Output
    if args.mermaid:
        mermaid_code = builder.generate_mermaid(arch)
        print("\n--- Mermaid Architecture Diagram ---")
        print(mermaid_code)
        print("------------------------------------\n")

    # 6. Summary Stats
    stats = arch.stats
    print(f"\n📊 Summary Statistics:")
    print(f"  • Applications: {stats.get('total_apps', 0)}")
    print(f"  • Routers:      {stats.get('total_routers', 0)}")
    print(f"  • Endpoints:    {stats.get('total_endpoints', 0)}")
    print(f"  • Dependencies: {stats.get('total_dependencies', 0)}")
    print(f"  • Schemas:      {stats.get('total_schemas', 0)}")
    if stats.get("methods_breakdown"):
        print(f"  • Methods:      {stats['methods_breakdown']}")
    if arch.git_diff and arch.git_diff.is_git_repo:
        gd = arch.git_diff
        print(f"  • Git Diff:     {gd.total_files} file(s) changed (+{gd.total_additions}, -{gd.total_deletions}) [{gd.mode_description}]")
        if gd.impacted_endpoints:
            print(f"  • Impacted API: {len(gd.impacted_endpoints)} endpoint(s)")

    # 7. Open in browser
    if args.open:
        print(f"[*] Opening {output_html_path} in default browser...")
        webbrowser.open(f"file://{output_html_path}")


if __name__ == "__main__":
    main()
