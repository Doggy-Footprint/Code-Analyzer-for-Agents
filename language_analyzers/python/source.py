import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union


@dataclass
class PythonSourceFile:
    file_path: Path
    module_name: str
    source_code: str
    tree: ast.AST


class PythonSourceAnalyzer:
    def __init__(self, project_path: Union[str, Path]):
        self.project_path = Path(project_path).resolve()

    def analyze(self) -> List[PythonSourceFile]:
        files = []
        for root, directories, filenames in os.walk(self.project_path):
            directories[:] = [
                directory for directory in directories
                if not directory.startswith(".")
                and directory not in {"venv", "env", "node_modules", "__pycache__", "build", "dist"}
            ]
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                file_path = Path(root) / filename
                try:
                    source_code = file_path.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source_code, filename=str(file_path))
                except (OSError, SyntaxError, UnicodeError):
                    continue
                files.append(PythonSourceFile(
                    file_path=file_path,
                    module_name=self._module_name(file_path),
                    source_code=source_code,
                    tree=tree,
                ))
        return files

    def _module_name(self, file_path: Path) -> str:
        parts = list(file_path.relative_to(self.project_path).parts)
        if parts[-1] == "__init__.py":
            parts.pop()
        else:
            parts[-1] = parts[-1][:-3]
        return ".".join(parts) if parts else "__init__"
