# Separate Analysis, Framework Helpers, and Rendering

**Status:** Accepted
**Date:** 2026-08-31

## Decision

Use one-way dependencies: language analyzers provide reusable parsing and symbol graphs; framework analyzers add framework semantics; analysis computes framework-independent metrics; renderers consume completed report data.

Report assets are written beside the report. Token cost is a configurable characters-per-token estimate that remains replaceable by a calibrated measurement.

## Alternatives Considered

- **Keep one FastAPI package**: rejected because it couples general metrics and rendering concerns to FastAPI.
