

# 🚀 Quick Start

## 1. Analyze Any FastAPI Project

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

## 2. Command-Line Options

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

# 🧪 Testing with Open-Source Sample Projects

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

# 🔬 Run Unit Tests

```bash
python3 -m unittest discover -s tests -v
```

---

# 📦 Python API

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
