import os
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .models import ExcludedFile

STATIC_EXCLUDED_DIRECTORIES = {"venv", "env", "node_modules", "__pycache__", "build", "dist"}
AGENT_DOC_NAMES = {"AGENTS.md", "CLAUDE.md", "README.md"}

_BINARY_SNIFF_CHARS = 8192


def read_file(path: Path) -> Optional[str]:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except (OSError, UnicodeError):
        return None


def list_repository_files(root: Path, *, respect_gitignore: bool = True) -> Tuple[str, List[str]]:
    if respect_gitignore:
        tracked = _git_tracked_files(root)
        if tracked is not None:
            return "git", sorted(tracked)
    return "static_fallback", sorted(_walk_files(root))


def _git_tracked_files(root: Path) -> Optional[List[str]]:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if completed.returncode != 0:
        return None
    entries = [entry for entry in completed.stdout.decode("utf-8", errors="replace").split("\0") if entry]
    if not entries:
        return None
    return [Path(entry).as_posix() for entry in entries]


def _walk_files(root: Path) -> List[str]:
    results: List[str] = []
    for current, directories, filenames in os.walk(root):
        directories[:] = [
            directory for directory in directories
            if not directory.startswith(".") and directory not in STATIC_EXCLUDED_DIRECTORIES
        ]
        for filename in filenames:
            relative = Path(current, filename).relative_to(root).as_posix()
            results.append(relative)
    return results


def scan_files(
    root: Path,
    relative_paths: Sequence[str],
    *,
    max_file_bytes: int,
    reader: Callable[[Path], Optional[str]],
    include_agent_docs: bool = True,
) -> Tuple[List[str], List[ExcludedFile], Dict[str, str]]:
    included: List[str] = []
    excluded: List[ExcludedFile] = []
    contents: Dict[str, str] = {}

    for relative in sorted(set(relative_paths)):
        if not include_agent_docs and Path(relative).name in AGENT_DOC_NAMES:
            continue
        try:
            text = reader(Path(root) / relative)
        except (OSError, UnicodeError):
            text = None
        if text is None:
            excluded.append(ExcludedFile(relative, "unreadable"))
            continue
        if len(text.encode("utf-8", errors="replace")) > max_file_bytes:
            excluded.append(ExcludedFile(relative, "too_large"))
            continue
        if "\x00" in text[:_BINARY_SNIFF_CHARS]:
            excluded.append(ExcludedFile(relative, "binary"))
            continue
        included.append(relative)
        contents[relative] = text

    excluded.sort(key=lambda item: item.file_path)
    return included, excluded, contents
