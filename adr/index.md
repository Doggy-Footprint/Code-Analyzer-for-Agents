File: 6e6b578535ca4a42-separate-analysis-rendering.md
Summary: Separates generic graph analysis, FastAPI semantics, and HTML rendering into one-way layers.
Related Files: analysis/graph_metrics.py, framework_helpers/fastapi/graph.py, renderers/html/renderer.py
Related Symbols: GraphAnalyzer, ArchitectureGraphBuilder, HTMLRenderer

---

File: 660d42e1dac2a960-generic-renderer-report-collections.md
Summary: Replaces the renderer's fixed FastAPI-shaped collections with a framework-declared ReportCollection/ColumnSpec contract usable by any framework adapter.
Related Files: renderers/html/renderer.py, renderers/html/templates/dashboard.html, renderers/html/static/app.js, framework_helpers/common/report_schema.py, framework_helpers/fastapi/graph.py, framework_helpers/android/graph.py
Related Symbols: ReportCollection, ColumnSpec, HTMLRenderer, GitDiffInfo
