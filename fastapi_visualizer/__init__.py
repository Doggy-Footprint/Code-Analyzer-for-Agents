"""
FastAPI Architecture & Dependency Visualizer.
"""

from .analyzer import FastAPIAnalyzer
from .dynamic_analyzer import DynamicFastAPIAnalyzer
from .graph import ArchitectureGraphBuilder
from .models import (
    AppInfo,
    DependencyInfo,
    EndpointInfo,
    GraphEdge,
    GraphNode,
    ProjectArchitecture,
    RouterInfo,
    SchemaInfo,
)
from .renderer import HTMLRenderer

__version__ = "0.1.0"
__all__ = [
    "FastAPIAnalyzer",
    "DynamicFastAPIAnalyzer",
    "ArchitectureGraphBuilder",
    "HTMLRenderer",
    "ProjectArchitecture",
    "AppInfo",
    "RouterInfo",
    "EndpointInfo",
    "DependencyInfo",
    "SchemaInfo",
    "GraphNode",
    "GraphEdge",
]
