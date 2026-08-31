# Typed Extraction Schema for Graph Nodes and Edges

**Status:** Accepted
**Date:** 2026-08-31

## Decision

Extraction owns typed source spans, costs, relation confidence, evidence, candidates, and friction signals. Unresolved or ambiguous relations are retained with their uncertainty instead of being dropped.

`metadata` is an adapter-specific compatibility shim, not the contract for new data, and can be removed after consumers migrate. JSON export and HTML rendering share one renderer-neutral serialization schema.

## Alternatives Considered

- **Keep `metadata` conventions**: rejected because required downstream facts would remain undeclared and unvalidated.
- **Split analysis and view models immediately**: rejected because the required translations across adapters and consumers are disproportionate at this stage.
- **Use a real tokenizer for cost**: rejected for now because it adds a dependency and makes costs model-specific.
