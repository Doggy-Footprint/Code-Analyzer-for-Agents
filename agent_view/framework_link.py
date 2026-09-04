import hashlib
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from language_analyzers.core.cost import estimate_tokens
from language_analyzers.core.graph_models import Confidence

from .exact_query import occurrence_digest, render_occurrences
from .models import FrameworkLink, Occurrence, QueryNode, ReadableNode
from .occurrence import OccurrenceIndex
from .profile import Profile

_SPECIFICITIES = ("unique", "narrowing")


def link_id(from_node_id: str, rule_id: str, specificity: str, targets: Sequence[str]) -> str:
    if specificity == "narrowing":
        return f"{from_node_id}|{rule_id}"
    return f"{from_node_id}|{rule_id}|{targets[0]}"


def framework_query_id(from_node_id: str, rule_id: str, version: int) -> str:
    payload = f"framework|{from_node_id}|{rule_id}|{version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _rule(edge: Any):
    metadata = getattr(edge, "metadata", None) or {}
    rule = metadata.get("framework_rule")
    if not isinstance(rule, dict):
        return None
    rule_id = rule.get("id")
    specificity = rule.get("specificity")
    if not isinstance(rule_id, str) or specificity not in _SPECIFICITIES:
        return None
    return rule_id, specificity


def build_framework_links(
    edges: Sequence[Any],
    readable_by_id: Mapping[str, ReadableNode],
    index: OccurrenceIndex,
    profile: Profile,
) -> Tuple[List[FrameworkLink], List[QueryNode], List[str]]:
    unknown: List[str] = []
    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for edge in edges:
        if str(getattr(edge, "confidence", "")) != str(Confidence.FRAMEWORK_INFERRED):
            continue
        rule = _rule(edge)
        if rule is None:
            # 미선언 규칙에 specificity 기본값을 주지 않는다. unique로 접으면 비확정 관계가
            # 확정 관계로 집계되고, narrowing으로 접으면 없는 query node가 생긴다. 둘 다
            # 조용히 비용을 왜곡하므로 adapter가 선언할 때까지 보고만 한다.
            unknown.append(f"{edge.from_id}->{edge.to_id}")
            continue
        rule_id, specificity = rule
        if edge.to_id not in readable_by_id:
            continue
        evidence = getattr(edge, "evidence", None)
        evidence_file = evidence.file_path if evidence is not None else "<framework-inference>"
        evidence_line = evidence.start_line if evidence is not None else 1
        key = (edge.from_id, rule_id, specificity)
        if specificity == "unique":
            key = (edge.from_id, rule_id, f"unique:{edge.to_id}")
        group = groups.get(key)
        if group is None:
            group = {
                "from_node_id": edge.from_id,
                "rule_id": rule_id,
                "specificity": specificity,
                "to_node_ids": set(),
                "candidate_node_ids": set(),
                "resolution": str(getattr(edge, "resolution", "")),
                "evidence": (evidence_file, evidence_line),
            }
            groups[key] = group
        group["to_node_ids"].add(edge.to_id)
        group["candidate_node_ids"].update(
            candidate for candidate in getattr(edge, "candidates", None) or []
            if candidate in readable_by_id
        )

    links: List[FrameworkLink] = []
    queries: List[QueryNode] = []
    for key in sorted(groups):
        group = groups[key]
        targets = sorted(group["to_node_ids"])
        if not targets:
            continue
        query_id = None
        if group["specificity"] == "narrowing":
            query_id = framework_query_id(group["from_node_id"], group["rule_id"], profile.ref.version)
            occurrences = [
                Occurrence(
                    file_path=readable_by_id[target].file_path,
                    line=readable_by_id[target].start_line or 1,
                    col=0,
                    matched_text=group["rule_id"],
                    context="code",
                    enclosing_node_id=target,
                )
                for target in targets
            ]
            occurrences.sort(key=lambda item: (item.file_path, item.line, item.col))
            excluded = len(targets) > profile.max_arrival_nodes
            queries.append(QueryNode(
                id=query_id,
                term=group["rule_id"],
                kind="framework",
                clue_kinds=[],
                origin_node_ids=[group["from_node_id"]],
                rule_id=group["rule_id"],
                source_terms=[],
                occurrences=occurrences,
                occurrence_digest=occurrence_digest(occurrences),
                arrival_node_ids=targets,
                output_tokens=estimate_tokens(render_occurrences(occurrences)),
                excluded=excluded,
                exclusion_reason="too_many_arrival_nodes" if excluded else None,
            ))
        links.append(FrameworkLink(
            id=link_id(group["from_node_id"], group["rule_id"], group["specificity"], targets),
            from_node_id=group["from_node_id"],
            rule_id=group["rule_id"],
            specificity=group["specificity"],
            resolution=group["resolution"],
            to_node_ids=targets,
            candidate_node_ids=sorted(group["candidate_node_ids"] - set(targets)),
            query_id=query_id,
            evidence_file=group["evidence"][0],
            evidence_line=group["evidence"][1],
        ))

    links.sort(key=lambda item: item.id)
    queries.sort(key=lambda item: item.id)
    return links, queries, sorted(set(unknown))
