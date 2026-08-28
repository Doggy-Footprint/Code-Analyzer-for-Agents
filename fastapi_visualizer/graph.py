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
    # Color palette
    COLORS = {
        "app": {"background": "#4F46E5", "border": "#3730A3", "highlight": "#6366F1"},
        "router": {"background": "#9333EA", "border": "#7E22CE", "highlight": "#A855F7"},
        "endpoint_get": {"background": "#059669", "border": "#047857", "highlight": "#10B981"},
        "endpoint_post": {"background": "#2563EB", "border": "#1D4ED8", "highlight": "#3B82F6"},
        "endpoint_put": {"background": "#D97706", "border": "#B45309", "highlight": "#F59E0B"},
        "endpoint_delete": {"background": "#E11D48", "border": "#BE123C", "highlight": "#F43F5E"},
        "endpoint_patch": {"background": "#0D9488", "border": "#0F766E", "highlight": "#14B8A6"},
        "endpoint_other": {"background": "#4B5563", "border": "#374151", "highlight": "#6B7280"},
        "dependency": {"background": "#0284C7", "border": "#0369A1", "highlight": "#38BDF8"},
        "schema": {"background": "#C026D3", "border": "#A21CAF", "highlight": "#E879F9"},
        "middleware": {"background": "#475569", "border": "#334155", "highlight": "#64748B"},
    }

    def __init__(self, include_models: bool = True, include_dependencies: bool = True):
        self.include_models = include_models
        self.include_dependencies = include_dependencies

    def build_graph(self, arch: ProjectArchitecture) -> ProjectArchitecture:
        """Populates nodes, edges, and statistics on ProjectArchitecture."""
        nodes: List[GraphNode] = []
        edges: List[GraphEdge] = []
        node_ids: Set[str] = set()

        # 1. Apps
        for app in arch.apps:
            node = GraphNode(
                id=app.id,
                label=f"🚀 {app.title}\n({app.var_name})",
                group="app",
                category="app",
                title=f"<b>FastAPI Application: {app.title}</b><br>Version: {app.version}<br>Module: {app.module}<br>File: {app.file_path}:{app.line_number}",
                shape="box",
                size=35,
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

            # Add middleware nodes
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
                        size=20,
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
                        color="#64748B"
                    ))

        # 2. Routers
        for router in arch.routers:
            prefix_label = f"\nPrefix: {router.prefix}" if router.prefix else ""
            node = GraphNode(
                id=router.id,
                label=f"📁 {router.var_name}{prefix_label}",
                group="router",
                category="router",
                title=f"<b>Router: {router.var_name}</b><br>Prefix: {router.prefix or '/'}<br>Tags: {', '.join(router.tags)}<br>Module: {router.module}<br>File: {router.file_path}:{router.line_number}",
                shape="box",
                size=30,
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

        # 3. Router Inclusions (Edges)
        # From Apps to Routers
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
                        color="#4F46E5"
                    ))

        # From Routers to Routers
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
                        color="#9333EA"
                    ))

        # 4. Endpoints
        for ep in arch.endpoints:
            method = ep.http_method.lower()
            group_name = f"endpoint_{method}" if f"endpoint_{method}" in self.COLORS else "endpoint_other"
            badge = self._get_method_badge(ep.http_method)
            
            node = GraphNode(
                id=ep.id,
                label=f"{badge} {ep.full_path or ep.path}\n({ep.function_name})",
                group=group_name,
                category="endpoint",
                title=f"<b>[{ep.http_method}] {ep.full_path or ep.path}</b><br>Handler: <code>{ep.function_name}()</code><br>Module: {ep.module}<br>Tags: {', '.join(ep.tags)}<br>Status: {ep.status_code or '200'}<br>Response: {ep.response_model or 'default'}",
                shape="box",
                size=22,
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

            # Connect to parent router or app
            if ep.router_id and ep.router_id in node_ids:
                edges.append(GraphEdge(
                    from_id=ep.router_id,
                    to_id=ep.id,
                    relation="ROUTES",
                    color="#9333EA"
                ))
            else:
                # Find router in same module or connect to default app
                matching_router = next((r for r in arch.routers if r.module == ep.module), None)
                if matching_router and matching_router.id in node_ids:
                    edges.append(GraphEdge(
                        from_id=matching_router.id,
                        to_id=ep.id,
                        relation="ROUTES",
                        color="#9333EA"
                    ))
                elif arch.apps and arch.apps[0].id in node_ids:
                    edges.append(GraphEdge(
                        from_id=arch.apps[0].id,
                        to_id=ep.id,
                        relation="ROUTES",
                        color="#4F46E5"
                    ))

        # 5. Dependencies (if enabled)
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
                    size=20,
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

            # Edges from Endpoints/Routers to Dependencies
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
                            color="#0284C7"
                        ))

            # Edges between Dependencies (Sub-dependencies)
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
                            color="#0284C7"
                        ))

        # 6. Schemas (if enabled)
        if self.include_models:
            for schema in arch.schemas:
                schema_node = GraphNode(
                    id=schema.id,
                    label=f"📦 {schema.name}",
                    group="schema",
                    category="schema",
                    title=f"<b>Schema Model: {schema.name}</b><br>Fields: {len(schema.fields)}<br>Module: {schema.module}",
                    shape="box",
                    size=18,
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

            # Connect endpoints to schemas
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
                            color="#C026D3"
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
                            color="#C026D3"
                        ))

        # 7. Compute Architecture Statistics
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
            "GET": "🟢 GET",
            "POST": "🔵 POST",
            "PUT": "🟡 PUT",
            "DELETE": "🔴 DELETE",
            "PATCH": "🟣 PATCH",
            "OPTIONS": "⚪ OPTIONS",
            "HEAD": "⚪ HEAD",
        }
        return icons.get(method.upper(), f"⚡ {method.upper()}")

    def generate_mermaid(self, arch: ProjectArchitecture) -> str:
        """Generates Mermaid diagram definition string from architecture."""
        lines = ["graph TD", "  %% FastAPI Architecture Diagram"]
        
        # Subgraphs by Module / Router
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
