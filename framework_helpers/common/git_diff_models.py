from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    impacted_by_collection: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    error_message: Optional[str] = None
