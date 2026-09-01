# Match Nodes Across Two Analysis States by id, symbol_path, then Shape

**Status:** Accepted
**Date:** 2026-09-01

## Decision

The exploration cost diff resolves node identity across two exported analysis states in three ordered stages — exact `id`, then `symbol_path`, then `(kind, label, file path)` — and a stage matches only when its key is unique on both sides. The strategy that produced each match is counted in `match_strategy_counts`.

Node ids are not stable identifiers: some embed line numbers, so an edit above a symbol renames it. Without a fallback, ordinary edits report as deletions plus additions and every metric delta becomes noise.

## Alternatives Considered

- **Match on `id` alone**: rejected because line-number-bearing ids turn unrelated edits into large false churn, which defeats the purpose of comparing two states.
- **Similarity or fuzzy matching (name distance, span overlap)**: rejected because it is not deterministic across runs and would make a diff unreproducible, which the milestone requires.
- **Require analyzers to emit stable ids**: rejected because id stability is a per-adapter guarantee that cannot be enforced across the framework and language tracks, and changing it now would invalidate existing exports.

## Consequences

- A symbol that is renamed and moved in the same change reports as a deletion plus an addition. This is visible in `match_strategy_counts` rather than silently smoothed over.
- Two symbols sharing a `symbol_path` are never matched at that stage; they fall through to shape matching or to added/removed.
- Diagnostics comparison depends on this mapping: baseline finding node ids are translated to current ids before classification, so a finding survives an id change.
