"""
Interactive HTML Dashboard Renderer for FastAPI Architecture.
Compiles architecture graphs and metadata into a standalone, single-file HTML application.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .models import ProjectArchitecture


class HTMLRenderer:
    def __init__(self, title: Optional[str] = None):
        self.title = title

    def render(self, arch: ProjectArchitecture, output_path: str) -> Path:
        """Renders the architecture graph into a standalone HTML file."""
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        doc_title = self.title or f"FastAPI Architecture - {arch.project_name}"
        
        # Serialize graph data
        nodes_data = [
            {
                "id": n.id,
                "label": n.label,
                "group": n.group,
                "category": n.category,
                "title": n.title,
                "shape": n.shape,
                "size": n.size,
                "color": n.color,
                "metadata": n.metadata,
            }
            for n in arch.nodes
        ]

        edges_data = [
            {
                "from": e.from_id,
                "to": e.to_id,
                "relation": e.relation,
                "label": e.label,
                "dashes": e.dashes,
                "arrows": e.arrows,
                "color": {"color": e.color or "#64748B", "highlight": "#38BDF8"},
                "title": e.title or f"{e.relation}: {e.label}" if e.label else e.relation,
            }
            for e in arch.edges
        ]

        raw_data = {
            "project_name": arch.project_name,
            "project_path": arch.project_path,
            "stats": arch.stats,
            "nodes": nodes_data,
            "edges": edges_data,
            "endpoints": [asdict(ep) for ep in arch.endpoints],
            "routers": [asdict(r) for r in arch.routers],
            "dependencies": [asdict(d) for d in arch.dependencies],
            "schemas": [asdict(s) for s in arch.schemas],
        }

        html_content = self._generate_html_template(doc_title, raw_data)
        
        with open(out, "w", encoding="utf-8") as f:
            f.write(html_content)

        return out

    def _generate_html_template(self, doc_title: str, raw_data: dict) -> str:
        data_json = json.dumps(raw_data, ensure_ascii=False)

        return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{doc_title}</title>
  <!-- Tailwind CSS -->
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          colors: {{
            brand: {{
              50: '#eef2ff',
              100: '#e0e7ff',
              500: '#6366f1',
              600: '#4f46e5',
              700: '#4338ca',
              900: '#312e81',
            }}
          }}
        }}
      }}
    }}
  </script>
  <!-- Vis.js Network -->
  <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <!-- Lucide Icons -->
  <script src="https://unpkg.com/lucide@latest"></script>
  
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }}
    #network-container {{
      width: 100%;
      height: 100%;
      background: radial-gradient(circle at center, #1e293b 0%, #0f172a 100%);
    }}
    .light #network-container {{
      background: radial-gradient(circle at center, #f8fafc 0%, #e2e8f0 100%);
    }}
    /* Custom scrollbar */
    ::-webkit-scrollbar {{
      width: 6px;
      height: 6px;
    }}
    ::-webkit-scrollbar-track {{
      background: rgba(0, 0, 0, 0.1);
    }}
    ::-webkit-scrollbar-thumb {{
      background: rgba(148, 163, 184, 0.3);
      border-radius: 3px;
    }}
    ::-webkit-scrollbar-thumb:hover {{
      background: rgba(148, 163, 184, 0.5);
    }}
  </style>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen flex flex-col overflow-hidden select-none">

  <!-- Top Header Navigation -->
  <header class="bg-slate-800/90 backdrop-blur border-b border-slate-700/80 px-5 py-3 flex items-center justify-between z-30 shrink-0">
    <div class="flex items-center space-x-3">
      <div class="p-2 bg-indigo-600/20 text-indigo-400 rounded-lg border border-indigo-500/30">
        <i data-lucide="network" class="w-5 h-5"></i>
      </div>
      <div>
        <div class="flex items-center space-x-2">
          <h1 class="font-bold text-lg text-white leading-tight">{doc_title}</h1>
          <span class="text-xs bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded border border-indigo-500/30">FastAPI</span>
        </div>
        <p class="text-xs text-slate-400 font-mono truncate max-w-md" id="header-path">{raw_data['project_path']}</p>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <div class="flex items-center bg-slate-900/80 p-1 rounded-xl border border-slate-700/60 space-x-1">
      <button onclick="switchTab('graph')" id="tab-btn-graph" class="tab-btn flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 text-white shadow-sm transition">
        <i data-lucide="git-fork" class="w-4 h-4"></i>
        <span>Topology Graph</span>
      </button>
      <button onclick="switchTab('routes')" id="tab-btn-routes" class="tab-btn flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition">
        <i data-lucide="list-tree" class="w-4 h-4"></i>
        <span>Route Matrix</span>
      </button>
      <button onclick="switchTab('deps')" id="tab-btn-deps" class="tab-btn flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition">
        <i data-lucide="boxes" class="w-4 h-4"></i>
        <span>Dependencies</span>
      </button>
      <button onclick="switchTab('schemas')" id="tab-btn-schemas" class="tab-btn flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition">
        <i data-lucide="database" class="w-4 h-4"></i>
        <span>Models / Schemas</span>
      </button>
    </div>

    <!-- Action Toolbar -->
    <div class="flex items-center space-x-2">
      <!-- Layout Toggle -->
      <button onclick="toggleLayout()" id="layout-toggle-btn" class="flex items-center space-x-1 px-3 py-1.5 bg-slate-700/60 hover:bg-slate-700 text-xs text-slate-200 rounded-lg border border-slate-600 transition" title="Toggle Force-Directed / Hierarchical Layout">
        <i data-lucide="layout" class="w-3.5 h-3.5"></i>
        <span id="layout-label">Hierarchical</span>
      </button>

      <!-- Physics Toggle -->
      <button onclick="togglePhysics()" id="physics-toggle-btn" class="flex items-center space-x-1 px-3 py-1.5 bg-slate-700/60 hover:bg-slate-700 text-xs text-slate-200 rounded-lg border border-slate-600 transition" title="Toggle Physics Simulation">
        <i data-lucide="zap" class="w-3.5 h-3.5"></i>
        <span id="physics-label">Physics: On</span>
      </button>

      <!-- Export Dropdown -->
      <div class="relative group">
        <button class="flex items-center space-x-1 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-xs text-white font-medium rounded-lg transition shadow-sm">
          <i data-lucide="download" class="w-3.5 h-3.5"></i>
          <span>Export</span>
          <i data-lucide="chevron-down" class="w-3 h-3 ml-1"></i>
        </button>
        <div class="absolute right-0 mt-1 w-44 bg-slate-800 border border-slate-700 rounded-xl shadow-xl py-1 hidden group-hover:block z-50">
          <button onclick="exportPNG()" class="w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-slate-700 hover:text-white flex items-center space-x-2">
            <i data-lucide="image" class="w-3.5 h-3.5"></i>
            <span>Export Graph (PNG)</span>
          </button>
          <button onclick="exportJSON()" class="w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-slate-700 hover:text-white flex items-center space-x-2">
            <i data-lucide="file-code" class="w-3.5 h-3.5"></i>
            <span>Export Architecture (JSON)</span>
          </button>
          <button onclick="exportMermaid()" class="w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-slate-700 hover:text-white flex items-center space-x-2">
            <i data-lucide="file-text" class="w-3.5 h-3.5"></i>
            <span>Copy Mermaid Diagram</span>
          </button>
        </div>
      </div>
    </div>
  </header>

  <!-- Metrics Subheader -->
  <div class="bg-slate-800/40 border-b border-slate-800 px-5 py-2 flex items-center justify-between text-xs text-slate-400 shrink-0">
    <div class="flex items-center space-x-6">
      <div class="flex items-center space-x-2">
        <span class="text-slate-500">Endpoints:</span>
        <span class="font-bold text-slate-200" id="stat-endpoints">{raw_data['stats'].get('total_endpoints', 0)}</span>
      </div>
      <div class="flex items-center space-x-2">
        <span class="text-slate-500">Routers:</span>
        <span class="font-bold text-slate-200" id="stat-routers">{raw_data['stats'].get('total_routers', 0)}</span>
      </div>
      <div class="flex items-center space-x-2">
        <span class="text-slate-500">Dependencies:</span>
        <span class="font-bold text-slate-200" id="stat-deps">{raw_data['stats'].get('total_dependencies', 0)}</span>
      </div>
      <div class="flex items-center space-x-2">
        <span class="text-slate-500">Schemas:</span>
        <span class="font-bold text-slate-200" id="stat-schemas">{raw_data['stats'].get('total_schemas', 0)}</span>
      </div>
    </div>

    <!-- HTTP Method Badges -->
    <div class="flex items-center space-x-2" id="method-badges-bar">
      <!-- Populated by JS -->
    </div>
  </div>

  <!-- Main Content View Area -->
  <main class="flex-1 relative flex overflow-hidden">

    <!-- TAB 1: Graph View -->
    <div id="view-graph" class="tab-view w-full h-full flex flex-col relative">
      <!-- Search & Filter Controls Floating Bar -->
      <div class="absolute top-4 left-4 z-20 flex flex-col space-y-2 max-w-sm w-full">
        <!-- Search Input -->
        <div class="relative">
          <i data-lucide="search" class="w-4 h-4 absolute left-3 top-2.5 text-slate-400"></i>
          <input type="text" id="graph-search" oninput="handleSearch(this.value)" placeholder="Search routes, methods, tags, deps..."
                 class="w-full pl-9 pr-8 py-2 bg-slate-800/90 backdrop-blur border border-slate-700 rounded-xl text-xs text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-lg">
          <button onclick="clearSearch()" id="clear-search-btn" class="hidden absolute right-2.5 top-2 text-slate-400 hover:text-white">
            <i data-lucide="x" class="w-4 h-4"></i>
          </button>
        </div>

        <!-- Filter Pills Bar -->
        <div class="bg-slate-800/90 backdrop-blur border border-slate-700 p-2.5 rounded-xl shadow-lg flex flex-col space-y-2 text-xs">
          <div class="text-slate-400 font-semibold text-[11px] flex justify-between items-center">
            <span>FILTER NODE TYPES</span>
            <button onclick="resetFilters()" class="text-indigo-400 hover:underline">Reset</button>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <button onclick="toggleFilterType('endpoint')" id="filter-btn-endpoint" class="filter-pill px-2 py-1 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-[11px]">Endpoints</button>
            <button onclick="toggleFilterType('router')" id="filter-btn-router" class="filter-pill px-2 py-1 rounded bg-purple-500/20 text-purple-300 border border-purple-500/40 text-[11px]">Routers</button>
            <button onclick="toggleFilterType('dependency')" id="filter-btn-dependency" class="filter-pill px-2 py-1 rounded bg-sky-500/20 text-sky-300 border border-sky-500/40 text-[11px]">Dependencies</button>
            <button onclick="toggleFilterType('schema')" id="filter-btn-schema" class="filter-pill px-2 py-1 rounded bg-fuchsia-500/20 text-fuchsia-300 border border-fuchsia-500/40 text-[11px]">Schemas</button>
            <button onclick="toggleFilterType('app')" id="filter-btn-app" class="filter-pill px-2 py-1 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 text-[11px]">App</button>
          </div>
        </div>
      </div>

      <!-- Graph Canvas -->
      <div id="network-container" class="w-full h-full"></div>

      <!-- Quick Canvas Controls Floating Bottom-Left -->
      <div class="absolute bottom-4 left-4 z-20 flex items-center space-x-2 bg-slate-800/90 backdrop-blur border border-slate-700 p-1.5 rounded-xl shadow-lg">
        <button onclick="network.fit({{animation: true}})" class="p-2 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg transition" title="Fit to Screen">
          <i data-lucide="maximize-2" class="w-4 h-4"></i>
        </button>
        <button onclick="zoomIn()" class="p-2 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg transition" title="Zoom In">
          <i data-lucide="zoom-in" class="w-4 h-4"></i>
        </button>
        <button onclick="zoomOut()" class="p-2 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg transition" title="Zoom Out">
          <i data-lucide="zoom-out" class="w-4 h-4"></i>
        </button>
        <div class="h-4 w-px bg-slate-700 mx-1"></div>
        <button onclick="stabilizeGraph()" class="p-2 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg transition" title="Re-stabilize Layout">
          <i data-lucide="refresh-cw" class="w-4 h-4"></i>
        </button>
      </div>

      <!-- Slide-over Inspector Drawer -->
      <div id="inspector-drawer" class="absolute top-0 right-0 h-full w-96 bg-slate-800/95 backdrop-blur-md border-l border-slate-700 shadow-2xl p-6 overflow-y-auto transform translate-x-full transition-transform duration-300 ease-in-out z-30 flex flex-col">
        <div class="flex items-center justify-between border-b border-slate-700 pb-3 mb-4">
          <div class="flex items-center space-x-2">
            <span id="inspector-badge" class="px-2 py-0.5 rounded text-xs font-bold bg-slate-700 text-white">TYPE</span>
            <h3 id="inspector-title" class="font-bold text-slate-100 text-sm truncate max-w-[200px]">Node Details</h3>
          </div>
          <button onclick="closeInspector()" class="p-1 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-white">
            <i data-lucide="x" class="w-4 h-4"></i>
          </button>
        </div>
        <div id="inspector-content" class="text-xs space-y-4 flex-1">
          <!-- Populated by JS on node click -->
        </div>
      </div>
    </div>

    <!-- TAB 2: Route Matrix Table -->
    <div id="view-routes" class="tab-view w-full h-full hidden overflow-auto p-6 bg-slate-900">
      <div class="max-w-7xl mx-auto space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-lg font-bold text-white">API Route Matrix</h2>
            <p class="text-xs text-slate-400">Complete catalog of endpoints, HTTP verbs, resolved paths, parameters, and dependencies.</p>
          </div>
          <input type="text" id="route-table-search" oninput="filterRouteTable(this.value)" placeholder="Filter routes..."
                 class="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 w-64">
        </div>

        <div class="border border-slate-700/80 rounded-xl overflow-hidden shadow-xl bg-slate-800/60">
          <table class="w-full text-left text-xs text-slate-300">
            <thead class="bg-slate-800 text-slate-400 font-semibold border-b border-slate-700">
              <tr>
                <th class="p-3 w-20">Method</th>
                <th class="p-3">Resolved Path</th>
                <th class="p-3">Handler Function</th>
                <th class="p-3">Tags</th>
                <th class="p-3">Dependencies</th>
                <th class="p-3">Response Model</th>
                <th class="p-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody id="routes-table-body" class="divide-y divide-slate-700/60">
              <!-- Populated by JS -->
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- TAB 3: Dependencies Tree -->
    <div id="view-deps" class="tab-view w-full h-full hidden overflow-auto p-6 bg-slate-900">
      <div class="max-w-7xl mx-auto space-y-4">
        <div>
          <h2 class="text-lg font-bold text-white">FastAPI Dependency Tree</h2>
          <p class="text-xs text-slate-400">Dependency Injection call hierarchy, security schemes, and consumer mapping.</p>
        </div>
        <div id="deps-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <!-- Populated by JS -->
        </div>
      </div>
    </div>

    <!-- TAB 4: Schemas Models -->
    <div id="view-schemas" class="tab-view w-full h-full hidden overflow-auto p-6 bg-slate-900">
      <div class="max-w-7xl mx-auto space-y-4">
        <div>
          <h2 class="text-lg font-bold text-white">Data Schemas & Pydantic Models</h2>
          <p class="text-xs text-slate-400">Pydantic models, request body schemas, and response types.</p>
        </div>
        <div id="schemas-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <!-- Populated by JS -->
        </div>
      </div>
    </div>

  </main>

  <!-- Embedded Data & Client Scripts -->
  <script>
    const ARCH_DATA = {data_json};

    let network = null;
    let nodesDataSet = null;
    let edgesDataSet = null;
    let isHierarchical = false;
    let physicsEnabled = true;
    let activeFilters = {{
      endpoint: true,
      router: true,
      dependency: true,
      schema: true,
      app: true,
    }};

    // Initialize on page load
    document.addEventListener('DOMContentLoaded', () => {{
      lucide.createIcons();
      initBadges();
      initNetwork();
      populateRouteTable();
      populateDepsGrid();
      populateSchemasGrid();
    }});

    function initBadges() {{
      const bar = document.getElementById('method-badges-bar');
      const mb = ARCH_DATA.stats.methods_breakdown || {{}};
      const colors = {{
        GET: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
        POST: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
        PUT: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
        DELETE: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
        PATCH: 'bg-teal-500/20 text-teal-400 border-teal-500/30',
      }};
      let html = '';
      for (const [method, count] of Object.entries(mb)) {{
        const cls = colors[method.toUpperCase()] || 'bg-slate-700 text-slate-300 border-slate-600';
        html += `<span class="px-2 py-0.5 rounded text-[11px] font-mono border ${{cls}} font-semibold">${{method}}: ${{count}}</span>`;
      }}
      bar.innerHTML = html;
    }}

    function initNetwork() {{
      const container = document.getElementById('network-container');
      
      nodesDataSet = new vis.DataSet(ARCH_DATA.nodes);
      edgesDataSet = new vis.DataSet(ARCH_DATA.edges);

      const data = {{
        nodes: nodesDataSet,
        edges: edgesDataSet
      }};

      const options = {{
        nodes: {{
          font: {{
            color: '#f8fafc',
            size: 12,
            face: 'ui-sans-serif, system-ui, sans-serif'
          }},
          borderWidth: 1.5,
          shadow: {{
            enabled: true,
            color: 'rgba(0,0,0,0.4)',
            size: 6,
            x: 2,
            y: 2
          }}
        }},
        edges: {{
          font: {{
            color: '#94a3b8',
            size: 10,
            align: 'top'
          }},
          arrows: {{
            to: {{ enabled: true, scaleFactor: 0.6 }}
          }},
          smooth: {{
            type: 'cubicBezier',
            roundness: 0.3
          }}
        }},
        physics: {{
          enabled: true,
          solver: 'forceAtlas2Based',
          forceAtlas2Based: {{
            gravitationalConstant: -70,
            centralGravity: 0.01,
            springLength: 130,
            springConstant: 0.08,
            damping: 0.8
          }},
          stabilization: {{
            iterations: 150
          }}
        }},
        interaction: {{
          hover: true,
          tooltipDelay: 100,
          navigationButtons: false,
          keyboard: true
        }}
      }};

      network = new vis.Network(container, data, options);

      // Node click handler
      network.on('click', (params) => {{
        if (params.nodes.length > 0) {{
          const nodeId = params.nodes[0];
          const node = nodesDataSet.get(nodeId);
          showInspector(node);
        }} else {{
          closeInspector();
        }}
      }});

      // Double click to focus & zoom
      network.on('doubleClick', (params) => {{
        if (params.nodes.length > 0) {{
          network.focus(params.nodes[0], {{
            scale: 1.2,
            animation: true
          }});
        }}
      }});
    }}

    function switchTab(tabId) {{
      document.querySelectorAll('.tab-view').forEach(v => v.classList.add('hidden'));
      document.querySelectorAll('.tab-btn').forEach(b => {{
        b.classList.remove('bg-indigo-600', 'text-white', 'shadow-sm');
        b.classList.add('text-slate-400');
      }});

      document.getElementById(`view-${{tabId}}`).classList.remove('hidden');
      const activeBtn = document.getElementById(`tab-btn-${{tabId}}`);
      activeBtn.classList.add('bg-indigo-600', 'text-white', 'shadow-sm');
      activeBtn.classList.remove('text-slate-400');

      if (tabId === 'graph' && network) {{
        setTimeout(() => {{
          network.redraw();
          network.fit();
        }}, 50);
      }}
    }}

    function toggleLayout() {{
      isHierarchical = !isHierarchical;
      const label = document.getElementById('layout-label');
      label.innerText = isHierarchical ? 'Force-Directed' : 'Hierarchical';

      if (isHierarchical) {{
        network.setOptions({{
          layout: {{
            hierarchical: {{
              enabled: true,
              direction: 'UD',
              sortMethod: 'directed',
              levelSeparation: 150,
              nodeSpacing: 180,
            }}
          }},
          physics: {{ enabled: false }}
        }});
      }} else {{
        network.setOptions({{
          layout: {{ hierarchical: {{ enabled: false }} }},
          physics: {{
            enabled: true,
            solver: 'forceAtlas2Based',
            forceAtlas2Based: {{
              gravitationalConstant: -70,
              centralGravity: 0.01,
              springLength: 130,
            }}
          }}
        }});
      }}
    }}

    function togglePhysics() {{
      physicsEnabled = !physicsEnabled;
      document.getElementById('physics-label').innerText = `Physics: ${{physicsEnabled ? 'On' : 'Off'}}`;
      network.setOptions({{ physics: {{ enabled: physicsEnabled }} }});
    }}

    function zoomIn() {{
      const scale = network.getScale() * 1.3;
      network.moveTo({{ scale: scale, animation: true }});
    }}

    function zoomOut() {{
      const scale = network.getScale() * 0.7;
      network.moveTo({{ scale: scale, animation: true }});
    }}

    function stabilizeGraph() {{
      network.stabilize();
    }}

    function toggleFilterType(category) {{
      activeFilters[category] = !activeFilters[category];
      const btn = document.getElementById(`filter-btn-${{category}}`);
      if (activeFilters[category]) {{
        btn.classList.remove('opacity-40');
      }} else {{
        btn.classList.add('opacity-40');
      }}
      applyFilters();
    }}

    function resetFilters() {{
      Object.keys(activeFilters).forEach(k => {{
        activeFilters[k] = true;
        const btn = document.getElementById(`filter-btn-${{k}}`);
        if (btn) btn.classList.remove('opacity-40');
      }});
      applyFilters();
    }}

    function applyFilters() {{
      const filteredNodes = ARCH_DATA.nodes.filter(n => activeFilters[n.category] !== false);
      const activeNodeIds = new Set(filteredNodes.map(n => n.id));
      const filteredEdges = ARCH_DATA.edges.filter(e => activeNodeIds.has(e.from) && activeNodeIds.has(e.to));

      nodesDataSet.clear();
      nodesDataSet.add(filteredNodes);
      edgesDataSet.clear();
      edgesDataSet.add(filteredEdges);
    }}

    function handleSearch(query) {{
      const q = query.trim().toLowerCase();
      const clearBtn = document.getElementById('clear-search-btn');
      clearBtn.classList.toggle('hidden', !q);

      if (!q) {{
        applyFilters();
        return;
      }}

      const matchedNodes = ARCH_DATA.nodes.filter(n => {{
        const lbl = (n.label || '').toLowerCase();
        const meta = JSON.stringify(n.metadata || {{}}).toLowerCase();
        return lbl.includes(q) || meta.includes(q);
      }});

      const matchedIds = new Set(matchedNodes.map(n => n.id));
      
      // Also include 1-hop connected neighbors
      ARCH_DATA.edges.forEach(e => {{
        if (matchedIds.has(e.from)) matchedIds.add(e.to);
        if (matchedIds.has(e.to)) matchedIds.add(e.from);
      }});

      const nodesToShow = ARCH_DATA.nodes.filter(n => matchedIds.has(n.id));
      const edgesToShow = ARCH_DATA.edges.filter(e => matchedIds.has(e.from) && matchedIds.has(e.to));

      nodesDataSet.clear();
      nodesDataSet.add(nodesToShow);
      edgesDataSet.clear();
      edgesDataSet.add(edgesToShow);

      if (matchedNodes.length > 0) {{
        network.focus(matchedNodes[0].id, {{ scale: 1.1, animation: true }});
      }}
    }}

    function clearSearch() {{
      document.getElementById('graph-search').value = '';
      document.getElementById('clear-search-btn').classList.add('hidden');
      applyFilters();
    }}

    function showInspector(node) {{
      const drawer = document.getElementById('inspector-drawer');
      const badge = document.getElementById('inspector-badge');
      const title = document.getElementById('inspector-title');
      const content = document.getElementById('inspector-content');

      badge.innerText = (node.category || 'node').toUpperCase();
      title.innerText = node.label.split('\\n')[0];

      let html = '';
      const meta = node.metadata || {{}};

      if (node.category === 'endpoint') {{
        const methodColors = {{
          GET: 'bg-emerald-500/20 text-emerald-400',
          POST: 'bg-blue-500/20 text-blue-400',
          PUT: 'bg-amber-500/20 text-amber-400',
          DELETE: 'bg-rose-500/20 text-rose-400',
          PATCH: 'bg-teal-500/20 text-teal-400',
        }};
        const mCls = methodColors[meta.http_method] || 'bg-slate-700 text-slate-200';

        html += `
          <div class="bg-slate-900/60 p-3 rounded-xl border border-slate-700 space-y-2">
            <div class="flex items-center space-x-2">
              <span class="px-2 py-0.5 rounded font-mono font-bold text-xs ${{mCls}}">${{meta.http_method}}</span>
              <span class="font-mono text-white text-xs font-semibold break-all">${{meta.full_path}}</span>
            </div>
            <div class="text-slate-400 text-[11px] font-mono">Handler: <span class="text-indigo-300 font-semibold">${{meta.function_name}}()</span></div>
            <div class="text-slate-500 text-[11px] font-mono">${{meta.file_path}}:${{meta.line_number}}</div>
          </div>
        `;

        if (meta.docstring) {{
          html += `
            <div>
              <div class="text-slate-400 font-semibold mb-1 text-[11px]">DOCSTRING</div>
              <div class="bg-slate-900/40 p-2.5 rounded-lg text-slate-300 font-mono text-[11px] whitespace-pre-wrap">${{meta.docstring}}</div>
            </div>
          `;
        }}

        if (meta.parameters && meta.parameters.length > 0) {{
          html += `
            <div>
              <div class="text-slate-400 font-semibold mb-1 text-[11px]">PARAMETERS (${{meta.parameters.length}})</div>
              <div class="space-y-1.5">
                ${{meta.parameters.map(p => `
                  <div class="bg-slate-900/40 p-2 rounded border border-slate-700/60 flex flex-col">
                    <div class="flex items-center justify-between">
                      <span class="font-mono text-indigo-300 font-semibold">${{p.name}}</span>
                      <span class="text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400 font-mono">${{p.kind}}</span>
                    </div>
                    ${{p.type_annotation ? `<span class="text-slate-400 text-[11px] font-mono">Type: ${{p.type_annotation}}</span>` : ''}}
                    ${{p.default_value ? `<span class="text-slate-500 text-[10px] font-mono">Default: ${{p.default_value}}</span>` : ''}}
                  </div>
                `).join('')}}
              </div>
            </div>
          `;
        }}

        if (meta.dependencies && meta.dependencies.length > 0) {{
          html += `
            <div>
              <div class="text-slate-400 font-semibold mb-1 text-[11px]">DEPENDENCIES</div>
              <div class="flex flex-wrap gap-1">
                ${{meta.dependencies.map(d => `<span class="bg-sky-500/20 text-sky-300 px-2 py-0.5 rounded text-[11px] border border-sky-500/30 font-mono">${{d}}</span>`).join('')}}
              </div>
            </div>
          `;
        }}

        if (meta.response_model) {{
          html += `
            <div>
              <div class="text-slate-400 font-semibold mb-1 text-[11px]">RESPONSE MODEL</div>
              <div class="bg-fuchsia-500/20 text-fuchsia-300 px-2.5 py-1 rounded text-[11px] border border-fuchsia-500/30 font-mono font-semibold">${{meta.response_model}}</div>
            </div>
          `;
        }}
      }} else if (node.category === 'router') {{
        html += `
          <div class="bg-slate-900/60 p-3 rounded-xl border border-slate-700 space-y-2">
            <div class="text-purple-300 font-bold text-sm">Router: ${{meta.var_name}}</div>
            <div class="text-slate-400 text-xs">Prefix: <code class="text-white">${{meta.prefix || '/'}}</code></div>
            <div class="text-slate-400 text-xs">Tags: ${{meta.tags && meta.tags.length ? meta.tags.join(', ') : 'None'}}</div>
            <div class="text-slate-500 text-[11px] font-mono">${{meta.file_path}}:${{meta.line_number}}</div>
          </div>
        `;
      }} else if (node.category === 'dependency') {{
        html += `
          <div class="bg-slate-900/60 p-3 rounded-xl border border-slate-700 space-y-2">
            <div class="text-sky-300 font-bold text-sm">Dependency: ${{meta.name}}</div>
            <div class="text-slate-400 text-xs">Kind: <span class="text-slate-200">${{meta.kind}}</span></div>
            <div class="text-slate-500 text-[11px] font-mono">${{meta.file_path}}:${{meta.line_number}}</div>
          </div>
        `;
        if (meta.docstring) {{
          html += `
            <div>
              <div class="text-slate-400 font-semibold mb-1 text-[11px]">DOCSTRING</div>
              <div class="bg-slate-900/40 p-2.5 rounded-lg text-slate-300 font-mono text-[11px]">${{meta.docstring}}</div>
            </div>
          `;
        }}
        if (meta.sub_dependencies && meta.sub_dependencies.length > 0) {{
          html += `
            <div>
              <div class="text-slate-400 font-semibold mb-1 text-[11px]">SUB-DEPENDENCIES</div>
              <div class="flex flex-wrap gap-1">
                ${{meta.sub_dependencies.map(d => `<span class="bg-sky-500/20 text-sky-300 px-2 py-0.5 rounded text-[11px] border border-sky-500/30 font-mono">${{d}}</span>`).join('')}}
              </div>
            </div>
          `;
        }}
      }} else if (node.category === 'schema') {{
        html += `
          <div class="bg-slate-900/60 p-3 rounded-xl border border-slate-700 space-y-2">
            <div class="text-fuchsia-300 font-bold text-sm">Model: ${{meta.name}}</div>
            <div class="text-slate-400 text-xs">Bases: ${{meta.base_classes ? meta.base_classes.join(', ') : 'BaseModel'}}</div>
            <div class="text-slate-500 text-[11px] font-mono">${{meta.file_path}}:${{meta.line_number}}</div>
          </div>
        `;
        if (meta.fields && meta.fields.length > 0) {{
          html += `
            <div>
              <div class="text-slate-400 font-semibold mb-1 text-[11px]">MODEL FIELDS (${{meta.fields.length}})</div>
              <div class="space-y-1.5">
                ${{meta.fields.map(f => `
                  <div class="bg-slate-900/40 p-2 rounded border border-slate-700/60 flex items-center justify-between font-mono">
                    <span class="text-fuchsia-300 font-semibold">${{f.name}}</span>
                    <span class="text-slate-400 text-[11px]">${{f.type_annotation}}</span>
                  </div>
                `).join('')}}
              </div>
            </div>
          `;
        }}
      }}

      content.innerHTML = html;
      drawer.classList.remove('translate-x-full');
      lucide.createIcons();
    }}

    function closeInspector() {{
      document.getElementById('inspector-drawer').classList.add('translate-x-full');
    }}

    function populateRouteTable() {{
      const tbody = document.getElementById('routes-table-body');
      const endpoints = ARCH_DATA.endpoints || [];

      const methodColors = {{
        GET: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
        POST: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
        PUT: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
        DELETE: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
        PATCH: 'bg-teal-500/20 text-teal-400 border-teal-500/30',
      }};

      tbody.innerHTML = endpoints.map(ep => {{
        const mCls = methodColors[ep.http_method] || 'bg-slate-700 text-slate-300 border-slate-600';
        return `
          <tr class="hover:bg-slate-800/80 transition">
            <td class="p-3">
              <span class="px-2 py-0.5 rounded font-mono font-bold text-[11px] border ${{mCls}}">${{ep.http_method}}</span>
            </td>
            <td class="p-3 font-mono font-semibold text-white">${{ep.full_path || ep.path}}</td>
            <td class="p-3 font-mono text-indigo-300">${{ep.function_name}}()</td>
            <td class="p-3 text-slate-400">${{ep.tags && ep.tags.length ? ep.tags.join(', ') : '-'}}</td>
            <td class="p-3 text-sky-400 font-mono text-[11px]">${{ep.dependencies && ep.dependencies.length ? ep.dependencies.join(', ') : '-'}}</td>
            <td class="p-3 text-fuchsia-400 font-mono text-[11px]">${{ep.response_model || '-'}}</td>
            <td class="p-3 text-right">
              <button onclick="focusEndpointInGraph('${{ep.id}}')" class="px-2.5 py-1 bg-slate-700 hover:bg-indigo-600 text-slate-200 hover:text-white rounded text-[11px] transition">
                View in Graph
              </button>
            </td>
          </tr>
        `;
      }}).join('');
    }}

    function filterRouteTable(q) {{
      const query = q.toLowerCase();
      const rows = document.querySelectorAll('#routes-table-body tr');
      rows.forEach(r => {{
        const text = r.innerText.toLowerCase();
        r.style.display = text.includes(query) ? '' : 'none';
      }});
    }}

    function focusEndpointInGraph(epId) {{
      switchTab('graph');
      const node = nodesDataSet.get(epId);
      if (node) {{
        network.focus(epId, {{ scale: 1.3, animation: true }});
        showInspector(node);
      }}
    }}

    function populateDepsGrid() {{
      const grid = document.getElementById('deps-grid');
      const deps = ARCH_DATA.dependencies || [];

      grid.innerHTML = deps.map(d => `
        <div class="bg-slate-800/80 border border-slate-700/80 rounded-xl p-4 shadow-lg hover:border-sky-500/50 transition">
          <div class="flex items-center justify-between mb-2">
            <h4 class="font-bold text-sky-300 font-mono text-sm">${{d.name}}</h4>
            <span class="text-[10px] bg-sky-500/20 text-sky-300 px-2 py-0.5 rounded border border-sky-500/30">${{d.kind}}</span>
          </div>
          <p class="text-slate-400 text-xs font-mono mb-2">${{d.module}}:${{d.line_number}}</p>
          ${{d.docstring ? `<p class="text-slate-300 text-xs bg-slate-900/60 p-2 rounded mb-3 font-mono">${{d.docstring}}</p>` : ''}}
          
          ${{d.sub_dependencies && d.sub_dependencies.length ? `
            <div class="mt-2 text-xs">
              <span class="text-slate-500 font-semibold block mb-1">Sub-Dependencies:</span>
              <div class="flex flex-wrap gap-1">
                ${{d.sub_dependencies.map(s => `<span class="bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded text-[10px] font-mono">${{s}}</span>`).join('')}}
              </div>
            </div>
          ` : ''}}
        </div>
      `).join('');
    }}

    function populateSchemasGrid() {{
      const grid = document.getElementById('schemas-grid');
      const schemas = ARCH_DATA.schemas || [];

      grid.innerHTML = schemas.map(s => `
        <div class="bg-slate-800/80 border border-slate-700/80 rounded-xl p-4 shadow-lg hover:border-fuchsia-500/50 transition">
          <div class="flex items-center justify-between mb-2">
            <h4 class="font-bold text-fuchsia-300 font-mono text-sm">${{s.name}}</h4>
            <span class="text-[10px] bg-fuchsia-500/20 text-fuchsia-300 px-2 py-0.5 rounded border border-fuchsia-500/30">${{s.base_classes ? s.base_classes[0] || 'BaseModel' : 'BaseModel'}}</span>
          </div>
          <p class="text-slate-400 text-xs font-mono mb-3">${{s.module}}:${{s.line_number}}</p>
          
          <div class="space-y-1.5 text-xs">
            ${{s.fields && s.fields.map(f => `
              <div class="bg-slate-900/50 p-1.5 rounded flex items-center justify-between font-mono text-[11px]">
                <span class="text-slate-200 font-semibold">${{f.name}}</span>
                <span class="text-fuchsia-400">${{f.type_annotation}}</span>
              </div>
            `).join('')}}
          </div>
        </div>
      `).join('');
    }}

    // Export Utilities
    function exportPNG() {{
      const canvas = document.querySelector('#network-container canvas');
      if (!canvas) return;
      const link = document.createElement('a');
      link.download = `${{ARCH_DATA.project_name}}-architecture.png`;
      link.href = canvas.toDataURL('image/png');
      link.click();
    }}

    function exportJSON() {{
      const blob = new Blob([JSON.stringify(ARCH_DATA, null, 2)], {{ type: 'application/json' }});
      const link = document.createElement('a');
      link.download = `${{ARCH_DATA.project_name}}-architecture.json`;
      link.href = URL.createObjectURL(blob);
      link.click();
    }}

    function exportMermaid() {{
      let mermaid = "graph TD\\n";
      ARCH_DATA.edges.forEach(e => {{
        const arrow = e.dashes ? "-.->" : "-->";
        const lbl = e.label ? `|${{e.label}}|` : "";
        mermaid += `  ${{e.from}} ${{arrow}}${{lbl}} ${{e.to}}\\n`;
      }});
      navigator.clipboard.writeText(mermaid).then(() => {{
        alert("Mermaid diagram copied to clipboard!");
      }});
    }}
  </script>
</body>
</html>"""
