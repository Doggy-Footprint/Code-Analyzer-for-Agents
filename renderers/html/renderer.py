import html
import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from language_analyzers.core.serialization import architecture_to_dict

# vis.js line styling per edge confidence. Confidence is a semantic field the analyzers
# produce; turning it into a dash pattern belongs here so no analyzer carries presentation.
CONFIDENCE_STYLES: Dict[str, Dict[str, Any]] = {
    "static_certain": {"dashes": False, "color": "#64748B"},
    "framework_inferred": {"dashes": False, "color": "#818CF8"},
    "static_inferred": {"dashes": [8, 6], "color": "#38BDF8"},
    "dynamic_required": {"dashes": [2, 4], "color": "#F59E0B"},
}
DEFAULT_STYLE = CONFIDENCE_STYLES["static_certain"]


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

        raw_data = architecture_to_dict(arch)
        raw_data["edges"] = [self._vis_edge(edge) for edge in raw_data["edges"]]
        raw_data["confidence_styles"] = CONFIDENCE_STYLES

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

    @staticmethod
    def _vis_edge(edge: Dict[str, Any]) -> Dict[str, Any]:
        confidence = edge.get("confidence") or "static_certain"
        style = CONFIDENCE_STYLES.get(confidence, DEFAULT_STYLE)
        relation = edge.get("relation", "")
        evidence = edge.get("evidence")
        tooltip_lines = [f"<b>{relation}</b>" if relation else "<b>edge</b>"]
        if edge.get("label"):
            tooltip_lines.append(edge["label"])
        tooltip_lines.append(f"confidence: {confidence}")
        tooltip_lines.append(f"resolution: {edge.get('resolution', 'exact')}")
        if evidence:
            tooltip_lines.append(f"evidence: {evidence['file_path']}:{evidence['start_line']}")
        if edge.get("candidates"):
            tooltip_lines.append(f"other candidates: {len(edge['candidates'])}")
        if edge.get("weight", 1.0) > 1:
            tooltip_lines.append(f"occurrences: {int(edge['weight'])}")

        colour = edge.get("color") or style["color"]
        vis = dict(edge)
        vis["from"] = edge["from_id"]
        vis["to"] = edge["to_id"]
        vis["dashes"] = edge.get("dashes") or style["dashes"]
        vis["color"] = {"color": colour, "highlight": "#38BDF8", "hover": "#38BDF8"}
        vis["title"] = edge.get("title") or "<br>".join(tooltip_lines)
        return vis
