File: 6e6b578535ca4a42-separate-analysis-rendering.md
Summary: Separates generic graph analysis, FastAPI semantics, and HTML rendering into one-way layers.
Related Files: analysis/graph_metrics.py, language_analyzers/typescript/analyzer.py, framework_analyzers/fastapi/graph.py, renderers/html/renderer.py
Related Symbols: GraphAnalyzer, ArchitectureGraphBuilder, HTMLRenderer

---

File: 660d42e1dac2a960-generic-renderer-report-collections.md
Summary: Replaces the renderer's fixed FastAPI-shaped collections with a framework-declared ReportCollection/ColumnSpec contract usable by any framework adapter.
Related Files: renderers/html/renderer.py, renderers/html/templates/dashboard.html, renderers/html/static/app.js, language_analyzers/core/report_schema.py, framework_analyzers/fastapi/graph.py, framework_analyzers/android/graph.py
Related Symbols: ReportCollection, ColumnSpec, HTMLRenderer, GitDiffInfo
