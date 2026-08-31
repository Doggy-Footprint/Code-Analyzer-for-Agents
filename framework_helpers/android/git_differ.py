"""
Correlates framework-neutral git diffs with Android architecture components.
"""

from pathlib import Path
from typing import Optional, Union

from framework_helpers.common.git_diff_core import GitDiffCore
from framework_helpers.common.git_diff_models import GitDiffInfo

from .models import AndroidProjectArchitecture


class GitDiffer:
    def __init__(self, project_path: Union[str, Path]):
        self._core = GitDiffCore(project_path)

    def get_diff_info(self, arch: Optional[AndroidProjectArchitecture] = None) -> GitDiffInfo:
        diff_info = self._core.get_diff_info()
        if arch:
            self._correlate_with_architecture(diff_info, arch)
        return diff_info

    @staticmethod
    def _correlate_with_architecture(diff_info: GitDiffInfo, arch: AndroidProjectArchitecture):
        def matches_file(element_file_path: str, diff_file_path: str) -> bool:
            if not element_file_path or not diff_file_path:
                return False
            norm_elem = element_file_path.replace("\\", "/").lstrip("./")
            norm_diff = diff_file_path.replace("\\", "/").lstrip("./")
            return norm_elem == norm_diff or norm_elem.endswith("/" + norm_diff) or norm_diff.endswith("/" + norm_elem)

        def impacted(elements, kind, label_prefix):
            found = []
            for el in elements:
                for f in diff_info.files:
                    if matches_file(el.file_path, f.file_path):
                        entry = {"id": el.id, "name": el.name, "file": el.file_path, "line": el.line_number}
                        found.append(entry)
                        f.impacted_components.append({"type": kind, "label": f"{label_prefix}: {el.name}", "id": el.id})
            return list({e["id"]: e for e in found}.values())

        diff_info.impacted_by_collection = {
            "composables": impacted(arch.composables, "composable", "Composable"),
            "viewmodels": impacted(arch.viewmodels, "viewmodel", "ViewModel"),
            "di_bindings": impacted(arch.di_bindings, "di_binding", "DI"),
            "room_entities": impacted(arch.room_entities, "room_entity", "Entity"),
            "retrofit_apis": impacted(arch.retrofit_apis, "retrofit_api", "API"),
        }
