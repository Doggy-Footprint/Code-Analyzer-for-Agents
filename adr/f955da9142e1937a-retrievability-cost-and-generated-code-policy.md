# Retrievability Cost and Generated Code Policy

**Status:** Accepted
**Date:** 2026-09-01
**Decider:** Repository owner

## Context

The analyzer evaluates repository exploration cost. Generated code may be evidence for a real implementation path even when it is not a normal editing target. Framework-derived relations may identify a source location without resolving to a concrete source symbol.

## Decision

- Language cores retain generated source unless their existing general discovery exclusions apply. Generated nodes keep the `generated` flag and their existing reduced-cost and diagnostic-population treatment.
- Framework adapters may exclude generated source from framework-specific extraction. When a framework graph is combined with its language graph, the language graph is added unchanged; the adapter exclusion must not remove language-core nodes or edges.
- Android+Kotlin therefore consists of the Android framework graph, the complete Kotlin language-core graph, and cross-layer relations. `--no-language-graph` removes only the Kotlin layer.
- Extraction models retain enough source identity to resolve cross-layer relations.
- When a relation resolves to a concrete symbol, record the normal code-fact relation. When it cannot be resolved and deterministic lexical retrieval cannot identify the endpoint, record a retrieval-gap cost on the relation/evidence instead of asserting a code-fact edge to an invented symbol.
- Retrieval-gap cost is a distinct exploration penalty. It must be visible in evaluation output, excluded from structural connectivity and code-fact diagnostics, and must not be added again when the same relation already contributes an unresolved or dynamic-resolution penalty.

## Alternatives Considered

- **Exclude generated source from every language core:** rejected because generated code can explain real implementation paths, and removes evidence needed to assess exploration effort.
- **Include generated source in framework extraction as well:** rejected because generated framework components create noisy semantic nodes without improving the language-core evidence.
- **Add a normal edge to a fabricated unresolved symbol:** rejected because it would change graph connectivity and present an unverified code fact as a relationship.
- **Ignore unresolvable framework relations:** rejected because it underestimates the work required to investigate implicit or framework-mediated behavior.
- **Treat every unresolved relation as an additional retrieval gap:** rejected because it double-counts uncertainty already represented by unresolved/dynamic resolution metadata.

## Consequences

- Cross-layer graph composition has a stable subgraph contract: enabling a framework must not alter the underlying language graph.
- Evaluation distinguishes a missing semantic link from a relation that requires extra repository search to resolve.
- Consumers of structural metrics must ignore retrieval-gap-only records; cost/report consumers must expose their penalty and evidence.
- Parser-cache sharing remains a separate performance concern and is not part of this decision.
