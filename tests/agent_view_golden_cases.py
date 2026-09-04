"""Shared definitions for the agent-view golden fixtures.

Used by tests/test_agent_view_golden.py and scripts/regen_agent_view_golden.py so the
fixture is regenerated through exactly the pipeline the test replays.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_view import build_agent_view, graph_to_json, list_repository_files  # noqa: E402
from agent_view.profile import default_profile_path, load_profile  # noqa: E402
from agent_view.readable import build_readable_nodes  # noqa: E402
from agent_view.scan import read_file, scan_files  # noqa: E402
from framework_analyzers.android.analyzer import AndroidAnalyzer  # noqa: E402
from framework_analyzers.android.graph import AndroidArchitectureGraphBuilder  # noqa: E402
from framework_analyzers.fastapi.analyzer import FastAPIAnalyzer  # noqa: E402
from framework_analyzers.fastapi.graph import ArchitectureGraphBuilder  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "agent_view"


def _fastapi(project_path: Path):
    return ArchitectureGraphBuilder().build_graph(FastAPIAnalyzer(str(project_path)).analyze())


def _android(project_path: Path):
    return AndroidArchitectureGraphBuilder().build_graph(AndroidAnalyzer(str(project_path)).analyze())


@dataclass(frozen=True)
class GoldenCase:
    name: str
    project: str
    architecture: Callable[[Path], object]

    @property
    def project_path(self) -> Path:
        return ROOT / self.project

    @property
    def manifest_path(self) -> Path:
        return FIXTURE_DIR / f"{self.name}.manifest.txt"

    @property
    def golden_path(self) -> Path:
        return FIXTURE_DIR / f"{self.name}.json.gz"


GOLDEN_CASES: Sequence[GoldenCase] = (
    GoldenCase("realworld_app", "examples/realworld_app", _fastapi),
    GoldenCase("nowinandroid_sample", "examples/nowinandroid_sample", _android),
)


def scan_manifest(case: GoldenCase) -> List[str]:
    _source, paths = list_repository_files(case.project_path, tracked_files_only=True)
    return list(paths)


def read_manifest(case: GoldenCase) -> List[str]:
    return case.manifest_path.read_text(encoding="utf-8").splitlines()


def build_json(case: GoldenCase, paths: Sequence[str]) -> str:
    # 파일 목록을 주입해 git 체크아웃 상태와 무관하게 같은 결과가 나오게 한다.
    def lister(_root) -> Tuple[str, List[str]]:
        return "git-tracked", list(paths)

    return graph_to_json(build_agent_view(case.architecture(case.project_path), file_lister=lister))


def index_inputs(case: GoldenCase, paths: Sequence[str]):
    """The contents and node grouping an OccurrenceIndex is built from inside build_agent_view."""
    profile = load_profile(default_profile_path())
    scanned, _excluded, contents = scan_files(
        case.project_path, paths,
        max_file_bytes=profile.max_file_bytes,
        reader=read_file,
        include_agent_docs=profile.include_agent_docs,
    )
    readable_nodes, _ = build_readable_nodes(case.architecture(case.project_path).nodes, scanned, contents)
    nodes_by_file: Dict[str, List] = {}
    for node in readable_nodes:
        nodes_by_file.setdefault(node.file_path, []).append(node)
    return contents, nodes_by_file
