# Shell-Consistent Exploration Order for Min/Expected/Max Cost

**Status:** Accepted
**Date:** 2026-09-02
**Decider:** Repository owner

## Context

M1 requires a minimum, expected, and maximum exploration cost for discovering a task's target node. ROADMAP.md defines min as an oracle-efficient search and max/expected as a search that "cannot distinguish candidates before reading them," with expected using "a uniformly random exploration order" — but it does not define what a valid order is over a graph where candidates become visible incrementally as nodes are opened. Without that definition, "uniformly random order" is ambiguous: a full random permutation over every eventually-reachable node is a different (and unbounded) process than a random order constrained by which nodes have actually become visible so far.

## Decision

Define a valid exploration order as **shell-consistent**: nodes are opened in non-decreasing node-weighted graph distance from the start frontier (the same distance a node-weighted Dijkstra run produces), and only the relative order of nodes tied at the same distance is treated as random. The exploration graph is undirected over every graph relation.

This gives closed-form, deterministic costs from a single Dijkstra run:
- **Min** = the weighted shortest-path cost to the target (`dist[target]`).
- **Max** = the total cost of every node whose distance is `<= dist[target]` (the "cost ball"), since none of them can be ruled out as irrelevant before being opened.
- **Expected** = every node strictly closer than the target counted at full weight (it is opened before the target under any shell-consistent order, not merely likely to be), plus the target's own cost, plus half the cost of every node tied with the target at the same distance (by pairwise symmetry, each tied node has exactly a 1/2 chance of being opened before the target under a uniformly random order within the tie).

Multi-target tasks require full recall. Their minimum is the exact minimum-cost node-weighted Steiner tree joining one start node and every target; shared nodes are charged once. Their expected and maximum costs use the shell containing the furthest required target. In that final shell, each non-target node is charged by the probability that it appears before the last required target.

Confidence ranges are edge-inclusion scenarios, because the model charges node reads rather than edge traversal: optimistic includes every confidence level, baseline excludes `dynamic_required`, and pessimistic retains only `static_certain` edges.

## Alternatives Considered

- **Fully random topological order over the whole candidate-expansion DAG** (a node becomes eligible as soon as any neighbor is opened, with no distance constraint on relative order): rejected because max cost is then unbounded by the target's own distance — an adversarial order could wander arbitrarily far into unrelated branches before ever approaching the target, and there is no closed form for the expected value (computing it exactly is a linear-extension counting problem, which is intractable in general).
- **Fixed hop-count neighborhoods (reusing the existing `hop_2`/`hop_3` pattern from `graph_metrics.py` directly, i.e. an unweighted distance bound)**: rejected because it ignores per-node token cost entirely when deciding which nodes are "close enough to matter," so a single expensive node one hop closer than the target would not appear in the cost accounting at all.

## Consequences

- `ball_node_ids` (the set of nodes within the target's weighted distance) becomes a reusable concept: it is both the max-cost node set and, once M3 defines structural bottlenecks, is expected to be reused there as the "non-target candidates exposed" set referenced in ROADMAP.md's 부가 산출물 table. Changing this distance model later would change that downstream meaning too.
- Any node with a strictly-vendored/generated cost multiplier of 0 on a tied or closer path is invisible to expected/max cost even though it is still traversed — consistent with how `effective_token_cost` already treats those nodes elsewhere.
- Multi-target exact minimization is exponential in the number of required targets; it is appropriate for the labeled M1 task sets, not an unbounded bulk query API.
