"""
Graph Builder and Topology Solver for FastAPI Architecture.
Converts extracted architecture metadata into an interactive network graph (nodes and edges)
and computes architecture metrics.
"""

from collections import Counter
from typing import Any, Dict, List, Optional, Set

from .models import (
    AppInfo,
    DependencyInfo,
    EndpointInfo,
    GraphEdge,
    GraphNode,
    ProjectArchitecture,
    RouterInfo,
    SchemaInfo,
)


class ArchitectureGraphBuilder:
    COLORS = {
        "app": {
            "background": "#4338CA",
            "border": "#6366F1",
            "highlight": {"background": "#4F46E5", "border": "#A5B4FC"},
            "hover": {"background": "#4F46E5", "border": "#818CF8"},
        },
        "router": {
            "background": "#7E22CE",
            "border": "#A855F7",
            "highlight": {"background": "#9333EA", "border": "#E9D5FF"},
            "hover": {"background": "#9333EA", "border": "#C084FC"},
        },
        "endpoint_get": {
            "background": "#065F46",
            "border": "#10B981",
            "highlight": {"background": "#047857", "border": "#6EE7B7"},
            "hover": {"background": "#047857", "border": "#34D399"},
        },
        "endpoint_post": {
            "background": "#1E40AF",
            "border": "#3B82F6",
            "highlight": {"background": "#1D4ED8", "border": "#93C5FD"},
            "hover": {"background": "#1D4ED8", "border": "#60A5FA"},
        },
        "endpoint_put": {
            "background": "#92400E",
            "border": "#F59E0B",
            "highlight": {"background": "#B45309", "border": "#FDE68A"},
            "hover": {"background": "#B45309", "border": "#FBBF24"},
        },
        "endpoint_delete": {
            "background": "#9F1239",
            "border": "#F43F5E",
            "highlight": {"background": "#BE123C", "border": "#FECDD3"},
            "hover": {"background": "#BE123C", "border": "#FB7185"},
        },
        "endpoint_patch": {
            "background": "#115E59",
            "border": "#14B8A6",
            "highlight": {"background": "#0F766E", "border": "#99F6E4"},
            "hover": {"background": "#0F766E", "border": "#2DD4BF"},
        },
        "endpoint_other": {
            "background": "#374151",
            "border": "#9CA3AF",
            "highlight": {"background": "#4B5563", "border": "#E5E7EB"},
            "hover": {"background": "#4B5563", "border": "#D1D5DB"},
        },
        "dependency": {
            "background": "#0369A1",
            "border": "#38BDF8",
            "highlight": {"background": "#0284C7", "border": "#BAE6FD"},
            "hover": {"background": "#0284C7", "border": "#7DD3FC"},
        },
        "schema": {
            "background": "#86198F",
            "border": "#E879F9",
            "highlight": {"background": "#A21CAF", "border": "#F5D0FE"},
            "hover": {"background": "#A21CAF", "border": "#F0ABFC"},
        },
        "middleware": {
            "background": "#334155",
            "border": "#94A3B8",
            "highlight": {"background": "#475569", "border": "#E2E8F0"},
            "hover": {"background": "#475569", "border": "#CBD5E1"},
        },
    }

    def __init__(self, include_models: bool = True, include_dependencies: bool = True):
        self.include_models = include_models
        self.include_dependencies = include_dependencies

    def build_graph(self, arch: ProjectArchitecture) -> ProjectArchitecture:
        nodes: List[GraphNode] = []
        edges: List[GraphEdge] = []
        node_ids: Set[str] = set()

        for app in arch.apps:
            node = GraphNode(
                id=app.id,
                label=f"🚀 {app.title}\napp: {app.var_name}",
                group="app",
                category="app",
                title=f"<b>FastAPI Application: {app.title}</b><br>Version: {app.version}<br>Module: {app.module}<br>File: {app.file_path}:{app.line_number}",
                shape="box",
                size=38,
                color=self.COLORS["app"],
                metadata={
                    "type": "app",
                    "title": app.title,
                    "version": app.version,
                    "module": app.module,
                    "file_path": app.file_path,
                    "line_number": app.line_number,
                    "middlewares": app.middlewares,
                }
            )
            nodes.append(node)
            node_ids.add(node.id)

            for mw in app.middlewares:
                mw_id = f"mw_{app.id}_{mw['name']}"
                if mw_id not in node_ids:
                    mw_node = GraphNode(
                        id=mw_id,
                        label=f"🛡️ {mw['name']}",
                        group="middleware",
                        category="middleware",
                        title=f"<b>Middleware: {mw['name']}</b><br>Registered on: {app.title}",
                        shape="ellipse",
                        size=22,
                        color=self.COLORS["middleware"],
                        metadata={"name": mw["name"], "app": app.title}
                    )
                    nodes.append(mw_node)
                    node_ids.add(mw_id)
                    edges.append(GraphEdge(
                        from_id=app.id,
                        to_id=mw_id,
                        relation="MIDDLEWARE_OF",
                        label="middleware",
                        dashes=True,
                        color="#94A3B8"
                    ))

        for router in arch.routers:
            prefix_label = f"\nprefix: {router.prefix}" if router.prefix else "\nprefix: /"
            node = GraphNode(
                id=router.id,
                label=f"📁 {router.var_name}{prefix_label}",
                group="router",
                category="router",
                title=f"<b>Router: {router.var_name}</b><br>Prefix: {router.prefix or '/'}<br>Tags: {', '.join(router.tags)}<br>Module: {router.module}<br>File: {router.file_path}:{router.line_number}",
                shape="box",
                size=32,
                color=self.COLORS["router"],
                metadata={
                    "type": "router",
                    "var_name": router.var_name,
                    "prefix": router.prefix,
                    "tags": router.tags,
                    "module": router.module,
                    "file_path": router.file_path,
                    "line_number": router.line_number,
                    "dependencies": router.dependencies,
                }
            )
            nodes.append(node)
            node_ids.add(node.id)

        for app in arch.apps:
            for inc in app.inclusions:
                target_id = inc.target_router_id or self._find_router_id(inc.module_or_source, inc.router_var, arch.routers)
                if target_id and target_id in node_ids:
                    lbl = f"include {inc.prefix}" if inc.prefix else "include"
                    edges.append(GraphEdge(
                        from_id=app.id,
                        to_id=target_id,
                        relation="INCLUDES",
                        label=lbl,
                        color="#818CF8"
                    ))

        for router in arch.routers:
            for inc in router.inclusions:
                target_id = inc.target_router_id or self._find_router_id(inc.module_or_source, inc.router_var, arch.routers)
                if target_id and target_id in node_ids and target_id != router.id:
                    lbl = f"include {inc.prefix}" if inc.prefix else "include"
                    edges.append(GraphEdge(
                        from_id=router.id,
                        to_id=target_id,
                        relation="INCLUDES",
                        label=lbl,
                        color="#C084FC"
                    ))

        for ep in arch.endpoints:
            method = ep.http_method.lower()
            group_name = f"endpoint_{method}" if f"endpoint_{method}" in self.COLORS else "endpoint_other"
            badge = self._get_method_badge(ep.http_method)
            
            node = GraphNode(
                id=ep.id,
                label=f"{badge} {ep.full_path or ep.path}\n{ep.function_name}()",
                group=group_name,
                category="endpoint",
                title=f"<b>[{ep.http_method}] {ep.full_path or ep.path}</b><br>Handler: <code>{ep.function_name}()</code><br>Module: {ep.module}<br>Tags: {', '.join(ep.tags)}<br>Status: {ep.status_code or '200'}<br>Response: {ep.response_model or 'default'}",
                shape="box",
                size=26,
                color=self.COLORS[group_name],
                metadata={
                    "type": "endpoint",
                    "http_method": ep.http_method,
                    "path": ep.path,
                    "full_path": ep.full_path or ep.path,
                    "function_name": ep.function_name,
                    "module": ep.module,
                    "file_path": ep.file_path,
                    "line_number": ep.line_number,
                    "docstring": ep.docstring,
                    "summary": ep.summary,
                    "tags": ep.tags,
                    "response_model": ep.response_model,
                    "status_code": ep.status_code,
                    "parameters": [p.__dict__ for p in ep.parameters],
                    "dependencies": ep.dependencies,
                    "request_schemas": ep.request_schemas,
                    "response_schemas": ep.response_schemas,
                }
            )
            nodes.append(node)
            node_ids.add(node.id)

            if ep.router_id and ep.router_id in node_ids:
                edges.append(GraphEdge(
                    from_id=ep.router_id,
                    to_id=ep.id,
                    relation="ROUTES",
                    color="#A855F7"
                ))
            else:
                matching_router = next((r for r in arch.routers if r.module == ep.module), None)
                if matching_router and matching_router.id in node_ids:
                    edges.append(GraphEdge(
                        from_id=matching_router.id,
                        to_id=ep.id,
                        relation="ROUTES",
                        color="#A855F7"
                    ))
                elif arch.apps and arch.apps[0].id in node_ids:
                    edges.append(GraphEdge(
                        from_id=arch.apps[0].id,
                        to_id=ep.id,
                        relation="ROUTES",
                        color="#818CF8"
                    ))

        if self.include_dependencies:
            for dep in arch.dependencies:
                dep_label = f"⚙️ {dep.name}"
                dep_node = GraphNode(
                    id=dep.id,
                    label=dep_label,
                    group="dependency",
                    category="dependency",
                    title=f"<b>Dependency: {dep.name}</b><br>Kind: {dep.kind}<br>Module: {dep.module}<br>File: {dep.file_path}:{dep.line_number}",
                    shape="ellipse",
                    size=22,
                    color=self.COLORS["dependency"],
                    metadata={
                        "type": "dependency",
                        "name": dep.name,
                        "kind": dep.kind,
                        "module": dep.module,
                        "file_path": dep.file_path,
                        "line_number": dep.line_number,
                        "docstring": dep.docstring,
                        "sub_dependencies": dep.sub_dependencies,
                        "consumers": dep.consumers,
                    }
                )
                nodes.append(dep_node)
                node_ids.add(dep.id)

            for ep in arch.endpoints:
                for d_name in ep.dependencies:
                    target_dep = self._find_dep_by_name(d_name, arch.dependencies)
                    if target_dep and target_dep.id in node_ids:
                        edges.append(GraphEdge(
                            from_id=ep.id,
                            to_id=target_dep.id,
                            relation="DEPENDS_ON",
                            label="depends",
                            dashes=True,
                            color="#38BDF8"
                        ))

            for dep in arch.dependencies:
                for sub_name in dep.sub_dependencies:
                    target_sub = self._find_dep_by_name(sub_name, arch.dependencies)
                    if target_sub and target_sub.id in node_ids and target_sub.id != dep.id:
                        edges.append(GraphEdge(
                            from_id=dep.id,
                            to_id=target_sub.id,
                            relation="SUB_DEPENDENCY",
                            label="calls",
                            dashes=True,
                            color="#38BDF8"
                        ))

        if self.include_models:
            for schema in arch.schemas:
                schema_node = GraphNode(
                    id=schema.id,
                    label=f"📦 {schema.name}\n({len(schema.fields)} fields)",
                    group="schema",
                    category="schema",
                    title=f"<b>Schema Model: {schema.name}</b><br>Fields: {len(schema.fields)}<br>Module: {schema.module}",
                    shape="box",
                    size=20,
                    color=self.COLORS["schema"],
                    metadata={
                        "type": "schema",
                        "name": schema.name,
                        "module": schema.module,
                        "file_path": schema.file_path,
                        "line_number": schema.line_number,
                        "docstring": schema.docstring,
                        "base_classes": schema.base_classes,
                        "fields": [f.__dict__ for f in schema.fields],
                    }
                )
                nodes.append(schema_node)
                node_ids.add(schema.id)

            for ep in arch.endpoints:
                for req_s in ep.request_schemas:
                    target_schema = self._find_schema_by_name(req_s, arch.schemas)
                    if target_schema and target_schema.id in node_ids:
                        edges.append(GraphEdge(
                            from_id=ep.id,
                            to_id=target_schema.id,
                            relation="REQUEST_BODY",
                            label="body",
                            dashes=True,
                            color="#E879F9"
                        ))
                for resp_s in ep.response_schemas:
                    target_schema = self._find_schema_by_name(resp_s, arch.schemas)
                    if target_schema and target_schema.id in node_ids:
                        edges.append(GraphEdge(
                            from_id=ep.id,
                            to_id=target_schema.id,
                            relation="RESPONSE_MODEL",
                            label="returns",
                            dashes=True,
                            color="#E879F9"
                        ))

        methods_counter = Counter([ep.http_method for ep in arch.endpoints])
        deps_counter = Counter([d for ep in arch.endpoints for d in ep.dependencies])

        arch.nodes = nodes
        arch.edges = edges
        arch.stats = {
            "total_apps": len(arch.apps),
            "total_routers": len(arch.routers),
            "total_endpoints": len(arch.endpoints),
            "total_dependencies": len(arch.dependencies),
            "total_schemas": len(arch.schemas),
            "methods_breakdown": dict(methods_counter),
            "top_reused_dependencies": deps_counter.most_common(5),
            "unique_tags": list(set([t for ep in arch.endpoints for t in ep.tags if t])),
        }

        return arch

    @staticmethod
    def _find_router_id(module_or_source: str, var_name: str, routers: List[RouterInfo]) -> Optional[str]:
        clean_var = var_name.split(".")[-1]
        for r in routers:
            if r.var_name == clean_var and (r.module == module_or_source or r.module.endswith(module_or_source)):
                return r.id
        for r in routers:
            if r.var_name == clean_var or r.module == module_or_source:
                return r.id
        return None

    @staticmethod
    def _find_dep_by_name(name: str, dependencies: List[DependencyInfo]) -> Optional[DependencyInfo]:
        clean_name = name.split("(")[0].split(".")[-1]
        for d in dependencies:
            if d.name == clean_name or d.name == name or d.id.endswith(f"_{clean_name}"):
                return d
        return None

    @staticmethod
    def _find_schema_by_name(name: str, schemas: List[SchemaInfo]) -> Optional[SchemaInfo]:
        clean_name = name.split(".")[-1]
        for s in schemas:
            if s.name == clean_name or s.name == name:
                return s
        return None

    @staticmethod
    def _get_method_badge(method: str) -> str:
        icons = {
            "GET": "GET",
            "POST": "POST",
            "PUT": "PUT",
            "DELETE": "DEL",
            "PATCH": "PATCH",
            "OPTIONS": "OPT",
            "HEAD": "HEAD",
        }
        return icons.get(method.upper(), method.upper())

    def generate_mermaid(self, arch: ProjectArchitecture) -> str:
        lines = ["graph TD", "  %% FastAPI Architecture Diagram"]
        
        for app in arch.apps:
            lines.append(f'  subgraph App_{app.var_name} ["App: {app.title}"]')
            lines.append(f'    {app.id}["🚀 {app.title}"]')
            lines.append("  end")

        for router in arch.routers:
            lines.append(f'  subgraph Router_{router.var_name} ["Router: {router.var_name} ({router.prefix or "/"})"]')
            lines.append(f'    {router.id}["📁 {router.var_name}"]')
            lines.append("  end")

        for edge in arch.edges:
            lbl = f"|{edge.label}|" if edge.label else ""
            arrow = "-.->" if edge.dashes else "-->"
            lines.append(f"  {edge.from_id} {arrow}{lbl} {edge.to_id}")

        return "\n".join(lines)
