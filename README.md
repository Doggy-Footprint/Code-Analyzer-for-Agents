# FastAPI Architecture & Dependency Visualizer

A static analysis and interactive visualization dashboard generator for **FastAPI** codebases.

![FastAPI Visualizer](https://img.shields.io/badge/FastAPI-Visualizer-indigo)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Zero Dependency](https://img.shields.io/badge/Dependencies-Standard%20Library-green)

---

## ✨ Features

- **Zero-Dependency Python Static Analysis**: Uses Python's built-in `ast` module to statically inspect any FastAPI codebase safely without requiring active database connections, external services, or project package installations.
- **Full Architecture Coverage**:
  - **FastAPI Applications & Sub-apps**: App initializations, middlewares, lifespan handlers.
  - **APIRouter Inclusions & Prefix Chains**: Resolves nested routers and full URL endpoint paths (e.g. `/api/v1/articles/{slug}/comments`).
  - **Dependency Injection Graphs**: Detects parameter-level (`Depends`, `Security`), `Annotated[..., Depends(...)]` type aliases, route/router-level dependencies, and nested multi-tier dependency chains.
  - **Pydantic Schemas & Models**: Request body schemas and `response_model` linkages.
- **Interactive HTML Dashboard**:
  - **Topology Graph Canvas**: Powered by **Vis.js Network** with physics simulation, force-directed & hierarchical DAG layouts, and HTTP verb color coding.
  - **Search & Multi-Facet Filters**: Live search across routes, methods, tags, and dependencies; filter pills for node categories.
  - **Inspector Slide-over Drawer**: Click any node to inspect docstrings, HTTP methods, line numbers, parameter tables, and dependency trees.
  - **Route Matrix Table Tab**: Searchable, filterable catalog of all endpoints.
  - **Dependency Hierarchy Tab**: Interactive dependency explorer.
  - **Data Models Tab**: Pydantic schema explorer with field signatures.
  - **Git Diff & Architecture Changes Tab**: Compares changes after the latest commit (including untracked and modified files) or compares the last two git commits if the working tree is clean, with visual unified diffs and architecture impact tracking.
  - **One-Click Exports**: Export high-res PNG diagrams, architecture JSON, and Mermaid markdown.
- **Optional Dynamic Runtime Introspection**: Supports `--app module:app` to introspect running apps if available in the Python environment.

---

## 🚀 Quick Start

### 1. Analyze Any FastAPI Project

```bash
# Analyze a project directory and generate an interactive HTML dashboard
python3 fastapi_visualizer.py /path/to/fastapi/project -o architecture.html

# Automatically open in browser
python3 fastapi_visualizer.py /path/to/fastapi/project -o architecture.html --open

# Also export architecture metadata as JSON
python3 fastapi_visualizer.py /path/to/fastapi/project -o architecture.html --json

# Print Mermaid diagram directly to terminal
python3 fastapi_visualizer.py /path/to/fastapi/project --mermaid
```

### 2. Command-Line Options

| Option | Flag | Default | Description |
| :--- | :--- | :--- | :--- |
| `project_path` | Positional | `.` | Target FastAPI project directory |
| `-o, --output` | String | `fastapi_architecture.html` | Path for generated interactive HTML report |
| `-e, --entrypoint` | String | `None` | Optional entrypoint file (e.g. `main.py`) |
| `--app` | String | `None` | Optional dynamic app import string (e.g. `app.main:app`) |
| `--title` | String | `None` | Custom dashboard title |
| `--no-models` | Flag | `False` | Exclude schema model nodes from graph |
| `--no-deps` | Flag | `False` | Exclude dependency injection nodes from graph |
| `--open` | Flag | `False` | Automatically open generated report in browser |
| `--json` | Flag | `False` | Also export architecture data JSON file |
| `--mermaid` | Flag | `False` | Print Mermaid markdown diagram |

---

## 🧪 Testing with Open-Source Sample Projects

Download open-source moderate-sized FastAPI sample repositories:

```bash
python3 examples/download_samples.py
```

Run visualizer on real-world sample projects:

```bash
# 1. RealWorld Conduit API (nested routers, auth dependencies, database repository pattern)
python3 fastapi_visualizer.py examples/realworld_app -o realworld_architecture.html --json

# 2. Official Full-Stack FastAPI Template backend (Annotated dependencies, SQLModel)
python3 fastapi_visualizer.py examples/official_template -o template_architecture.html --json
```

---

## 🔬 Run Unit Tests

```bash
python3 -m unittest discover -s tests -v
```

---

## 📦 Python API

You can also use the visualizer programmatically inside Python scripts:

```python
from fastapi_visualizer import FastAPIAnalyzer, ArchitectureGraphBuilder, HTMLRenderer

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
