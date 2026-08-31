# Separate Analysis, Framework Helpers, and Rendering

**Status:** Accepted
**Date:** 2026-08-31
**Deciders:** Repository maintainers

## Context

The original package combined FastAPI extraction, graph construction, metrics, and a large HTML f-string. The repository now targets framework-independent analysis of AI-agent exploration cost while retaining FastAPI as the first semantic helper.

## Decision

Use language and framework layers with one-way dependencies:

1. `language_analyzers/` owns reusable language parsing and generic symbol graphs.
2. `framework_analyzers/` imports language analyzers to add framework semantics; language analyzers never import framework analyzers.
3. `analysis/` computes framework-independent graph and token-cost metrics.
4. `renderers/html/` consumes completed report data and owns separate HTML, CSS, and JavaScript assets.

The renderer writes assets beside each report instead of embedding application code and styles in Python. Token cost initially uses a configurable characters-per-token estimate over the smallest AST definition containing a node's source line. This approximation remains explicit and replaceable.

## Alternatives Considered

- **Keep one FastAPI package**: simpler short-term, but keeps generic metrics coupled to FastAPI and UI concerns. Rejected for lacking a stable boundary for future framework helpers.

## Consequences

- Framework analyzers can be replaced without changing language graphs; renderers can change independently of graph algorithms.
- HTML reports now depend on a sibling `<report-name>_assets/` directory.
- Source token costs are estimates until calibrated against a model tokenizer or agent traces.
- The FastAPI graph model is not yet the final generic repository graph schema.

## Action Items

1. Calibrate token estimation against observed agent context usage.
2. Define a renderer-neutral serialized report schema.
