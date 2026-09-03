"""
Android/Kotlin Architecture & Dependency Visualizer.
"""

from .analyzer import AndroidAnalyzer
from .graph import AndroidArchitectureGraphBuilder
from .models import AndroidProjectArchitecture

__version__ = "0.1.0"
__all__ = [
    "AndroidAnalyzer",
    "AndroidArchitectureGraphBuilder",
    "AndroidProjectArchitecture",
]
