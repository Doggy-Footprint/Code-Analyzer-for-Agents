import html
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional


class HTMLRenderer:
    def __init__(self, title: Optional[str] = None, framework_label: str = ""):
        self.title = title
        self.framework_label = framework_label
        self.package_dir = Path(__file__).resolve().parent

    def render(self, arch: Any, output_path: str) -> Path:
        output = Path(output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        asset_dir = output.parent / f"{output.stem}_assets"
        asset_dir.mkdir(parents=True, exist_ok=True)

        for asset_name in ("styles.css", "tailwind-config.js", "app.js"):
            shutil.copyfile(
                self.package_dir / "static" / asset_name,
                asset_dir / asset_name,
            )

        raw_data = {
            "project_name": arch.project_name,
            "project_path": arch.project_path,
            "stats": arch.stats,
            "nodes": [
                {
                    "id": node.id,
                    "label": node.label,
                    "group": node.group,
                    "category": node.category,
                    "title": node.title,
                    "shape": node.shape,
                    "size": node.size,
                    "color": node.color,
                    "metadata": node.metadata,
                }
                for node in arch.nodes
            ],
            "edges": [
                {
                    "from": edge.from_id,
                    "to": edge.to_id,
                    "relation": edge.relation,
                    "label": edge.label,
                    "dashes": edge.dashes,
                    "arrows": edge.arrows,
                    "color": {
                        "color": edge.color or "#64748B",
                        "highlight": "#38BDF8",
                        "hover": "#38BDF8",
                    },
                    "title": edge.title or (
                        f"{edge.relation}: {edge.label}" if edge.label else edge.relation
                    ),
                }
                for edge in arch.edges
            ],
            "collections": {
                collection.key: {
                    "label": collection.label,
                    "icon": getattr(collection, "icon", "box"),
                    "view": collection.view,
                    "node_category": collection.node_category,
                    "columns": [asdict(column) for column in collection.columns],
                    "rows": collection.rows,
                }
                for collection in getattr(arch, "report_collections", [])
            },
            "git_diff": asdict(arch.git_diff) if arch.git_diff else None,
        }

        document = (self.package_dir / "templates" / "dashboard.html").read_text(encoding="utf-8")
        replacements = {
            "{{DOC_TITLE}}": html.escape(self.title or f"Architecture - {arch.project_name}"),
            "{{PROJECT_PATH}}": html.escape(arch.project_path),
            "{{FRAMEWORK_LABEL}}": html.escape(self.framework_label or "Analyzer"),
            "{{ASSET_DIR}}": asset_dir.name,
            "{{ARCH_DATA}}": json.dumps(raw_data, ensure_ascii=False, default=str).replace("<", "\\u003c"),
        }
        for placeholder, value in replacements.items():
            document = document.replace(placeholder, value)

        output.write_text(document, encoding="utf-8")
        return output
