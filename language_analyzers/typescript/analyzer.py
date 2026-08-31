import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from language_analyzers.core.git_diff_core import GitDiffCore
from language_analyzers.core.graph_models import GraphEdge, GraphNode
from language_analyzers.core.report_schema import ColumnSpec, ReportCollection


SOURCE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
IGNORED_DIRECTORIES = {".git", "node_modules", "dist", "build", "coverage", ".next"}
CALL_EXCLUSIONS = {"if", "for", "while", "switch", "catch", "function", "return", "new"}


@dataclass
class TypeScriptProjectArchitecture:
    project_name: str
    project_path: str
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    stats: Dict[str, object] = field(default_factory=dict)
    report_collections: List[ReportCollection] = field(default_factory=list)
    git_diff: object = None


@dataclass
class _Symbol:
    id: str
    name: str
    kind: str
    file_path: Path
    line_number: int
    source: str
    exported: bool = False
    parent: Optional[str] = None
    extends: Optional[str] = None


class TypeScriptAnalyzer:
    def __init__(self, project_path: Union[str, Path]):
        self.project_path = Path(project_path).resolve()

    def analyze(self) -> TypeScriptProjectArchitecture:
        files = self._discover_files()
        symbols: List[_Symbol] = []
        imports: Dict[Path, List[Tuple[str, str]]] = {}
        for file_path in files:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            symbols.extend(self._symbols_for(file_path, source))
            imports[file_path] = self._imports_for(source)

        nodes = self._nodes_for(files, symbols)
        edges = self._edges_for(files, symbols, imports)
        architecture = TypeScriptProjectArchitecture(
            project_name=self.project_path.name,
            project_path=str(self.project_path),
            nodes=nodes,
            edges=edges,
            stats={
                "total_files": len(files),
                "total_symbols": len(symbols),
                "symbols_by_kind": {
                    kind: sum(symbol.kind == kind for symbol in symbols)
                    for kind in sorted({symbol.kind for symbol in symbols})
                },
            },
            report_collections=[ReportCollection(
                key="symbols",
                label="Symbols",
                node_category="symbol",
                columns=[
                    ColumnSpec("name", "Name", "mono"),
                    ColumnSpec("kind", "Kind"),
                    ColumnSpec("file_path", "File", "mono"),
                    ColumnSpec("line_number", "Line"),
                ],
                rows=[{
                    "id": symbol.id,
                    "name": symbol.name,
                    "kind": symbol.kind,
                    "file_path": str(symbol.file_path.relative_to(self.project_path)),
                    "line_number": symbol.line_number,
                } for symbol in symbols],
            )],
            git_diff=GitDiffCore(self.project_path).get_diff_info(),
        )
        return architecture

    def _discover_files(self) -> List[Path]:
        result = []
        for path in self.project_path.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_EXTENSIONS:
                continue
            if any(part in IGNORED_DIRECTORIES or part.startswith(".") for part in path.relative_to(self.project_path).parts):
                continue
            result.append(path)
        return sorted(result)

    def _symbols_for(self, file_path: Path, source: str) -> List[_Symbol]:
        symbols: List[_Symbol] = []
        class_ranges = []
        for match in re.finditer(r"(?m)^\s*(?P<export>export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)(?:\s+extends\s+(?P<base>[\w$.]+))?[^\{]*\{", source):
            end = self._matching_brace(source, match.end() - 1)
            symbol = self._symbol(file_path, source, match, "class", match.group("name"), match.group("export") is not None, extends=match.group("base"))
            symbols.append(symbol)
            class_ranges.append((match.start(), end, symbol))
            body = source[match.end():end]
            body_offset = match.end()
            for method in re.finditer(r"(?m)^\s*(?:public|private|protected|static|async|readonly|override|\s)*\s*(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\([^\n)]*\)[^{;]*\{", body):
                name = method.group("name")
                if name in CALL_EXCLUSIONS:
                    continue
                start = body_offset + method.start()
                finish = self._matching_brace(source, body_offset + method.end() - 1)
                symbols.append(_Symbol(
                    id=self._symbol_id(file_path, name, start),
                    name=name,
                    kind="method",
                    file_path=file_path,
                    line_number=source.count("\n", 0, start) + 1,
                    source=source[start:finish + 1],
                    parent=symbol.id,
                ))

        for match in re.finditer(r"(?m)^\s*(?P<export>export\s+(?:default\s+)?)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)[^\{]*\{", source):
            if self._inside_class(match.start(), class_ranges):
                continue
            symbols.append(self._symbol(file_path, source, match, "function", match.group("name"), match.group("export") is not None))

        for match in re.finditer(r"(?m)^\s*(?P<export>export\s+(?:default\s+)?)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)[^=]*=\s*(?:async\s*)?(?:\([^\n]*?\)|[A-Za-z_$][\w$]*)\s*=>", source):
            symbols.append(self._symbol(file_path, source, match, "function", match.group("name"), match.group("export") is not None))
        return symbols

    def _symbol(self, file_path: Path, source: str, match, kind: str, name: str, exported: bool, extends: Optional[str] = None) -> _Symbol:
        start = match.start()
        opening = source.find("{", match.start(), match.end())
        end = self._matching_brace(source, opening) if opening >= 0 else source.find("\n", match.end())
        return _Symbol(
            id=self._symbol_id(file_path, name, start),
            name=name,
            kind=kind,
            file_path=file_path,
            line_number=source.count("\n", 0, start) + 1,
            source=source[start:end + 1],
            exported=exported,
            extends=extends,
        )

    def _nodes_for(self, files: Sequence[Path], symbols: Sequence[_Symbol]) -> List[GraphNode]:
        nodes = [GraphNode(
            id=self._file_id(file_path),
            label=str(file_path.relative_to(self.project_path)),
            group="file",
            category="file",
            metadata={"file_path": str(file_path.relative_to(self.project_path))},
        ) for file_path in files]
        nodes.extend(GraphNode(
            id=symbol.id,
            label=symbol.name,
            group=symbol.kind,
            category="symbol",
            metadata={
                "kind": symbol.kind,
                "file_path": str(symbol.file_path.relative_to(self.project_path)),
                "line_number": symbol.line_number,
                "exported": symbol.exported,
            },
        ) for symbol in symbols)
        return nodes

    def _edges_for(self, files: Sequence[Path], symbols: Sequence[_Symbol], imports: Dict[Path, List[Tuple[str, str]]]) -> List[GraphEdge]:
        edges = []
        symbols_by_name: Dict[str, List[_Symbol]] = {}
        for symbol in symbols:
            symbols_by_name.setdefault(symbol.name, []).append(symbol)
            edges.append(GraphEdge(self._file_id(symbol.file_path), symbol.id, "EXPORTS" if symbol.exported else "DECLARES"))
            if symbol.parent:
                edges.append(GraphEdge(symbol.parent, symbol.id, "CONTAINS"))

        for file_path in files:
            for _, specifier in imports[file_path]:
                target = self._resolve_import(file_path, specifier)
                if target in files:
                    edges.append(GraphEdge(self._file_id(file_path), self._file_id(target), "IMPORTS"))

        for symbol in symbols:
            for call in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*\(", symbol.source):
                name = call.group(1)
                if name in CALL_EXCLUSIONS:
                    continue
                target = self._resolve_symbol(symbol, name, symbols_by_name)
                if target and target.id != symbol.id:
                    edges.append(GraphEdge(symbol.id, target.id, "CALLS"))
            if symbol.extends:
                target = self._resolve_symbol(symbol, symbol.extends.rsplit(".", 1)[-1], symbols_by_name)
                if target:
                    edges.append(GraphEdge(symbol.id, target.id, "EXTENDS"))
        return self._unique_edges(edges)

    def _resolve_symbol(self, source: _Symbol, name: str, symbols_by_name: Dict[str, List[_Symbol]]) -> Optional[_Symbol]:
        candidates = symbols_by_name.get(name, [])
        same_file = [candidate for candidate in candidates if candidate.file_path == source.file_path]
        if len(same_file) == 1:
            return same_file[0]
        return candidates[0] if len(candidates) == 1 else None

    def _imports_for(self, source: str) -> List[Tuple[str, str]]:
        return [
            (match.group("bindings"), match.group("specifier"))
            for match in re.finditer(r"(?m)^\s*import\s+(?P<bindings>.*?)\s+from\s+[\"'](?P<specifier>[^\"']+)[\"']", source)
        ]

    def _resolve_import(self, file_path: Path, specifier: str) -> Optional[Path]:
        if not specifier.startswith("."):
            return None
        base = (file_path.parent / specifier).resolve()
        candidates = [base] if base.suffix in SOURCE_EXTENSIONS else [base.with_suffix(extension) for extension in SOURCE_EXTENSIONS] + [base / f"index{extension}" for extension in SOURCE_EXTENSIONS]
        return next((candidate for candidate in candidates if candidate.is_file()), None)

    @staticmethod
    def _matching_brace(source: str, opening: int) -> int:
        depth = 0
        for index in range(opening, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return index
        return len(source) - 1

    @staticmethod
    def _inside_class(position: int, ranges) -> bool:
        return any(start <= position <= end for start, end, _ in ranges)

    def _symbol_id(self, file_path: Path, name: str, position: int) -> str:
        return f"symbol:{file_path.relative_to(self.project_path)}:{name}:{position}"

    def _file_id(self, file_path: Path) -> str:
        return f"file:{file_path.relative_to(self.project_path)}"

    @staticmethod
    def _unique_edges(edges: Sequence[GraphEdge]) -> List[GraphEdge]:
        seen = set()
        result = []
        for edge in edges:
            key = edge.from_id, edge.to_id, edge.relation
            if key not in seen:
                seen.add(key)
                result.append(edge)
        return result
