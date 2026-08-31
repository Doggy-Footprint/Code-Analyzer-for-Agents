"""
Shared building blocks for framework adapters (FastAPI, Android, ...).
Framework adapters may import from here; they must never import each other.
"""

from .git_diff_core import GitDiffCore
from .git_diff_models import (
    GitCommitInfo,
    GitDiffHunk,
    GitDiffInfo,
    GitDiffLine,
    GitFileDiff,
)
from .graph_models import GraphEdge, GraphNode
from .report_schema import ColumnSpec, ReportCollection

__all__ = [
    "GitDiffCore",
    "GitCommitInfo",
    "GitDiffHunk",
    "GitDiffInfo",
    "GitDiffLine",
    "GitFileDiff",
    "GraphEdge",
    "GraphNode",
    "ColumnSpec",
    "ReportCollection",
]
