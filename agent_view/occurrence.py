import bisect
import re
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

from .models import Occurrence, ReadableNode

DOC_SUFFIXES = {".md", ".rst", ".txt"}
CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".properties", ".env", ".gradle"}
_TRIPLE_QUOTE_SUFFIXES = {".py", ".pyi"}


def file_context_kind(path: str) -> str:
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    if suffix in DOC_SUFFIXES:
        return "doc"
    if name.endswith(".gradle.kts") or suffix in CONFIG_SUFFIXES or name == ".env":
        return "config"
    return "code"


def _line_starts(text: str) -> List[int]:
    starts = [0]
    for index, character in enumerate(text):
        if character == "\n":
            starts.append(index + 1)
    return starts


def _classify_regions(text: str, path: str) -> List[Tuple[int, int, str]]:
    triple = Path(path).suffix.lower() in _TRIPLE_QUOTE_SUFFIXES
    regions: List[Tuple[int, int, str]] = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if triple and text.startswith(('"""', "'''"), index):
            delimiter = text[index:index + 3]
            end = text.find(delimiter, index + 3)
            end = length if end == -1 else end + 3
            regions.append((index, end, "docstring"))
            index = end
            continue
        if character == "#" or text.startswith("//", index):
            end = text.find("\n", index)
            end = length if end == -1 else end
            regions.append((index, end, "comment"))
            index = end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = length if end == -1 else end + 2
            regions.append((index, end, "comment"))
            index = end
            continue
        if character in ("'", '"'):
            index += 1
            while index < length and text[index] != character and text[index] != "\n":
                index += 2 if text[index] == "\\" else 1
            index += 1
            continue
        index += 1
    return regions


class OccurrenceIndex:
    def __init__(self, contents: Mapping[str, str], nodes_by_file: Mapping[str, List[ReadableNode]]):
        self._contents = dict(contents)
        self._nodes_by_file = {path: list(nodes) for path, nodes in nodes_by_file.items()}
        self._line_starts = {path: _line_starts(text) for path, text in self._contents.items()}
        self._regions: Dict[str, List[Tuple[int, int, str]]] = {}
        self._region_starts: Dict[str, List[int]] = {}
        self._base_context = {path: file_context_kind(path) for path in self._contents}

    def _context(self, path: str, offset: int) -> str:
        base = self._base_context[path]
        if base != "code":
            return base
        if path not in self._regions:
            regions = _classify_regions(self._contents[path], path)
            self._regions[path] = regions
            self._region_starts[path] = [region[0] for region in regions]
        regions = self._regions[path]
        starts = self._region_starts[path]
        position = bisect.bisect_right(starts, offset) - 1
        if position >= 0 and regions[position][0] <= offset < regions[position][1]:
            return regions[position][2]
        return "code"

    def _enclosing(self, path: str, line: int) -> str:
        return enclosing_node_id(self._nodes_by_file.get(path, []), path, line)

    def find(self, term: str) -> List[Occurrence]:
        if not term:
            return []
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])")
        results: List[Occurrence] = []
        for path in sorted(self._contents):
            text = self._contents[path]
            starts = self._line_starts[path]
            for match in pattern.finditer(text):
                offset = match.start()
                line_index = bisect.bisect_right(starts, offset) - 1
                results.append(Occurrence(
                    file_path=path,
                    line=line_index + 1,
                    col=offset - starts[line_index],
                    matched_text=match.group(0),
                    context=self._context(path, offset),
                    enclosing_node_id=self._enclosing(path, line_index + 1),
                ))
        results.sort(key=lambda item: (item.file_path, item.line, item.col))
        return results


def enclosing_node_id(nodes: Sequence[ReadableNode], path: str, line: int) -> str:
    containing = [
        node for node in nodes
        if node.start_line is not None and node.end_line is not None
        and node.start_line <= line <= node.end_line
    ]
    if containing:
        return min(containing, key=lambda node: (node.end_line - node.start_line, node.id)).id
    file_id = f"file:{path}"
    if any(node.id == file_id for node in nodes):
        return file_id
    return min((node.id for node in nodes), default=file_id)
