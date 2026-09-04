import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml

from .models import ProfileRef

ALLOWED_TRANSFORM_IDS = (
    "split-case",
    "token-adjacent-pairs",
    "normalize-case",
    "plural-singular",
    "strip-affix",
)

_LIMIT_KEYS = ("max_arrival_nodes", "min_term_length", "max_file_bytes")


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Transform:
    id: str
    prefixes: List[str] = field(default_factory=list)
    suffixes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Profile:
    ref: ProfileRef
    max_arrival_nodes: int
    min_term_length: int
    max_file_bytes: int
    transforms: List[Transform]
    include_agent_docs: bool
    tracked_files_only: bool

    @property
    def version(self) -> int:
        return self.ref.version


def default_profile_path() -> Path:
    return Path(__file__).resolve().parents[1] / "profiles" / "derived_query_rules.v2.yaml"


def load_profile(path: Union[str, Path]) -> Profile:
    raw_bytes = Path(path).read_bytes()
    try:
        document = yaml.safe_load(raw_bytes.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as error:
        raise ProfileError(f"profile is not valid YAML: {error}") from error
    if not isinstance(document, dict):
        raise ProfileError("profile root must be a mapping")

    for key in ("id", "version", "limits", "transforms"):
        if key not in document:
            raise ProfileError(f"profile is missing required key: {key}")

    version = document["version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise ProfileError("profile version must be an int")

    limits = document["limits"]
    if not isinstance(limits, dict):
        raise ProfileError("profile limits must be a mapping")
    values: Dict[str, int] = {}
    for key in _LIMIT_KEYS:
        if key not in limits:
            raise ProfileError(f"profile limits is missing required key: {key}")
        value = limits[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ProfileError(f"profile limit {key} must be an int >= 1")
        values[key] = value

    transforms = _load_transforms(document["transforms"])

    return Profile(
        ref=ProfileRef(
            id=str(document["id"]),
            version=version,
            content_hash=hashlib.sha256(raw_bytes).hexdigest(),
        ),
        max_arrival_nodes=values["max_arrival_nodes"],
        min_term_length=values["min_term_length"],
        max_file_bytes=values["max_file_bytes"],
        transforms=transforms,
        include_agent_docs=bool(document.get("include_agent_docs", True)),
        tracked_files_only=bool(document.get("tracked_files_only", True)),
    )


def _load_transforms(raw: Any) -> List[Transform]:
    if not isinstance(raw, list) or not raw:
        raise ProfileError("profile transforms must be a non-empty list")
    seen = set()
    transforms: List[Transform] = []
    for entry in raw:
        if not isinstance(entry, dict) or "id" not in entry:
            raise ProfileError("each transform must be a mapping with an id")
        transform_id = entry["id"]
        if transform_id not in ALLOWED_TRANSFORM_IDS:
            raise ProfileError(f"unknown transform id: {transform_id}")
        if transform_id in seen:
            raise ProfileError(f"duplicate transform id: {transform_id}")
        seen.add(transform_id)
        prefixes = [str(item) for item in (entry.get("prefixes") or [])]
        suffixes = [str(item) for item in (entry.get("suffixes") or [])]
        if transform_id == "strip-affix":
            if not prefixes and not suffixes:
                raise ProfileError("strip-affix requires prefixes or suffixes")
        elif "prefixes" in entry or "suffixes" in entry:
            raise ProfileError(f"prefixes/suffixes are only allowed on strip-affix, not {transform_id}")
        transforms.append(Transform(id=transform_id, prefixes=prefixes, suffixes=suffixes))
    return transforms
