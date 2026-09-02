File: f955da9142e1937a-retrievability-cost-and-generated-code-policy.md
Summary: Preserves generated code in language cores while charging retrieval gaps for unresolvable framework relations without asserting fabricated code edges.
Related Files: language_analyzers/core/flags.py, language_analyzers/python/source.py, language_analyzers/kotlin/analyzer.py, language_analyzers/typescript/analyzer.py, framework_analyzers/android/analyzer.py, framework_analyzers/android/models.py, framework_analyzers/android/graph.py, language_analyzers/core/serialization.py
Related Symbols: is_generated_path, PythonSourceAnalyzer, KotlinAnalyzer, TypeScriptAnalyzer, AndroidAnalyzer, DiBindingInfo, EvaluationRelation, AndroidArchitectureGraphBuilder, architecture_to_dict

---

File: 6e6b578535ca4a42-separate-analysis-rendering.md
Summary: Separates generic graph analysis, FastAPI semantics, and HTML rendering into one-way layers.
Related Files: analysis/graph_metrics.py, language_analyzers/typescript/analyzer.py, framework_analyzers/fastapi/graph.py, renderers/html/renderer.py
Related Symbols: GraphAnalyzer, ArchitectureGraphBuilder, HTMLRenderer

---

File: 660d42e1dac2a960-generic-renderer-report-collections.md
Summary: Replaces the renderer's fixed FastAPI-shaped collections with a framework-declared ReportCollection/ColumnSpec contract usable by any framework adapter.
Related Files: renderers/html/renderer.py, renderers/html/templates/dashboard.html, renderers/html/static/app.js, language_analyzers/core/report_schema.py, framework_analyzers/fastapi/graph.py, framework_analyzers/android/graph.py
Related Symbols: ReportCollection, ColumnSpec, HTMLRenderer, GitDiffInfo

---

File: cd82c9ae781f6488-typed-extraction-schema.md
Summary: Moves source span, read cost, edge confidence, evidence and friction flags out of the untyped metadata dict into typed fields the analyzers fill at extraction time.
Related Files: language_analyzers/core/graph_models.py, language_analyzers/core/cost.py, language_analyzers/core/flags.py, language_analyzers/core/annotate.py, language_analyzers/core/serialization.py, analysis/graph_metrics.py, renderers/html/renderer.py, renderers/html/static/app.js
Related Symbols: GraphNode, GraphEdge, SourceSpan, NodeCost, Confidence, Resolution, NodeKind, RelationKind, architecture_to_dict, annotate_nodes, GraphAnalyzer

---

File: 5963ffefa795c46a-python-language-core.md
Summary: Builds a real Python symbol graph under the framework adapters, links framework components to it with IMPLEMENTED_BY, and fixes the parser choice per language (stdlib ast for Python, tree-sitter for TypeScript).
Related Files: language_analyzers/python/symbols.py, language_analyzers/python/graph.py, language_analyzers/typescript/ast.py, language_analyzers/typescript/analyzer.py, framework_analyzers/fastapi/graph.py, code_analyzer/cli.py
Related Symbols: PythonGraphAnalyzer, SymbolTable, build_symbol_table, resolve_relative_module, TypeScriptAnalyzer, ArchitectureGraphBuilder

---

File: 2fa75a6058d4f5eb-cost-diff-node-identity.md
Summary: Matches nodes across two analysis states by id, then symbol_path, then (kind, label, file path), only when unique on both sides.
Related Files: analysis/cost_diff.py, code_analyzer/cli.py, language_analyzers/core/serialization.py
Related Symbols: diff_repository_cost, _match_nodes, _unique_group_match, NodeCostDelta, RepositoryCostDiff

---

File: f5d6125852c61319-percentile-with-absolute-floor.md
Summary: Reports structural friction only when a metric clears both the repository's nearest-rank percentile cut and an absolute floor, recording the resolved cuts.
Related Files: analysis/friction_diagnostics.py, code_analyzer/cli.py
Related Symbols: FrictionDiagnoser, DiagnosticsConfig, DiagnosticsReport, _quantile
