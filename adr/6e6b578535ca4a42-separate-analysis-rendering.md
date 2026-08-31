# Separate Analysis, Framework Helpers, and Rendering

**Status:** Accepted
**Date:** 2026-08-31
**Deciders:** Repository maintainers

## Context

The original package combined FastAPI extraction, graph construction, metrics, and a large HTML f-string. The repository now targets framework-independent analysis of AI-agent exploration cost while retaining FastAPI as the first semantic helper.

## Decision

Use three one-way layers:

1. `analysis/` computes framework-independent graph and token-cost metrics.
2. `framework_helpers/fastapi/` extracts FastAPI semantics and builds its graph representation before invoking the analysis layer.
3. `renderers/html/` consumes completed report data and owns separate HTML, CSS, and JavaScript assets.

The renderer writes assets beside each report instead of embedding application code and styles in Python. Token cost initially uses a configurable characters-per-token estimate over the smallest AST definition containing a node's source line. This approximation remains explicit and replaceable.

## Alternatives Considered

- **Keep one FastAPI package**: simpler short-term, but keeps generic metrics coupled to FastAPI and UI concerns. Rejected for lacking a stable boundary for future framework helpers.

## Consequences

- New framework helpers can reuse graph metrics without importing FastAPI code; renderers can change independently of graph algorithms.
- HTML reports now depend on a sibling `<report-name>_assets/` directory.
- Source token costs are estimates until calibrated against a model tokenizer or agent traces.
- The FastAPI graph model is not yet the final generic repository graph schema.

## Action Items

1. Add a language-level symbol graph producer above framework helpers.
2. Calibrate token estimation against observed agent context usage.
3. Define a renderer-neutral serialized report schema.
