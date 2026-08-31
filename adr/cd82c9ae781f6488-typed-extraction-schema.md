# Typed Extraction Schema for Graph Nodes and Edges

**Status:** Accepted
**Date:** 2026-08-31
**Deciders:** Repository maintainers

## Context

`GraphNode` and `GraphEdge` were vis.js view models. Half of `GraphNode` (`shape`, `size`, `color`, HTML `title`) is presentation, and every semantic fact travelled in an untyped `metadata` dict under conventions no code declared: `analysis/graph_metrics.py` read `metadata["file_path"]`, `["line_number"]`, `["end_line_number"]`, and adapters happened to write them. Nothing could express a source range, a read cost, how far a relation could be trusted, or where a relation was written.

Three consequences followed. Token cost was reverse-engineered: with no end line, `GraphAnalyzer` re-parsed the file and guessed the smallest AST node enclosing a line, degrading to whole-file or metadata length when that failed. Edge confidence, which `IDEA.md` requires in four grades, had nowhere to live, so the least certain inferences — FastAPI's substring matching, TypeScript's ambiguous name resolution — discarded exactly the signal that made them uncertain. Structural friction (dynamic imports, reflection, barrel re-exports, name collisions, generated code) is observable only while parsing and was recorded nowhere.

## Decision

Add typed fields to the core graph model and let extraction own them.

`GraphNode` gains `kind`, `language`, `span: SourceSpan`, `cost: NodeCost`, `signature`, `docstring`, `exported`, `symbol_path`, `flags`, and `provenance`. `GraphEdge` gains `confidence`, `resolution`, `evidence: SourceSpan`, `candidates`, `weight`, and `metadata`. `Confidence` and `Resolution` are string enums; `NodeKind` and `RelationKind` centralize vocabularies that were previously string literals at each call site.

Analyzers fill `span` and compute `cost` from it at extraction time. `analysis/graph_metrics.py` prefers `node.cost`, keeping its AST guess only as a fallback for nodes without a span. Relations that cannot be resolved keep an edge with `dynamic_required`/`unresolved` rather than being dropped, and ambiguous ones keep their rejected candidates.

`metadata` is demoted to adapter-specific data. Because existing consumers read the conventional keys, `GraphNode.__post_init__` mirrors `span` into them; the mirror is a compatibility shim, not the way new fields reach the dashboard. `language_analyzers/core/serialization.py` defines one neutral schema (`schema_version: 2`) that both the `--json` export and the HTML renderer use, and the renderer maps confidence onto line style so presentation stays out of the analyzers.

## Alternatives Considered

- **Keep using `metadata` by convention**: no migration cost, but the fields most needed downstream stay undeclared and unvalidated, and the token-cost guess stays load-bearing. Rejected because the diagnosis layer this schema exists to feed needs cost and confidence to be reliable, not conventional.
- **Split view models from analysis models entirely**: cleanest separation, but it forces every adapter, the renderer, the CLI, and the metrics layer to translate between two shapes at once. Rejected as disproportionate now; the neutral serialization schema captures most of the benefit and leaves the split available later.
- **Compute cost with a real tokenizer**: more accurate, but adds a dependency and ties costs to one model's vocabulary. Rejected for now; `characters_per_token` stays configurable in one place.

## Consequences

- Token cost is exact for every node whose analyzer reports a span, and is no longer re-derived downstream.
- Confidence is a first-class field, so a later diagnosis layer can weight or exclude uncertain edges instead of treating all edges alike.
- Friction signals are recorded as raw observations (`flags`, `unresolved_calls`, `candidates`) with no judgement attached; scoring them is a separate decision.
- Every adapter must now populate the typed fields to benefit; an adapter that only sets `metadata` still works but stays on the fallback path.
- The `metadata` mirror is duplicated state. It exists only for compatibility and should be removed once no consumer reads the conventional keys.
- This closes the "define a renderer-neutral serialized report schema" action item from ADR `6e6b578535ca4a42`.
