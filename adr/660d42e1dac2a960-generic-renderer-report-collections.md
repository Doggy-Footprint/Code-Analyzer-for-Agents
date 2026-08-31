# Generalize HTML Renderer to Framework-Declared Report Collections

**Status:** Accepted
**Date:** 2026-08-31

## Decision

Framework adapters declare report collections and the renderer presents them generically.

## Alternatives Considered

- **Separate renderer per framework**: rejected because it duplicates rendering logic.
- **Map foreign concepts to FastAPI names**: rejected because it mislabels data.

## Consequences

- FastAPI-specific visual tuning is limited by framework-neutral rendering.
