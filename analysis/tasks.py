import json
import posixpath
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

__all__ = [
    "SeedKind",
    "SeedQuery",
    "TaskDefinition",
    "TaskSeedResolver",
    "TaskType",
    "load_task_definitions",
]


class TaskType(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE_ADD = "feature_add"
    API_CHANGE = "api_change"
    CONFIG_CHANGE = "config_change"


class SeedKind(str, Enum):
    URL = "url"
    SYMBOL = "symbol"
    ERROR = "error"
    CONFIG = "config"
    CHANGED_FILE = "changed_file"


@dataclass(frozen=True)
class SeedQuery:
    kind: SeedKind
    value: str

    def __post_init__(self):
        try:
            kind = SeedKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid seed kind: {exc}") from exc
        object.__setattr__(self, "kind", kind)
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("seed value must be a non-empty string")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SeedQuery":
        if not isinstance(value, Mapping):
            raise ValueError("each seed must be an object")
        try:
            return cls(SeedKind(value["kind"]), value["value"])
        except KeyError as exc:
            raise ValueError(f"seed is missing {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid seed: {exc}") from exc


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    type: TaskType
    seeds: tuple[SeedQuery, ...]
    target_node_ids: frozenset[str] = frozenset()
    impact_node_ids: frozenset[str] = frozenset()
    test_node_ids: frozenset[str] = frozenset()

    def __post_init__(self):
        try:
            task_type = TaskType(self.type)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid task type: {exc}") from exc
        if not isinstance(self.seeds, (list, tuple)):
            raise ValueError("task seeds must be a list or tuple")
        try:
            seeds = tuple(
                seed if isinstance(seed, SeedQuery) else SeedQuery.from_dict(seed)
                for seed in self.seeds
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        object.__setattr__(self, "type", task_type)
        object.__setattr__(self, "seeds", seeds)
        object.__setattr__(self, "target_node_ids", self._node_ids(self.target_node_ids, "target_node_ids"))
        object.__setattr__(self, "impact_node_ids", self._node_ids(self.impact_node_ids, "impact_node_ids"))
        object.__setattr__(self, "test_node_ids", self._node_ids(self.test_node_ids, "test_node_ids"))
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("task id must be a non-empty string")

    @staticmethod
    def _node_ids(values: Any, name: str) -> frozenset[str]:
        if isinstance(values, str) or not isinstance(values, (list, tuple, set, frozenset)):
            raise ValueError(f"{name} must be a collection of node ids")
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError(f"{name} must contain non-empty strings")
        return frozenset(values)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskDefinition":
        if not isinstance(value, Mapping):
            raise ValueError("each task must be an object")
        if "budget" in value:
            raise ValueError("task budget is no longer supported")
        goals = value.get("goals", {})
        if goals is None:
            goals = {}
        if not isinstance(goals, Mapping):
            raise ValueError("task goals must be an object")

        def goal(name: str, *aliases: str) -> Any:
            for key in (name, *aliases):
                if key in value:
                    return value[key]
                if key in goals:
                    return goals[key]
            return []

        try:
            if not any(key in value for key in ("seeds", "seed", "seed_clues")):
                raise ValueError("task is missing seeds")
            seeds = value.get("seeds", value.get("seed", value.get("seed_clues", [])))
            if isinstance(seeds, Mapping):
                seeds = [seeds]
            if not isinstance(seeds, list):
                raise ValueError("task seeds must be a list")
            return cls(
                id=value["id"],
                type=TaskType(value["type"]),
                seeds=tuple(SeedQuery.from_dict(item) for item in seeds),
                target_node_ids=goal("target_node_ids", "target_nodes", "targets", "target"),
                impact_node_ids=goal("impact_node_ids", "impact_nodes", "impacts", "impact"),
                test_node_ids=goal("test_node_ids", "test_nodes", "tests", "test"),
            )
        except KeyError as exc:
            raise ValueError(f"task is missing {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith(("task ", "seed ", "target_", "impact_", "test_", "invalid seed")):
                raise
            raise ValueError(f"invalid task: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "seeds": [{"kind": seed.kind.value, "value": seed.value} for seed in self.seeds],
            "target_node_ids": sorted(self.target_node_ids),
            "impact_node_ids": sorted(self.impact_node_ids),
            "test_node_ids": sorted(self.test_node_ids),
        }


class TaskSeedResolver:
    def __init__(
        self,
        nodes: Sequence[Any],
        project_path: Optional[str | Path] = None,
        source_reader: Optional[Callable[[Path], str]] = None,
    ):
        self.nodes = {str(self._value(node, "id")): node for node in nodes}
        root = Path(project_path) if project_path is not None else None
        self.project_path = root if root is None or root.is_absolute() else Path.cwd() / root
        if source_reader is not None and not callable(source_reader):
            raise ValueError("source_reader must be callable")
        self.source_reader = source_reader
        self._source_cache: Dict[Path, str] = {}

    def retrieve(self, seed: SeedQuery) -> list[str]:
        if not isinstance(seed, SeedQuery):
            seed = SeedQuery.from_dict(seed)
        query = seed.value.strip()
        query_lower = query.casefold()
        matches = []
        for node_id, node in self.nodes.items():
            score: Optional[int] = None
            if seed.kind == SeedKind.CHANGED_FILE:
                wanted = self._normalize_path(query)
                paths = {self._normalize_path(path) for path in self._file_values(node)}
                if wanted in paths:
                    score = 0
            elif seed.kind == SeedKind.ERROR:
                lowered = [value.casefold() for value in self._search_values(node, include_source=True) if value]
                if any(query_lower in value for value in lowered):
                    score = 0
            elif seed.kind == SeedKind.URL:
                url_values = [str(value) for value in self._url_values(node)]
                textual = [value.casefold() for value in self._symbol_values(node)]
                textual.extend(value.casefold() for value in url_values)
                if any(query == value for value in url_values):
                    score = 0
                elif any(query_lower == value.casefold() for value in url_values):
                    score = 1
                elif any(query == value for value in self._symbol_values(node)):
                    score = 1
                elif any(query_lower in value for value in textual):
                    score = 2
            elif seed.kind == SeedKind.CONFIG:
                config_values = self._config_values(node)
                if any(query == value for value in config_values):
                    score = 0
                elif any(query_lower == value.casefold() for value in config_values):
                    score = 1
            else:
                symbol_values = self._symbol_values(node)
                if any(query == value for value in symbol_values):
                    score = 0
                elif any(query_lower == value.casefold() for value in symbol_values):
                    score = 1
                elif any(
                    value.endswith("." + query_lower) or value.endswith("#" + query_lower)
                    for value in map(str.casefold, symbol_values)
                ):
                    score = 2
            if score is not None:
                matches.append((score, node_id))
        return [node_id for _, node_id in sorted(matches)]

    def _search_values(self, node: Any, include_source: bool = False) -> list[str]:
        metadata = self._value(node, "metadata", {}) or {}
        values = list(self._symbol_values(node))
        values.extend(str(value) for value in self._flatten(metadata))
        values.extend(self._file_values(node))
        if include_source:
            source = self._source_text(node)
            if source:
                values.append(source)
        return values

    def _source_text(self, node: Any) -> str:
        if self.source_reader is None:
            return ""
        file_values = self._file_values(node)
        if not file_values:
            return ""
        path = Path(file_values[0])
        if not path.is_absolute() and self.project_path is not None:
            path = self.project_path / path
        if path not in self._source_cache:
            try:
                source = self.source_reader(path)
            except (OSError, UnicodeError):
                source = ""
            self._source_cache[path] = source if isinstance(source, str) else ""
        source = self._source_cache[path]
        span = self._value(node, "span")
        if not source or span is None:
            return source
        start = self._value(span, "start_line")
        end = self._value(span, "end_line")
        if isinstance(start, int) and isinstance(end, int):
            return "\n".join(source.splitlines()[max(0, start - 1):end])
        return source

    def _symbol_values(self, node: Any) -> list[str]:
        return [str(self._value(node, name, "") or "") for name in ("label", "title", "symbol_path", "signature", "docstring")]

    def _url_values(self, node: Any) -> list[str]:
        metadata = self._value(node, "metadata", {}) or {}
        keys = ("url", "path", "route", "full_path", "endpoint")
        return [str(metadata[key]) for key in keys if key in metadata and isinstance(metadata[key], (str, int, float))]

    def _config_values(self, node: Any) -> list[str]:
        metadata = self._value(node, "metadata", {}) or {}
        values = self._symbol_values(node)
        for key, value in metadata.items():
            if key in {"key", "config_key", "environment_variable", "env", "name"}:
                values.extend((str(key), str(value)))
        return values

    def _file_values(self, node: Any) -> list[str]:
        values = []
        span = self._value(node, "span")
        if span is not None:
            file_path = self._value(span, "file_path")
            if file_path:
                values.append(str(file_path))
        metadata = self._value(node, "metadata", {}) or {}
        for key in ("file_path", "path", "source_file", "filename"):
            if metadata.get(key):
                values.append(str(metadata[key]))
        return list(dict.fromkeys(values))

    def _normalize_path(self, value: Any) -> str:
        path = str(value).replace("\\", "/")
        if self.project_path is not None:
            candidate = Path(path)
            if candidate.is_absolute():
                try:
                    path = candidate.relative_to(self.project_path).as_posix()
                except ValueError:
                    path = candidate.as_posix()
        return posixpath.normpath(path).removeprefix("./")

    @staticmethod
    def _value(value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _flatten(cls, value: Any):
        if isinstance(value, Mapping):
            for key, item in value.items():
                yield key
                yield from cls._flatten(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                yield from cls._flatten(item)
        elif value is not None:
            yield value


def load_task_definitions(path: str | Path) -> list[TaskDefinition]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load task set: {exc}") from exc
    if isinstance(payload, Mapping):
        payload = payload.get("tasks")
    if not isinstance(payload, list):
        raise ValueError("task set must be a list or an object containing a tasks list")
    return [TaskDefinition.from_dict(item) for item in payload]
