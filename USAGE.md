

# 🚀 Quick Start

## 1. Analyze Any FastAPI Project

```bash
# Analyze a project directory and generate an interactive HTML dashboard
python3 -m code_analyzer /path/to/fastapi/project -o architecture.html

# Automatically open in browser
python3 -m code_analyzer /path/to/fastapi/project -o architecture.html --open

# Also export architecture metadata as JSON
python3 -m code_analyzer /path/to/fastapi/project -o architecture.html --json

# Print Mermaid diagram directly to terminal
python3 -m code_analyzer /path/to/fastapi/project --mermaid
```

HTML reports reference generated CSS and JavaScript in a sibling directory named after the report. For example, `architecture.html` is accompanied by `architecture_assets/`. Keep both when moving or publishing a report.

Graph construction also records agent-exploration metrics in each node's `metadata.analysis` and in `stats.analysis`: PageRank, HITS hub/authority, degree and betweenness centrality, estimated token cost, weighted centrality cost, and cumulative 2-hop/3-hop token cost.

The FastAPI graph is built on top of the Python symbol graph, so it also contains modules, classes, functions, methods, fields and constants along with their `IMPORTS`, `CALLS`, `INSTANTIATES`, `INHERITS`, `TYPE_USES`, `READS` and `WRITES` edges. Each endpoint, dependency and schema is linked to the symbol that implements it with an `IMPLEMENTED_BY` edge. Pass `--no-language-graph` for framework components only.

### What each node and edge carries

Every node reports `span` (file and exact line range), `cost` (estimated tokens, characters, lines), `kind`, `language`, `symbol_path`, `signature`, `docstring`, `exported`, `provenance`, and `flags` — raw friction signals such as `dynamic_import`, `dynamic_attr`, `dynamic_eval`, `reexport`, `ambiguous_name`, `generated`, `vendored` and `test`. Names that could not be resolved are counted in `metadata.unresolved_calls` instead of being dropped.

Every edge reports `confidence` (`static_certain`, `framework_inferred`, `static_inferred`, `dynamic_required`), `resolution` (`exact`, `unique_name`, `ambiguous`, `unresolved`), `evidence` (the file and line where the relation is written), `candidates` (the targets rejected for an ambiguous name) and `weight` (how many times the relation occurs). The dashboard draws each confidence level with its own line style and offers a filter per level.

## 2. Analyze Any Python Project Without Framework Semantics

```bash
python3 -m code_analyzer --language python /path/to/python/project -o architecture.html --json
```

Produces the symbol graph described above with no FastAPI interpretation. Uses the standard library `ast`; no dependencies.

## 3. Analyze Any TypeScript/JavaScript Project

Requires `tree-sitter` and `tree-sitter-language-pack` (see [Setup](#setup) below).

```bash
python3 -m code_analyzer --language typescript /path/to/javascript-or-typescript/project -o architecture.html --json
```

Parses `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs` and `.cjs` with tree-sitter and extracts files, classes, interfaces, type aliases, enums, functions, methods, fields and constants, plus `IMPORTS`, `IMPORTS_SYMBOL`, `RE_EXPORTS`, `EXPORTS`/`DECLARES`, `CONTAINS`, `CALLS`, `INSTANTIATES`, `INHERITS`, `IMPLEMENTS` and `TYPE_USES` relationships. Barrel files (`export * from`) are flagged `reexport`; `import()` and `require()` produce `dynamic_required` edges. It does not apply framework semantics.

## 4. Analyze Any Android/Kotlin Project

Requires `tree-sitter` and `tree-sitter-language-pack` (see [Setup](#setup) below).

```bash
# Analyze an Android project directory and generate an interactive HTML dashboard
python3 -m code_analyzer --framework android /path/to/android/project -o architecture.html

# Exclude Room entity nodes / Hilt-Dagger DI nodes from the graph
python3 -m code_analyzer --framework android /path/to/android/project --no-models --no-deps
```

The Android track extracts Jetpack Compose functions and their call graph, Hilt/Dagger DI (`@Module`/`@Provides`/`@Binds`/`@HiltViewModel`/`@Inject`), ViewModel↔UI binding, Room (`@Entity`/`@Dao`/`@Database`), and Retrofit API interfaces from `.kt` sources — the same agent-exploration metrics above apply. `-e/--entrypoint` and `--app` are FastAPI-only and are rejected together with `--framework android`.

## Setup

The FastAPI and Python tracks have no dependencies beyond the Python standard library. The TypeScript and Android tracks need:

```bash
pip install -r requirements.txt
```

## 5. Command-Line Options

| Option | Flag | Default | Description |
| :--- | :--- | :--- | :--- |
| `project_path` | Positional | `.` | Target project directory |
| `-f, --framework` | `fastapi` \| `android` | `fastapi` | Which framework adapter to analyze the project with |
| `-l, --language` | `python` \| `typescript` | `None` | Analyze a language directly without framework semantics |
| `-o, --output` | String | `architecture.html` | Path for generated interactive HTML report |
| `-e, --entrypoint` | String | `None` | [fastapi only] Optional entrypoint file (e.g. `main.py`) |
| `--app` | String | `None` | [fastapi only] Optional dynamic app import string (e.g. `app.main:app`) |
| `--title` | String | `None` | Custom dashboard title |
| `--no-models` | Flag | `False` | Exclude schema-shaped nodes from graph (Pydantic/SQLModel for fastapi, Room entities for android) |
| `--no-deps` | Flag | `False` | Exclude dependency-injection-shaped nodes from graph (FastAPI dependencies for fastapi, Hilt/Dagger modules & bindings for android) |
| `--no-language-graph` | Flag | `False` | [fastapi only] Exclude the underlying Python symbol graph and show framework components only |
| `--open` | Flag | `False` | Automatically open generated report in browser |
| `--json` | Flag | `False` | Also export architecture data JSON file |
| `--mermaid` | Flag | `False` | Print Mermaid markdown diagram |

---

# 🧪 Testing with Open-Source Sample Projects

Download open-source moderate-sized FastAPI sample repositories:

```bash
python3 examples/download_samples.py
```

Run visualizer on real-world sample projects:

```bash
# 1. RealWorld Conduit API (nested routers, auth dependencies, database repository pattern)
python3 -m code_analyzer examples/realworld_app -o realworld_architecture.html --json

# 2. Official Full-Stack FastAPI Template backend (Annotated dependencies, SQLModel)
python3 -m code_analyzer examples/official_template -o template_architecture.html --json
```

Download a subset of Google's official `android/nowinandroid` sample (Compose, Hilt, Room; the pulled subset does not include the Retrofit-based network module):

```bash
python3 examples/download_android_samples.py

python3 -m code_analyzer --framework android examples/nowinandroid_sample -o nia_architecture.html --json
```

---

# 🔬 Run Unit Tests

```bash
python3 -m unittest discover -s tests -v
```

---

# 📦 Python API

You can also use the visualizer programmatically inside Python scripts:

```python
from framework_analyzers.fastapi import FastAPIAnalyzer, ArchitectureGraphBuilder
from renderers.html import HTMLRenderer

# 1. Statically analyze project
analyzer = FastAPIAnalyzer(project_path="./my_fastapi_app")
arch = analyzer.analyze()

# 2. Build graph & compute metrics
builder = ArchitectureGraphBuilder(include_models=True, include_dependencies=True)
arch = builder.build_graph(arch)

# 3. Render HTML dashboard
renderer = HTMLRenderer(title="My API Architecture")
renderer.render(arch, output_path="docs/architecture.html")
```
