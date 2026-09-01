# Diagnose Structural Friction on a Percentile Cut Combined with an Absolute Floor

**Status:** Accepted
**Date:** 2026-09-01

## Decision

A structural friction detector reports a node only when its metric clears both the nearest-rank percentile of that metric's distribution within the analyzed repository and a configured absolute floor. The resolved cut values are written to `thresholds` in every diagnostics report.

## Alternatives Considered

- **Absolute thresholds only**: rejected because a single token or centrality value cannot hold across repository sizes and languages, so every repository would need tuning before the tool says anything useful.
- **Percentile only**: rejected because a percentile always selects a top slice. A small or already healthy repository would still be handed findings, which trains the reader to ignore them.

## Consequences

- A repository whose largest symbol is below the floor produces no findings at all, and that is the intended answer rather than a failure.
- Findings are not comparable across repositories as absolute severity; they are statements about a repository relative to itself plus a minimum bar.
- Because the cut depends on the population, the same node can enter or leave the report when unrelated parts of the repository change. Recording the resolved cuts is what makes such a change explainable.
