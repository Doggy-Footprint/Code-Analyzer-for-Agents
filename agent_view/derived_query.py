import dataclasses
import re
from typing import Dict, List, Mapping, Tuple

from .exact_query import Clue, make_query_node
from .models import QueryNode
from .occurrence import OccurrenceIndex
from .profile import Profile

_TOKEN_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")
_VOWELS = "aeiou"


def split_tokens(identifier: str) -> List[str]:
    tokens: List[str] = []
    for part in re.split(r"[^A-Za-z0-9]+", identifier):
        if not part:
            continue
        for match in re.finditer(r"[A-Za-z]+|[0-9]+", part):
            chunk = match.group(0)
            if chunk.isdigit():
                tokens.append(chunk)
            else:
                tokens.extend(item.group(0) for item in _TOKEN_RE.finditer(chunk))
    return tokens


def _pluralize(term: str) -> str:
    if term.endswith("ies"):
        return term[:-3] + "y"
    if term.endswith("s") and not term.endswith("ss"):
        return term[:-1]
    if term.endswith("y") and len(term) > 1 and term[-2].lower() not in _VOWELS:
        return term[:-1] + "ies"
    return term + "s"


def _strip_affix(identifier: str, prefixes, suffixes) -> List[str]:
    results: List[str] = []
    for prefix in prefixes:
        if identifier.startswith(prefix) and len(identifier) > len(prefix):
            remainder = identifier[len(prefix):]
            results.append(remainder[0].lower() + remainder[1:])
    for suffix in suffixes:
        if identifier.endswith(suffix) and len(identifier) > len(suffix):
            results.append(identifier[:-len(suffix)])
    return results


def derive_terms(identifier: str, profile: Profile) -> List[Tuple[str, str]]:
    seen: Dict[str, str] = {}
    ordered: List[Tuple[str, str]] = []

    for transform in profile.transforms:
        candidates: List[str] = []
        if transform.id == "split-case":
            candidates = split_tokens(identifier)
        elif transform.id == "token-adjacent-pairs":
            tokens = split_tokens(identifier)
            candidates = [tokens[i] + tokens[i + 1] for i in range(len(tokens) - 1)]
        elif transform.id == "normalize-case":
            candidates = [identifier.lower()]
        elif transform.id == "plural-singular":
            candidates = [_pluralize(identifier)]
        elif transform.id == "strip-affix":
            candidates = _strip_affix(identifier, transform.prefixes, transform.suffixes)

        for candidate in candidates:
            if candidate == identifier or len(candidate) < profile.min_term_length:
                continue
            if candidate in seen:
                continue
            seen[candidate] = transform.id
            ordered.append((candidate, transform.id))
    return ordered


def build_derived_queries(
    clues: Mapping[str, Clue],
    index: OccurrenceIndex,
    profile: Profile,
    existing: Mapping[str, QueryNode],
) -> List[QueryNode]:
    accumulated: Dict[str, Tuple[str, Clue, List[str]]] = {}

    for term in sorted(clues):
        clue = clues[term]
        if "identifier" not in clue.clue_kinds:
            continue
        for derived, rule_id in derive_terms(term, profile):
            if derived in existing:
                current = existing[derived]
                existing[derived] = dataclasses.replace(
                    current,
                    origin_node_ids=sorted(set(current.origin_node_ids) | clue.origin_node_ids),
                    source_terms=sorted(set(current.source_terms) | {term}),
                )
                continue
            if derived not in accumulated:
                accumulated[derived] = (rule_id, Clue(term=derived), [])
            _, merged, source_terms = accumulated[derived]
            merged.origin_node_ids.update(clue.origin_node_ids)
            source_terms.append(term)

    queries: List[QueryNode] = []
    for derived in sorted(accumulated):
        rule_id, merged, source_terms = accumulated[derived]
        occurrences = index.find(derived)
        if not occurrences:
            continue
        queries.append(make_query_node(
            term=derived, kind="derived", clue=merged, occurrences=occurrences,
            profile=profile, rule_id=rule_id, source_terms=set(source_terms),
        ))
    queries.sort(key=lambda item: item.id)
    return queries
