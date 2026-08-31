from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ColumnSpec:
    key: str
    label: str
    kind: str = "text"  # text | mono | list


@dataclass
class ReportCollection:
    """A named group of extracted components a framework adapter wants shown as its own
    dashboard tab, e.g. FastAPI's "endpoints" or Android's "composables"."""

    key: str
    label: str
    view: str = "grid"  # grid | table
    node_category: Optional[str] = None
    columns: List[ColumnSpec] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
