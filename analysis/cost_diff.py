import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from language_analyzers.core.serialization import SCHEMA_VERSION

NODE_METRIC_KEYS = (
    "token_cost",
    "effective_token_cost",
    "pagerank",
    "betweenness_centrality",
    "weighted_centrality_cost",
    "hop_2_token_cost",
    "hop_3_token_cost",
    "fan_in",
    "fan_out",
)

TOTAL_KEYS = ("total_token_cost", "total_effective_token_cost")

@dataclass(frozen=True)
class NodeCostDelta:
    node_id: str
    match_strategy: str
    status: str
    deltas: Mapping[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "match_strategy": self.match_strategy,
            "status": self.status,
            "deltas": dict(self.deltas),
        }


@dataclass(frozen=True)
class DiagnosticsDelta:
    introduced: Tuple[Dict[str, Any], ...]
    resolved: Tuple[Dict[str, Any], ...]
    persisted: Tuple[Dict[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "introduced": [dict(item) for item in self.introduced],
            "resolved": [dict(item) for item in self.resolved],
            "persisted": [dict(item) for item in self.persisted],
        }


@dataclass(frozen=True)
class RepositoryCostDiff:
    totals: Mapping[str, float]
    node_counts: Mapping[str, int]
    top_movers: Tuple[NodeCostDelta, ...]
    diagnostics: Optional[DiagnosticsDelta]
    match_strategy_counts: Mapping[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "totals": dict(self.totals),
            "node_counts": dict(self.node_counts),
            "top_movers": [item.to_dict() for item in self.top_movers],
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics is not None else None,
            "match_strategy_counts": dict(self.match_strategy_counts),
        }


def load_analysis_export(path: str | Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load analysis export: {exc}") from exc
    return _require_export(payload)


def _require_export(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("analysis export must be an object")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {version!r}, expected {SCHEMA_VERSION!r}")
    return payload


def _node_file_path(node: Mapping[str, Any]) -> str:
    span = node.get("span")
    if isinstance(span, Mapping) and span.get("file_path"):
        return str(span["file_path"]).replace("\\", "/")
    metadata = node.get("metadata") or {}
    if isinstance(metadata, Mapping) and metadata.get("file_path"):
        return str(metadata["file_path"]).replace("\\", "/")
    return ""


def _unique_group_match(baseline_rest, current_rest, key_of):
    matched = []
    baseline_groups: Dict[Any, List[Mapping[str, Any]]] = {}
    current_groups: Dict[Any, List[Mapping[str, Any]]] = {}
    for node in baseline_rest:
        key = key_of(node)
        if key is not None:
            baseline_groups.setdefault(key, []).append(node)
    for node in current_rest:
        key = key_of(node)
        if key is not None:
            current_groups.setdefault(key, []).append(node)
    for key in sorted(baseline_groups, key=str):
        left = baseline_groups[key]
        right = current_groups.get(key, [])
        if len(left) == 1 and len(right) == 1:
            matched.append((left[0], right[0]))
    consumed_baseline = {id(left) for left, _ in matched}
    consumed_current = {id(right) for _, right in matched}
    return (
        matched,
        [node for node in baseline_rest if id(node) not in consumed_baseline],
        [node for node in current_rest if id(node) not in consumed_current],
    )


def _match_nodes(baseline_nodes, current_nodes):
    current_by_id = {str(node.get("id")): node for node in current_nodes}
    matched: List[Tuple[Mapping[str, Any], Mapping[str, Any], str]] = []
    baseline_rest: List[Mapping[str, Any]] = []
    consumed: set = set()
    for node in baseline_nodes:
        node_id = str(node.get("id"))
        counterpart = current_by_id.get(node_id)
        if counterpart is not None:
            matched.append((node, counterpart, "id"))
            consumed.add(node_id)
        else:
            baseline_rest.append(node)
    current_rest = [node for node in current_nodes if str(node.get("id")) not in consumed]

    def symbol_key(node):
        value = str(node.get("symbol_path") or "")
        return value or None

    by_symbol, baseline_rest, current_rest = _unique_group_match(baseline_rest, current_rest, symbol_key)
    matched.extend((left, right, "symbol_path") for left, right in by_symbol)

    def shape_key(node):
        return (str(node.get("kind") or ""), str(node.get("label") or ""), _node_file_path(node))

    by_shape, baseline_rest, current_rest = _unique_group_match(baseline_rest, current_rest, shape_key)
    matched.extend((left, right, "kind_label_path") for left, right in by_shape)
    return matched, baseline_rest, current_rest


def _node_metrics(export: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    analysis = ((export.get("stats") or {}).get("analysis") or {})
    metrics = analysis.get("node_metrics") or {}
    return metrics if isinstance(metrics, Mapping) else {}


def _numeric(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _metric_deltas(baseline_metrics, current_metrics) -> Dict[str, float]:
    return {
        key: _numeric(current_metrics.get(key)) - _numeric(baseline_metrics.get(key))
        for key in NODE_METRIC_KEYS
    }


def _diagnostics_key(finding: Mapping[str, Any], translate: Mapping[str, str]) -> Tuple[str, Tuple[str, ...]]:
    node_ids = tuple(sorted(translate.get(str(item), str(item)) for item in finding.get("node_ids") or []))
    return str(finding.get("kind") or ""), node_ids


def _diagnostics_delta(baseline, current, translate) -> Optional[DiagnosticsDelta]:
    baseline_report = (baseline.get("stats") or {}).get("diagnostics")
    current_report = (current.get("stats") or {}).get("diagnostics")
    if not isinstance(baseline_report, Mapping) and not isinstance(current_report, Mapping):
        return None
    baseline_findings = (baseline_report or {}).get("findings") or []
    current_findings = (current_report or {}).get("findings") or []
    baseline_keys = {_diagnostics_key(item, translate): item for item in baseline_findings}
    current_keys = {_diagnostics_key(item, {}): item for item in current_findings}
    introduced = tuple(current_keys[key] for key in sorted(set(current_keys) - set(baseline_keys)))
    resolved = tuple(baseline_keys[key] for key in sorted(set(baseline_keys) - set(current_keys)))
    persisted = tuple(current_keys[key] for key in sorted(set(current_keys) & set(baseline_keys)))
    return DiagnosticsDelta(introduced, resolved, persisted)


def diff_repository_cost(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    top_movers: int = 20,
) -> RepositoryCostDiff:
    baseline = _require_export(baseline)
    current = _require_export(current)
    if isinstance(top_movers, bool) or not isinstance(top_movers, int) or top_movers < 0:
        raise ValueError("top_movers must be a non-negative integer")

    baseline_analysis = (baseline.get("stats") or {}).get("analysis") or {}
    current_analysis = (current.get("stats") or {}).get("analysis") or {}
    totals = {
        key: _numeric(current_analysis.get(key)) - _numeric(baseline_analysis.get(key))
        for key in TOTAL_KEYS
    }

    baseline_metrics = _node_metrics(baseline)
    current_metrics = _node_metrics(current)
    matched, baseline_only, current_only = _match_nodes(baseline.get("nodes") or [], current.get("nodes") or [])

    strategy_counts = {"id": 0, "symbol_path": 0, "kind_label_path": 0}
    deltas: List[NodeCostDelta] = []
    translate: Dict[str, str] = {}
    for baseline_node, current_node, strategy in matched:
        strategy_counts[strategy] += 1
        baseline_id = str(baseline_node.get("id"))
        current_id = str(current_node.get("id"))
        translate[baseline_id] = current_id
        node_deltas = _metric_deltas(
            baseline_metrics.get(baseline_id) or {},
            current_metrics.get(current_id) or {},
        )
        status = "changed" if any(value != 0.0 for value in node_deltas.values()) else "unchanged"
        if status == "changed":
            deltas.append(NodeCostDelta(current_id, strategy, status, node_deltas))
    for node in current_only:
        node_id = str(node.get("id"))
        deltas.append(NodeCostDelta(node_id, "none", "added", _metric_deltas({}, current_metrics.get(node_id) or {})))
    for node in baseline_only:
        node_id = str(node.get("id"))
        deltas.append(NodeCostDelta(node_id, "none", "removed", _metric_deltas(baseline_metrics.get(node_id) or {}, {})))

    deltas.sort(key=lambda item: (-abs(item.deltas.get("weighted_centrality_cost", 0.0)), item.node_id))
    return RepositoryCostDiff(
        totals=totals,
        node_counts={"added": len(current_only), "removed": len(baseline_only), "matched": len(matched)},
        top_movers=tuple(deltas[:top_movers]),
        diagnostics=_diagnostics_delta(baseline, current, translate),
        match_strategy_counts=strategy_counts,
    )


def cost_diff_to_dict(repository: RepositoryCostDiff) -> Dict[str, Any]:
    return {"repository": repository.to_dict()}
