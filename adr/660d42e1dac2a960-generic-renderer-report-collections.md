# Generalize HTML Renderer to Framework-Declared Report Collections

**Status:** Accepted
**Date:** 2026-08-31
**Deciders:** Repository maintainers

## Context

The HTML renderer assumes FastAPI's vocabulary. A second framework adapter therefore cannot reuse it without duplication or misleading labels.

## Decision

Replace fixed collections with a framework-declared report-collection contract. Each adapter, including FastAPI, supplies its collections and the renderer presents them generically.

## Alternatives Considered

- **Separate renderer per framework**: rejected because it duplicates rendering logic.
- **Remap foreign concepts to fixed FastAPI names**: rejected because it mislabels data.

## Consequences

- FastAPI's inspector drawer gives up category-specific visual tuning for framework-neutral rendering.
