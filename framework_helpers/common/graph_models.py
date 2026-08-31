from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class GraphNode:
    id: str
    label: str
    group: str
    category: str
    title: str = ""
    shape: str = "box"
    size: int = 25
    color: Optional[Dict[str, str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    from_id: str
    to_id: str
    relation: str
    label: str = ""
    dashes: bool = False
    arrows: str = "to"
    color: Optional[str] = None
    title: Optional[str] = None
