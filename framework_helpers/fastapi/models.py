"""
Data models representing the extracted architecture of a FastAPI project.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParameterInfo:
    name: str
    type_annotation: Optional[str] = None
    default_value: Optional[str] = None
    kind: str = "query"  # query, path, body, header, cookie, dependency, security
    dependency_call: Optional[str] = None


@dataclass
class EndpointInfo:
    id: str
    http_method: str  # GET, POST, PUT, DELETE, PATCH, etc.
    path: str  # Path declared on decorator (e.g. "/items/{id}")
    full_path: str = ""  # Full resolved path with router prefixes
    function_name: str = ""
    module: str = ""
    file_path: str = ""
    line_number: int = 0
    docstring: Optional[str] = None
    summary: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    response_model: Optional[str] = None
    status_code: Optional[str] = None
    parameters: List[ParameterInfo] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    request_schemas: List[str] = field(default_factory=list)
    response_schemas: List[str] = field(default_factory=list)
    router_id: Optional[str] = None
    app_id: Optional[str] = None


@dataclass
class RouterInclusion:
    router_var: str
    module_or_source: str
    prefix: str = ""
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    target_router_id: Optional[str] = None


@dataclass
class RouterInfo:
    id: str
    var_name: str
    module: str
    file_path: str
    line_number: int
    prefix: str = ""
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    inclusions: List[RouterInclusion] = field(default_factory=list)
    endpoints: List[str] = field(default_factory=list)


@dataclass
class AppInfo:
    id: str
    var_name: str
    title: str = "FastAPI App"
    version: str = "0.1.0"
    module: str = ""
    file_path: str = ""
    line_number: int = 0
    middlewares: List[Dict[str, Any]] = field(default_factory=list)
    event_handlers: List[Dict[str, Any]] = field(default_factory=list)
    inclusions: List[RouterInclusion] = field(default_factory=list)
    endpoints: List[str] = field(default_factory=list)


@dataclass
class DependencyInfo:
    id: str
    name: str
    kind: str  # function, class, security_scheme, annotated_alias
    module: str
    file_path: str
    line_number: int = 0
    docstring: Optional[str] = None
    sub_dependencies: List[str] = field(default_factory=list)
    parameters: List[ParameterInfo] = field(default_factory=list)
    consumers: List[str] = field(default_factory=list)


@dataclass
class SchemaFieldInfo:
    name: str
    type_annotation: str
    default_value: Optional[str] = None
    description: Optional[str] = None
    is_required: bool = True


@dataclass
class SchemaInfo:
    id: str
    name: str
    module: str
    file_path: str
    line_number: int = 0
    docstring: Optional[str] = None
    base_classes: List[str] = field(default_factory=list)
    fields: List[SchemaFieldInfo] = field(default_factory=list)
    used_by_endpoints: List[str] = field(default_factory=list)


@dataclass
class GraphNode:
    id: str
    label: str
    group: str  # app, router, endpoint_get, endpoint_post, etc., dependency, schema, middleware
    category: str  # app, router, endpoint, dependency, schema, middleware
    title: str = ""
    shape: str = "box"
    size: int = 25
    color: Optional[Dict[str, str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    from_id: str
    to_id: str
    relation: str  # INCLUDES, ROUTES, DEPENDS_ON, REQUEST_BODY, RESPONSE_MODEL, MIDDLEWARE_OF, SUB_DEPENDENCY
    label: str = ""
    dashes: bool = False
    arrows: str = "to"
    color: Optional[str] = None
    title: Optional[str] = None


@dataclass
class GitCommitInfo:
    hash: str
    short_hash: str
    author: str
    email: str
    date: str
    message: str


@dataclass
class GitDiffLine:
    type: str  # 'context', 'add', 'del', 'header'
    old_lineno: Optional[int] = None
    new_lineno: Optional[int] = None
    content: str = ""


@dataclass
class GitDiffHunk:
    header: str
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: List[GitDiffLine] = field(default_factory=list)


@dataclass
class GitFileDiff:
    file_path: str
    status: str  # 'modified', 'added', 'deleted', 'untracked', 'renamed'
    additions: int = 0
    deletions: int = 0
    old_path: Optional[str] = None
    raw_diff: str = ""
    is_binary: bool = False
    hunks: List[GitDiffHunk] = field(default_factory=list)
    impacted_components: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class GitDiffInfo:
    is_git_repo: bool = False
    comparison_mode: str = "none"  # 'working_tree_vs_head', 'last_two_commits', 'single_commit', 'none'
    mode_description: str = ""
    base_commit: Optional[GitCommitInfo] = None
    target_commit: Optional[GitCommitInfo] = None
    target_name: str = ""  # e.g. "Working Tree (Uncommitted Changes)" or "HEAD"
    has_uncommitted_changes: bool = False
    total_files: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    files: List[GitFileDiff] = field(default_factory=list)
    impacted_endpoints: List[Dict[str, Any]] = field(default_factory=list)
    impacted_routers: List[Dict[str, Any]] = field(default_factory=list)
    impacted_dependencies: List[Dict[str, Any]] = field(default_factory=list)
    impacted_schemas: List[Dict[str, Any]] = field(default_factory=list)
    error_message: Optional[str] = None


@dataclass
class ProjectArchitecture:
    project_name: str
    project_path: str
    apps: List[AppInfo] = field(default_factory=list)
    routers: List[RouterInfo] = field(default_factory=list)
    endpoints: List[EndpointInfo] = field(default_factory=list)
    dependencies: List[DependencyInfo] = field(default_factory=list)
    schemas: List[SchemaInfo] = field(default_factory=list)
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    git_diff: Optional[GitDiffInfo] = None
