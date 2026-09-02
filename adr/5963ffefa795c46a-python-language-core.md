# A Language Core Beneath the Framework Adapters

**Status:** Accepted
**Date:** 2026-08-31

## Decision

Language semantics belong in reusable language cores rather than framework adapters. Framework components remain distinct from language symbols and connect through `IMPLEMENTED_BY`: one handler can implement multiple routes, while a node has one category.

Uncertain, ambiguous, and unresolved relations are retained with confidence and candidate information rather than discarded.

## Alternatives Considered

- **Extend the FastAPI analyzer**: rejected because general language semantics would be duplicated by every framework adapter.
- **Merge routes and handlers**: rejected because it loses the many-routes-to-one-handler relationship and gives a node conflicting categories.
- **Use tree-sitter, griffe, or jedi for Python**: rejected because Python's `ast` already provides the required source information without adding runtime dependencies; griffe would hide re-exports that should remain visible, and jedi's repository-wide inference is too costly.
- **Keep TypeScript regular expressions**: rejected because false relations would corrupt the confidence signal.
