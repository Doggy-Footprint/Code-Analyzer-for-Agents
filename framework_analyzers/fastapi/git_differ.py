"""
Correlates framework-neutral git diffs with FastAPI architecture components.
"""

from pathlib import Path
from typing import Optional, Union

from language_analyzers.core.git_diff_core import GitDiffCore
from language_analyzers.core.git_diff_models import GitDiffInfo

from .models import ProjectArchitecture


class GitDiffer:
    def __init__(self, project_path: Union[str, Path]):
        self._core = GitDiffCore(project_path)

    def get_diff_info(self, arch: Optional[ProjectArchitecture] = None) -> GitDiffInfo:
        diff_info = self._core.get_diff_info()
        if arch:
            self._correlate_with_architecture(diff_info, arch)
        return diff_info

    @staticmethod
    def _correlate_with_architecture(diff_info: GitDiffInfo, arch: ProjectArchitecture):
        def matches_file(element_file_path: str, diff_file_path: str) -> bool:
            if not element_file_path or not diff_file_path:
                return False
            norm_elem = element_file_path.replace("\\", "/").lstrip("./")
            norm_diff = diff_file_path.replace("\\", "/").lstrip("./")
            return norm_elem == norm_diff or norm_elem.endswith("/" + norm_diff) or norm_diff.endswith("/" + norm_elem)

        impacted_endpoints = []
        for ep in arch.endpoints:
            for f in diff_info.files:
                if matches_file(ep.file_path, f.file_path):
                    impacted_endpoints.append({
                        "id": ep.id,
                        "method": ep.http_method,
                        "path": ep.full_path or ep.path,
                        "func": ep.function_name,
                        "file": ep.file_path,
                        "line": ep.line_number,
                    })
                    f.impacted_components.append({
                        "type": "endpoint",
                        "label": f"{ep.http_method} {ep.full_path or ep.path}",
                        "id": ep.id,
                    })

        impacted_routers = []
        for r in arch.routers:
            for f in diff_info.files:
                if matches_file(r.file_path, f.file_path):
                    impacted_routers.append({
                        "id": r.id,
                        "var_name": r.var_name,
                        "prefix": r.prefix,
                        "file": r.file_path,
                        "line": r.line_number,
                    })
                    f.impacted_components.append({
                        "type": "router",
                        "label": f"Router: {r.var_name}",
                        "id": r.id,
                    })

        impacted_dependencies = []
        for d in arch.dependencies:
            for f in diff_info.files:
                if matches_file(d.file_path, f.file_path):
                    impacted_dependencies.append({
                        "id": d.id,
                        "name": d.name,
                        "kind": d.kind,
                        "file": d.file_path,
                        "line": d.line_number,
                    })
                    f.impacted_components.append({
                        "type": "dependency",
                        "label": f"Dep: {d.name}",
                        "id": d.id,
                    })

        impacted_schemas = []
        for s in arch.schemas:
            for f in diff_info.files:
                if matches_file(s.file_path, f.file_path):
                    impacted_schemas.append({
                        "id": s.id,
                        "name": s.name,
                        "file": s.file_path,
                        "line": s.line_number,
                    })
                    f.impacted_components.append({
                        "type": "schema",
                        "label": f"Model: {s.name}",
                        "id": s.id,
                    })

        diff_info.impacted_by_collection = {
            "endpoints": list({e["id"]: e for e in impacted_endpoints}.values()),
            "routers": list({r["id"]: r for r in impacted_routers}.values()),
            "dependencies": list({d["id"]: d for d in impacted_dependencies}.values()),
            "schemas": list({s["id"]: s for s in impacted_schemas}.values()),
        }
