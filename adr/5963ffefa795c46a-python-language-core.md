# A Language Core Beneath the Framework Adapters

**Status:** Accepted
**Date:** 2026-08-31
**Deciders:** Repository maintainers

## Context

ADR `6e6b578535ca4a42` declared that `language_analyzers/` owns reusable language parsing and `framework_analyzers/` adds framework semantics on top. For Python the lower layer was never built. `language_analyzers/python/` discovered files and called `ast.parse`; all Python meaning lived in `framework_analyzers/fastapi/analyzer.py`, which walks only `tree.body`, so class methods, nested functions and anything inside `try`/`with` were invisible. The resulting graph held `app`, `router`, `endpoint`, `dependency` and `schema` nodes and no file, module, class or plain function nodes — and therefore no `IMPORTS`, `CALLS`, `INHERITS` or `TYPE_USES` edges at all. A repository's actual structure was absent from the graph meant to describe it.

TypeScript had the opposite problem: a language analyzer existed, but it was regular expressions over raw text. It matched calls inside comments and string literals, could not see `interface`, `type`, `enum` or re-exports, and parsed import bindings only to discard them before resolution.

## Decision

Build `language_analyzers/python/` into a real symbol-graph layer (`symbols.py`, `graph.py`) that emits package/module/class/function/method/field/constant nodes and `CONTAINS`, `IMPORTS`, `IMPORTS_SYMBOL`, `RE_EXPORTS`, `CALLS`, `INSTANTIATES`, `INHERITS`, `DECORATES`, `TYPE_USES`, `READS` and `WRITES` edges, each carrying confidence and the source line where the relation is written. Resolution walks a scope chain — locals, enclosing scope, class and its bases, module bindings including import aliases — then falls back to project-wide name matching, degrading from `exact` through `unique_name` to `ambiguous` with the rejected candidates retained.

The FastAPI adapter sits on this layer rather than replacing it. Framework nodes stay distinct from language nodes and are joined by `IMPLEMENTED_BY` edges, because one handler function can back several routes and the dashboard's category filters and `ReportCollection.node_category` contract assume one category per node. `--no-language-graph` restores the framework-only graph.

**Parsers.** Python uses the standard library `ast`. TypeScript moves from regular expressions to tree-sitter via the already-declared `tree-sitter-language-pack`, following the helper-module pattern `language_analyzers/kotlin/ast.py` established.

## Alternatives Considered

- **Keep extending `framework_analyzers/fastapi/analyzer.py`**: no new module, but it would put general Python semantics inside a FastAPI adapter, leaving Django or Flask to reimplement them and contradicting the layering ADR `6e6b578535ca4a42` set. Rejected.
- **Merge endpoint and handler into one node**: a smaller graph and one fewer edge kind, but it conflates a route with the function implementing it, breaks for one function serving several routes, and forces a node into two categories at once. Rejected.
- **tree-sitter for Python too, for a uniform stack**: appealing for symmetry, but `ast` is the reference parser and already supplies `end_lineno`, annotations and docstrings; tree-sitter would add an import-time dependency to the FastAPI path, which today runs with none. Rejected.
- **`griffe` for Python alias and re-export resolution**: it resolves re-export chains accurately, but this analyzer's purpose is to *record* barrel re-exports as a friction signal, not to see through them — and it adds a dependency for something the symbol table already does. Rejected.
- **`jedi` for Python name resolution**: the most accurate option and it would raise many `static_inferred` edges to `exact`, but per-file inference is slow over a whole repository and the dependency is heavy. Rejected for now; the scope chain plus explicit confidence grades makes the uncertainty visible instead of hiding it.
- **Keep the TypeScript regular expressions and mark their output low-confidence**: cheaper, but it labels false edges (calls inside comments and strings) as merely uncertain rather than removing them, which corrupts the confidence signal the other ADR introduces. Rejected.

## Consequences

- The graph now describes the repository's real structure: on `examples/realworld_app` it grows from 79 nodes and 104 edges to roughly 600 and 1,700.
- Framework adapters get import, call and inheritance context for free, and every framework component is linked to the symbol implementing it.
- Uncertainty is explicit. Name-based resolution produces `static_inferred` edges, and ambiguous ones list the candidates that were not chosen; consumers must decide how to weight them.
- TypeScript analysis now requires `tree-sitter` and `tree-sitter-language-pack`, as Android already did. Without them the analyzer raises a clear `ImportError` and its tests skip.
- Graph size grows roughly tenfold, which matters for the exact betweenness computation in `analysis/graph_metrics.py` on large repositories. `--no-language-graph` is the escape hatch; a cheaper metric may be needed later.
- Kotlin still has no language core. `language_analyzers/kotlin/ast.py` already exposes the helpers one would need.
