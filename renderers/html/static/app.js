const ARCH_DATA = JSON.parse(document.getElementById("architecture-data").textContent);

document.addEventListener('click', event => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  const action = window[target.dataset.action];
  if (typeof action !== 'function') return;
  if (Object.prototype.hasOwnProperty.call(target.dataset, 'arg')) action(target.dataset.arg);
  else action();
});

document.addEventListener('input', event => {
  const actionName = event.target.dataset.inputAction;
  const action = actionName && window[actionName];
  if (typeof action === 'function') action(event.target.value);
});

let network = null;
let nodesDataSet = null;
let edgesDataSet = null;
let currentLayout = 'force'; // 'force', 'hierarchical_lr', 'hierarchical_ud'
let physicsEnabled = true;
let currentSpringLength = 240;
let selectedNodeId = null;

let activeFilters = {
  endpoint: true,
  router: true,
  dependency: true,
  schema: true,
  app: true,
};

let activeMethods = {
  GET: true,
  POST: true,
  PUT: true,
  DELETE: true,
  PATCH: true,
  OPTIONS: true,
  HEAD: true,
};

document.addEventListener('DOMContentLoaded', () => {
  lucide.createIcons();
  initNetwork();
  populateRouteTable();
  populateDepsGrid();
  populateSchemasGrid();
  populateGitDiff();

  window.addEventListener('resize', () => {
    if (network) network.setSize('100%', '100%');
  });

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeInspector();
  });
});

function initNetwork() {
  const container = document.getElementById('network-container');

  nodesDataSet = new vis.DataSet(ARCH_DATA.nodes);
  edgesDataSet = new vis.DataSet(ARCH_DATA.edges);

  const data = {
    nodes: nodesDataSet,
    edges: edgesDataSet
  };

  const options = {
    autoResize: true,
    nodes: {
      font: {
        color: '#f8fafc',
        size: 12,
        face: 'Plus Jakarta Sans, sans-serif',
        multi: 'html',
      },
      shapeProperties: {
        borderRadius: 8
      },
      margin: {
        top: 10,
        right: 14,
        bottom: 10,
        left: 14
      },
      borderWidth: 2,
      shadow: {
        enabled: true,
        color: 'rgba(0,0,0,0.5)',
        size: 8,
        x: 2,
        y: 3
      }
    },
    edges: {
      font: {
        color: '#94a3b8',
        size: 10,
        face: 'JetBrains Mono, monospace',
        align: 'top'
      },
      arrows: {
        to: { enabled: true, scaleFactor: 0.8 }
      },
      smooth: {
        type: 'cubicBezier',
        roundness: 0.35
      },
      width: 1.5,
      selectionWidth: 3
    },
    physics: {
      enabled: true,
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {
        gravitationalConstant: -180,
        centralGravity: 0.005,
        springLength: currentSpringLength,
        springConstant: 0.05,
        damping: 0.85,
        avoidOverlap: 0.9
      },
      stabilization: {
        iterations: 200,
        updateInterval: 25
      }
    },
    interaction: {
      hover: true,
      tooltipDelay: 100,
      navigationButtons: false,
      keyboard: false,
      zoomView: true,
      dragView: true
    }
  };

  network = new vis.Network(container, data, options);

  network.on('click', (params) => {
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0];
      selectedNodeId = nodeId;
      const node = nodesDataSet.get(nodeId);
      highlightNodeNeighborhood(nodeId);
      showInspector(node);
    } else {
      selectedNodeId = null;
      resetNodeHighlighting();
      closeInspector();
    }
  });

  network.on('hoverNode', (params) => {
    if (!selectedNodeId) {
      highlightNodeNeighborhood(params.node);
    }
  });

  network.on('blurNode', () => {
    if (!selectedNodeId) {
      resetNodeHighlighting();
    }
  });

  network.on('doubleClick', (params) => {
    if (params.nodes.length > 0) {
      network.focus(params.nodes[0], {
        scale: 1.25,
        animation: { duration: 400, easingFunction: 'easeInOutQuad' }
      });
    }
  });

  network.once('stabilizationIterationsDone', () => {
    fitView();
  });
}

function highlightNodeNeighborhood(nodeId) {
  const connectedNodes = new Set(network.getConnectedNodes(nodeId));
  connectedNodes.add(nodeId);
  const connectedEdges = new Set(network.getConnectedEdges(nodeId));

  const allNodes = nodesDataSet.get();
  const updatedNodes = allNodes.map(n => {
    const isConnected = connectedNodes.has(n.id);
    return {
      id: n.id,
      opacity: isConnected ? 1.0 : 0.15,
    };
  });
  nodesDataSet.update(updatedNodes);

  const allEdges = edgesDataSet.get();
  const updatedEdges = allEdges.map(e => {
    const isConnected = connectedEdges.has(e.id);
    return {
      id: e.id,
      opacity: isConnected ? 1.0 : 0.1,
      width: isConnected ? 2.5 : 1
    };
  });
  edgesDataSet.update(updatedEdges);
}

function resetNodeHighlighting() {
  const allNodes = nodesDataSet.get();
  nodesDataSet.update(allNodes.map(n => ({ id: n.id, opacity: 1.0 })));

  const allEdges = edgesDataSet.get();
  edgesDataSet.update(allEdges.map(e => ({ id: e.id, opacity: 1.0, width: 1.5 })));
}

function switchTab(tabId) {
  document.querySelectorAll('.tab-view').forEach(v => v.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.remove('bg-indigo-600', 'text-white', 'shadow-sm');
    b.classList.add('text-slate-400');
  });

  document.getElementById(`view-${tabId}`).classList.remove('hidden');
  const activeBtn = document.getElementById(`tab-btn-${tabId}`);
  activeBtn.classList.add('bg-indigo-600', 'text-white', 'shadow-sm');
  activeBtn.classList.remove('text-slate-400');

  if (tabId === 'graph' && network) {
    setTimeout(() => {
      network.setSize('100%', '100%');
      network.redraw();
      fitView();
    }, 50);
  } else if (tabId === 'gitdiff') {
    lucide.createIcons();
  }
}

function setLayout(layoutType) {
  currentLayout = layoutType;
  document.querySelectorAll('.layout-opt-btn').forEach(b => {
    b.classList.remove('bg-indigo-600', 'text-white');
    b.classList.add('text-slate-400');
  });
  const btn = document.getElementById(`layout-btn-${layoutType}`);
  btn.classList.add('bg-indigo-600', 'text-white');
  btn.classList.remove('text-slate-400');

  if (layoutType === 'force') {
    network.setOptions({
      layout: { hierarchical: { enabled: false } },
      physics: {
        enabled: physicsEnabled,
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: -180,
          centralGravity: 0.005,
          springLength: currentSpringLength,
          springConstant: 0.05,
          damping: 0.85,
          avoidOverlap: 0.9
        }
      }
    });
  } else if (layoutType === 'hierarchical_lr') {
    network.setOptions({
      layout: {
        hierarchical: {
          enabled: true,
          direction: 'LR',
          sortMethod: 'directed',
          levelSeparation: 300,
          nodeSpacing: 180,
          treeSpacing: 260,
          blockShifting: true,
          edgeMinimization: true,
          parentCentralization: true
        }
      },
      physics: { enabled: false }
    });
  } else if (layoutType === 'hierarchical_ud') {
    network.setOptions({
      layout: {
        hierarchical: {
          enabled: true,
          direction: 'UD',
          sortMethod: 'directed',
          levelSeparation: 220,
          nodeSpacing: 200,
          treeSpacing: 260,
          blockShifting: true,
          edgeMinimization: true,
          parentCentralization: true
        }
      },
      physics: { enabled: false }
    });
  }

  setTimeout(() => fitView(), 200);
}

function updateSpacing(val) {
  currentSpringLength = parseInt(val, 10);
  document.getElementById('spacing-val').innerText = `${currentSpringLength}px`;
  if (currentLayout === 'force') {
    network.setOptions({
      physics: {
        forceAtlas2Based: {
          springLength: currentSpringLength
        }
      }
    });
  }
}

function togglePhysics() {
  physicsEnabled = !physicsEnabled;
  const lbl = document.getElementById('bottom-physics-label');
  lbl.innerText = `Physics: ${physicsEnabled ? 'On' : 'Off'}`;
  network.setOptions({ physics: { enabled: physicsEnabled } });
}

function fitView() {
  if (network) {
    network.fit({
      animation: { duration: 500, easingFunction: 'easeInOutQuad' }
    });
  }
}

function zoomIn() {
  const scale = network.getScale() * 1.35;
  network.moveTo({ scale: scale, animation: { duration: 250 } });
}

function zoomOut() {
  const scale = network.getScale() * 0.7;
  network.moveTo({ scale: scale, animation: { duration: 250 } });
}

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen();
  } else if (document.exitFullscreen) {
    document.exitFullscreen();
  }
}

function toggleDock() {
  const body = document.getElementById('dock-body');
  const openBtn = document.getElementById('dock-open-btn');
  const minimizeBtn = document.getElementById('dock-minimize-btn');
  const isHidden = body.classList.contains('hidden');

  if (isHidden) {
    body.classList.remove('hidden');
    openBtn.classList.add('hidden');
    minimizeBtn.classList.remove('hidden');
  } else {
    body.classList.add('hidden');
    openBtn.classList.remove('hidden');
    minimizeBtn.classList.add('hidden');
  }
}

function toggleFilterType(category) {
  activeFilters[category] = !activeFilters[category];
  const btn = document.getElementById(`filter-btn-${category}`);
  btn.classList.toggle('opacity-30', !activeFilters[category]);
  applyFilters();
}

function toggleMethodFilter(method) {
  activeMethods[method] = !activeMethods[method];
  const btn = document.getElementById(`method-btn-${method}`);
  if (btn) btn.classList.toggle('opacity-30', !activeMethods[method]);
  applyFilters();
}

function resetFilters() {
  Object.keys(activeFilters).forEach(k => {
    activeFilters[k] = true;
    const btn = document.getElementById(`filter-btn-${k}`);
    if (btn) btn.classList.remove('opacity-30');
  });
  Object.keys(activeMethods).forEach(m => {
    activeMethods[m] = true;
    const btn = document.getElementById(`method-btn-${m}`);
    if (btn) btn.classList.remove('opacity-30');
  });
  applyFilters();
}

function applyFilters() {
  const filteredNodes = ARCH_DATA.nodes.filter(n => {
    if (activeFilters[n.category] === false) return false;
    if (n.category === 'endpoint') {
      const m = (n.metadata && n.metadata.http_method) || 'GET';
      if (activeMethods[m] === false) return false;
    }
    return true;
  });

  const activeNodeIds = new Set(filteredNodes.map(n => n.id));
  const filteredEdges = ARCH_DATA.edges.filter(e => activeNodeIds.has(e.from) && activeNodeIds.has(e.to));

  nodesDataSet.clear();
  nodesDataSet.add(filteredNodes);
  edgesDataSet.clear();
  edgesDataSet.add(filteredEdges);
}

function handleSearch(query) {
  const q = query.trim().toLowerCase();
  const clearBtn = document.getElementById('clear-search-btn');
  clearBtn.classList.toggle('hidden', !q);

  if (!q) {
    applyFilters();
    return;
  }

  const matchedNodes = ARCH_DATA.nodes.filter(n => {
    const lbl = (n.label || '').toLowerCase();
    const meta = JSON.stringify(n.metadata || {}).toLowerCase();
    return lbl.includes(q) || meta.includes(q);
  });

  const matchedIds = new Set(matchedNodes.map(n => n.id));

  ARCH_DATA.edges.forEach(e => {
    if (matchedIds.has(e.from)) matchedIds.add(e.to);
    if (matchedIds.has(e.to)) matchedIds.add(e.from);
  });

  const nodesToShow = ARCH_DATA.nodes.filter(n => matchedIds.has(n.id));
  const edgesToShow = ARCH_DATA.edges.filter(e => matchedIds.has(e.from) && matchedIds.has(e.to));

  nodesDataSet.clear();
  nodesDataSet.add(nodesToShow);
  edgesDataSet.clear();
  edgesDataSet.add(edgesToShow);

  if (matchedNodes.length > 0) {
    network.focus(matchedNodes[0].id, { scale: 1.15, animation: { duration: 350 } });
  }
}

function clearSearch() {
  document.getElementById('graph-search').value = '';
  document.getElementById('clear-search-btn').classList.add('hidden');
  applyFilters();
}

function showInspector(node) {
  const drawer = document.getElementById('inspector-drawer');
  const badge = document.getElementById('inspector-badge');
  const title = document.getElementById('inspector-title');
  const content = document.getElementById('inspector-content');

  badge.innerText = (node.category || 'node').toUpperCase();
  title.innerText = node.label.split('\n')[0];

  let html = '';
  const meta = node.metadata || {};

  if (node.category === 'endpoint') {
    const methodColors = {
      GET: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40',
      POST: 'bg-blue-500/20 text-blue-400 border-blue-500/40',
      PUT: 'bg-amber-500/20 text-amber-400 border-amber-500/40',
      DELETE: 'bg-rose-500/20 text-rose-400 border-rose-500/40',
      PATCH: 'bg-teal-500/20 text-teal-400 border-teal-500/40',
    };
    const mCls = methodColors[meta.http_method] || 'bg-slate-700 text-slate-200 border-slate-600';

    html += `
      <div class="bg-slate-900/90 p-4 rounded-xl border border-slate-700/80 space-y-2.5 shadow-inner">
        <div class="flex items-center space-x-2">
          <span class="px-2.5 py-0.5 rounded-lg font-mono font-bold text-xs border ${mCls}">${meta.http_method}</span>
          <span class="font-mono text-white text-xs font-semibold break-all">${meta.full_path}</span>
        </div>
        <div class="text-slate-400 text-xs font-mono">Handler: <span class="text-indigo-300 font-semibold">${meta.function_name}()</span></div>
        <div class="text-slate-500 text-[11px] font-mono break-all">${meta.file_path}:${meta.line_number}</div>
      </div>
    `;

    if (meta.docstring) {
      html += `
        <div>
          <div class="text-slate-400 font-semibold mb-1 text-[11px] uppercase tracking-wider">Docstring</div>
          <div class="bg-slate-900/60 p-3 rounded-xl border border-slate-800 text-slate-300 font-mono text-[11px] whitespace-pre-wrap">${meta.docstring}</div>
        </div>
      `;
    }

    if (meta.parameters && meta.parameters.length > 0) {
      html += `
        <div>
          <div class="text-slate-400 font-semibold mb-1.5 text-[11px] uppercase tracking-wider">Parameters (${meta.parameters.length})</div>
          <div class="space-y-1.5">
            ${meta.parameters.map(p => `
              <div class="bg-slate-900/60 p-2.5 rounded-xl border border-slate-800 flex flex-col">
                <div class="flex items-center justify-between">
                  <span class="font-mono text-indigo-300 font-semibold">${p.name}</span>
                  <span class="text-[10px] bg-slate-800 px-2 py-0.5 rounded text-slate-400 font-mono">${p.kind}</span>
                </div>
                ${p.type_annotation ? `<span class="text-slate-400 text-[11px] font-mono mt-0.5">Type: ${p.type_annotation}</span>` : ''}
                ${p.default_value ? `<span class="text-slate-500 text-[10px] font-mono mt-0.5">Default: ${p.default_value}</span>` : ''}
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }

    if (meta.dependencies && meta.dependencies.length > 0) {
      html += `
        <div>
          <div class="text-slate-400 font-semibold mb-1.5 text-[11px] uppercase tracking-wider">Injected Dependencies</div>
          <div class="flex flex-wrap gap-1.5">
            ${meta.dependencies.map(d => `<span class="bg-sky-500/20 text-sky-300 px-2.5 py-1 rounded-lg text-[11px] border border-sky-500/30 font-mono font-medium">${d}</span>`).join('')}
          </div>
        </div>
      `;
    }

    if (meta.response_model) {
      html += `
        <div>
          <div class="text-slate-400 font-semibold mb-1.5 text-[11px] uppercase tracking-wider">Response Model</div>
          <div class="bg-fuchsia-500/20 text-fuchsia-300 px-3 py-1.5 rounded-xl border border-fuchsia-500/30 font-mono font-semibold">${meta.response_model}</div>
        </div>
      `;
    }
  } else if (node.category === 'router') {
    html += `
      <div class="bg-slate-900/90 p-4 rounded-xl border border-slate-700/80 space-y-2 shadow-inner">
        <div class="text-purple-300 font-bold text-sm">Router: ${meta.var_name}</div>
        <div class="text-slate-400 text-xs">Prefix: <code class="text-white bg-slate-800 px-1.5 py-0.5 rounded font-mono">${meta.prefix || '/'}</code></div>
        <div class="text-slate-400 text-xs">Tags: ${meta.tags && meta.tags.length ? meta.tags.join(', ') : 'None'}</div>
        <div class="text-slate-500 text-[11px] font-mono break-all">${meta.file_path}:${meta.line_number}</div>
      </div>
    `;
  } else if (node.category === 'dependency') {
    html += `
      <div class="bg-slate-900/90 p-4 rounded-xl border border-slate-700/80 space-y-2 shadow-inner">
        <div class="text-sky-300 font-bold text-sm">Dependency: ${meta.name}</div>
        <div class="text-slate-400 text-xs">Kind: <span class="text-slate-200">${meta.kind}</span></div>
        <div class="text-slate-500 text-[11px] font-mono break-all">${meta.file_path}:${meta.line_number}</div>
      </div>
    `;
    if (meta.docstring) {
      html += `
        <div>
          <div class="text-slate-400 font-semibold mb-1 text-[11px] uppercase tracking-wider">Docstring</div>
          <div class="bg-slate-900/60 p-3 rounded-xl border border-slate-800 text-slate-300 font-mono text-[11px]">${meta.docstring}</div>
        </div>
      `;
    }
    if (meta.sub_dependencies && meta.sub_dependencies.length > 0) {
      html += `
        <div>
          <div class="text-slate-400 font-semibold mb-1.5 text-[11px] uppercase tracking-wider">Sub-Dependencies</div>
          <div class="flex flex-wrap gap-1.5">
            ${meta.sub_dependencies.map(d => `<span class="bg-sky-500/20 text-sky-300 px-2.5 py-1 rounded-lg text-[11px] border border-sky-500/30 font-mono">${d}</span>`).join('')}
          </div>
        </div>
      `;
    }
  } else if (node.category === 'schema') {
    html += `
      <div class="bg-slate-900/90 p-4 rounded-xl border border-slate-700/80 space-y-2 shadow-inner">
        <div class="text-fuchsia-300 font-bold text-sm">Model: ${meta.name}</div>
        <div class="text-slate-400 text-xs">Bases: ${meta.base_classes ? meta.base_classes.join(', ') : 'BaseModel'}</div>
        <div class="text-slate-500 text-[11px] font-mono break-all">${meta.file_path}:${meta.line_number}</div>
      </div>
    `;
    if (meta.fields && meta.fields.length > 0) {
      html += `
        <div>
          <div class="text-slate-400 font-semibold mb-1.5 text-[11px] uppercase tracking-wider">Model Fields (${meta.fields.length})</div>
          <div class="space-y-1.5">
            ${meta.fields.map(f => `
              <div class="bg-slate-900/60 p-2 rounded-lg border border-slate-800 flex items-center justify-between font-mono">
                <span class="text-fuchsia-300 font-semibold">${f.name}</span>
                <span class="text-slate-400 text-[11px]">${f.type_annotation}</span>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }
  }

  if (meta.analysis) {
    const metrics = meta.analysis;
    const metricItems = [
      ['Token cost', metrics.token_cost],
      ['PageRank', metrics.pagerank],
      ['Hub', metrics.hub_score],
      ['Authority', metrics.authority_score],
      ['Degree', metrics.degree_centrality],
      ['Betweenness', metrics.betweenness_centrality],
      ['Weighted cost', metrics.weighted_centrality_cost],
      ['2-hop tokens', metrics.hop_2_token_cost],
      ['3-hop tokens', metrics.hop_3_token_cost],
    ];
    html += `
      <div>
        <div class="text-slate-400 font-semibold mb-1.5 text-[11px] uppercase tracking-wider">Agent Exploration Metrics</div>
        <div class="grid grid-cols-2 gap-1.5">
          ${metricItems.map(([label, value]) => `
            <div class="bg-slate-900/60 p-2 rounded-lg border border-slate-800">
              <div class="text-[10px] text-slate-500">${label}</div>
              <div class="font-mono text-xs text-indigo-300">${typeof value === 'number' && !Number.isInteger(value) ? value.toFixed(6) : value}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  content.innerHTML = html;
  drawer.classList.remove('translate-x-full');
  lucide.createIcons();
}

function closeInspector() {
  document.getElementById('inspector-drawer').classList.add('translate-x-full');
  selectedNodeId = null;
  resetNodeHighlighting();
}

function populateRouteTable() {
  const tbody = document.getElementById('routes-table-body');
  const endpoints = ARCH_DATA.endpoints || [];

  const methodColors = {
    GET: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    POST: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    PUT: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    DELETE: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
    PATCH: 'bg-teal-500/20 text-teal-400 border-teal-500/30',
  };

  tbody.innerHTML = endpoints.map(ep => {
    const mCls = methodColors[ep.http_method] || 'bg-slate-700 text-slate-300 border-slate-600';
    return `
      <tr class="hover:bg-slate-800/60 transition">
        <td class="p-3.5">
          <span class="px-2.5 py-0.5 rounded font-mono font-bold text-[11px] border ${mCls}">${ep.http_method}</span>
        </td>
        <td class="p-3.5 font-mono font-semibold text-white">${ep.full_path || ep.path}</td>
        <td class="p-3.5 font-mono text-indigo-300">${ep.function_name}()</td>
        <td class="p-3.5 text-slate-400">${ep.tags && ep.tags.length ? ep.tags.join(', ') : '-'}</td>
        <td class="p-3.5 text-sky-400 font-mono text-[11px]">${ep.dependencies && ep.dependencies.length ? ep.dependencies.join(', ') : '-'}</td>
        <td class="p-3.5 text-fuchsia-400 font-mono text-[11px]">${ep.response_model || '-'}</td>
        <td class="p-3.5 text-right">
          <button data-action="focusEndpointInGraph" data-arg="${ep.id}" class="px-3 py-1 bg-slate-800 hover:bg-indigo-600 text-slate-300 hover:text-white rounded-lg text-xs font-medium transition border border-slate-700">
            View in Graph
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

function filterRouteTable(q) {
  const query = q.toLowerCase();
  const rows = document.querySelectorAll('#routes-table-body tr');
  rows.forEach(r => {
    const text = r.innerText.toLowerCase();
    r.style.display = text.includes(query) ? '' : 'none';
  });
}

function focusEndpointInGraph(epId) {
  switchTab('graph');
  const node = nodesDataSet.get(epId);
  if (node) {
    selectedNodeId = epId;
    network.focus(epId, { scale: 1.3, animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
    highlightNodeNeighborhood(epId);
    showInspector(node);
  }
}

function populateDepsGrid() {
  const grid = document.getElementById('deps-grid');
  const deps = ARCH_DATA.dependencies || [];

  grid.innerHTML = deps.map(d => `
    <div class="glass-panel rounded-2xl p-5 shadow-xl hover:border-sky-500/60 transition">
      <div class="flex items-center justify-between mb-2">
        <h4 class="font-bold text-sky-300 font-mono text-sm">${d.name}</h4>
        <span class="text-[10px] bg-sky-500/20 text-sky-300 px-2 py-0.5 rounded border border-sky-500/30">${d.kind}</span>
      </div>
      <p class="text-slate-400 text-xs font-mono mb-2.5 truncate">${d.module}:${d.line_number}</p>
      ${d.docstring ? `<p class="text-slate-300 text-xs bg-slate-900/80 p-2.5 rounded-xl mb-3 font-mono border border-slate-800">${d.docstring}</p>` : ''}

      ${d.sub_dependencies && d.sub_dependencies.length ? `
        <div class="mt-2 text-xs">
          <span class="text-slate-500 font-semibold block mb-1 text-[11px] uppercase tracking-wider">Sub-Dependencies:</span>
          <div class="flex flex-wrap gap-1.5">
            ${d.sub_dependencies.map(s => `<span class="bg-slate-800 text-slate-300 px-2 py-0.5 rounded-lg text-[10px] font-mono border border-slate-700">${s}</span>`).join('')}
          </div>
        </div>
      ` : ''}
    </div>
  `).join('');
}

function populateSchemasGrid() {
  const grid = document.getElementById('schemas-grid');
  const schemas = ARCH_DATA.schemas || [];

  grid.innerHTML = schemas.map(s => `
    <div class="glass-panel rounded-2xl p-5 shadow-xl hover:border-fuchsia-500/60 transition">
      <div class="flex items-center justify-between mb-2">
        <h4 class="font-bold text-fuchsia-300 font-mono text-sm">${s.name}</h4>
        <span class="text-[10px] bg-fuchsia-500/20 text-fuchsia-300 px-2 py-0.5 rounded border border-fuchsia-500/30">${s.base_classes ? s.base_classes[0] || 'BaseModel' : 'BaseModel'}</span>
      </div>
      <p class="text-slate-400 text-xs font-mono mb-3 truncate">${s.module}:${s.line_number}</p>

      <div class="space-y-1.5 text-xs">
        ${s.fields && s.fields.map(f => `
          <div class="bg-slate-900/70 p-2 rounded-lg flex items-center justify-between font-mono text-[11px] border border-slate-800">
            <span class="text-slate-200 font-semibold">${f.name}</span>
            <span class="text-fuchsia-400">${f.type_annotation}</span>
          </div>
        `).join('')}
      </div>
    </div>
  `).join('');
}

function exportPNG() {
  const canvas = document.querySelector('#network-container canvas');
  if (!canvas) return;
  const link = document.createElement('a');
  link.download = `${ARCH_DATA.project_name}-architecture.png`;
  link.href = canvas.toDataURL('image/png');
  link.click();
}

function exportJSON() {
  const blob = new Blob([JSON.stringify(ARCH_DATA, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.download = `${ARCH_DATA.project_name}-architecture.json`;
  link.href = URL.createObjectURL(blob);
  link.click();
}

function exportMermaid() {
  let mermaid = "graph TD\n";
  ARCH_DATA.edges.forEach(e => {
    const arrow = e.dashes ? "-.->" : "-->";
    const lbl = e.label ? `|${e.label}|` : "";
    mermaid += `  ${e.from} ${arrow}${lbl} ${e.to}\n`;
  });
  navigator.clipboard.writeText(mermaid).then(() => {
    alert("Mermaid diagram copied to clipboard!");
  });
}

let currentGitStatusFilter = 'ALL';
let currentGitSearchQuery = '';

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function populateGitDiff() {
  const gd = ARCH_DATA.git_diff;
  const navBadge = document.getElementById('nav-git-badge');
  const heroContainer = document.getElementById('git-diff-hero');
  const impactContainer = document.getElementById('git-arch-impact-container');
  const mainLayout = document.getElementById('git-diff-main-layout');
  const emptyState = document.getElementById('git-diff-empty-state');

  if (!gd || !gd.is_git_repo) {
    if (mainLayout) mainLayout.classList.add('hidden');
    if (impactContainer) impactContainer.classList.add('hidden');
    if (heroContainer) heroContainer.classList.add('hidden');
    if (emptyState) {
      emptyState.classList.remove('hidden');
      const title = document.getElementById('git-empty-title');
      const msg = document.getElementById('git-empty-msg');
      if (title) title.innerText = 'Not a Git Repository';
      if (msg) msg.innerText = (gd && gd.error_message) || 'Project directory is not tracked by Git.';
    }
    return;
  }

  if (navBadge) {
    if (gd.total_files > 0) {
      navBadge.innerText = `${gd.total_files} ${gd.total_files === 1 ? 'file' : 'files'}`;
      navBadge.classList.remove('hidden');
    } else {
      navBadge.classList.add('hidden');
    }
  }

  let modeBadgeCls = 'bg-slate-800 text-slate-300 border-slate-700';
  let modeIcon = 'git-commit';
  let modePillText = 'Git Diff';

  if (gd.comparison_mode === 'working_tree_vs_head') {
    modeBadgeCls = 'bg-amber-500/20 text-amber-300 border-amber-500/40';
    modeIcon = 'zap';
    modePillText = 'Uncommitted Changes (Working Tree vs Latest Commit)';
  } else if (gd.comparison_mode === 'last_two_commits') {
    modeBadgeCls = 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40';
    modeIcon = 'git-compare';
    modePillText = 'Clean Working Tree — Comparing Last 2 Commits';
  } else if (gd.comparison_mode === 'single_commit') {
    modeBadgeCls = 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40';
    modeIcon = 'git-branch';
    modePillText = 'Clean Working Tree — Initial Commit';
  }

  const baseCommit = gd.base_commit;
  const targetCommit = gd.target_commit;
  const netLines = (gd.total_additions || 0) - (gd.total_deletions || 0);
  const netSign = netLines >= 0 ? `+${netLines}` : `${netLines}`;
  const netCls = netLines >= 0 ? 'text-emerald-400' : 'text-rose-400';

  let comparisonCardsHtml = '';
  if (gd.comparison_mode === 'working_tree_vs_head') {
    comparisonCardsHtml = `
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-center">
        <!-- Base: HEAD -->
        <div class="bg-slate-900/80 p-4 rounded-xl border border-slate-800 flex items-start space-x-3">
          <div class="p-2 rounded-lg bg-slate-800 text-slate-300 border border-slate-700 mt-0.5 shrink-0">
            <i data-lucide="git-commit" class="w-4 h-4 text-indigo-400"></i>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center space-x-2">
              <span class="text-[10px] font-mono uppercase tracking-wider text-slate-400 font-bold">Base: HEAD Commit</span>
              ${baseCommit ? `<span class="px-1.5 py-0.2 rounded font-mono text-[10px] bg-slate-800 text-indigo-300 border border-slate-700 font-bold">${escapeHtml(baseCommit.short_hash)}</span>` : ''}
            </div>
            <div class="text-xs text-white font-semibold truncate mt-0.5">${baseCommit ? escapeHtml(baseCommit.message) : 'Initial Commit'}</div>
            <div class="text-[11px] text-slate-400 font-mono mt-0.5 truncate">${baseCommit ? `${escapeHtml(baseCommit.author)} • ${escapeHtml(baseCommit.date)}` : ''}</div>
          </div>
        </div>

        <!-- Target: Working Tree -->
        <div class="bg-amber-950/20 p-4 rounded-xl border border-amber-500/30 flex items-start space-x-3">
          <div class="p-2 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/30 mt-0.5 shrink-0">
            <i data-lucide="folder-git-2" class="w-4 h-4"></i>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center space-x-2">
              <span class="text-[10px] font-mono uppercase tracking-wider text-amber-400 font-bold">Target: Working Directory</span>
              <span class="px-1.5 py-0.2 rounded font-mono text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold">Uncommitted</span>
            </div>
            <div class="text-xs text-white font-semibold mt-0.5">Staged, Unstaged & Untracked Files</div>
            <div class="text-[11px] text-slate-400 font-mono mt-0.5">Current local modifications on filesystem</div>
          </div>
        </div>
      </div>
    `;
  } else if (gd.comparison_mode === 'last_two_commits') {
    comparisonCardsHtml = `
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-center">
        <!-- Base: HEAD~1 -->
        <div class="bg-slate-900/80 p-4 rounded-xl border border-slate-800 flex items-start space-x-3">
          <div class="p-2 rounded-lg bg-slate-800 text-slate-300 border border-slate-700 mt-0.5 shrink-0">
            <i data-lucide="git-commit" class="w-4 h-4 text-slate-400"></i>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center space-x-2">
              <span class="text-[10px] font-mono uppercase tracking-wider text-slate-400 font-bold">Base: HEAD~1</span>
              ${baseCommit ? `<span class="px-1.5 py-0.2 rounded font-mono text-[10px] bg-slate-800 text-slate-300 border border-slate-700 font-bold">${escapeHtml(baseCommit.short_hash)}</span>` : ''}
            </div>
            <div class="text-xs text-white font-semibold truncate mt-0.5">${baseCommit ? escapeHtml(baseCommit.message) : 'Parent Commit'}</div>
            <div class="text-[11px] text-slate-400 font-mono mt-0.5 truncate">${baseCommit ? `${escapeHtml(baseCommit.author)} • ${escapeHtml(baseCommit.date)}` : ''}</div>
          </div>
        </div>

        <!-- Target: HEAD -->
        <div class="bg-indigo-950/30 p-4 rounded-xl border border-indigo-500/40 flex items-start space-x-3">
          <div class="p-2 rounded-lg bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 mt-0.5 shrink-0">
            <i data-lucide="git-commit" class="w-4 h-4"></i>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center space-x-2">
              <span class="text-[10px] font-mono uppercase tracking-wider text-indigo-400 font-bold">Target: HEAD (Latest Commit)</span>
              ${targetCommit ? `<span class="px-1.5 py-0.2 rounded font-mono text-[10px] bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-bold">${escapeHtml(targetCommit.short_hash)}</span>` : ''}
            </div>
            <div class="text-xs text-white font-semibold truncate mt-0.5">${targetCommit ? escapeHtml(targetCommit.message) : 'Latest Commit'}</div>
            <div class="text-[11px] text-slate-400 font-mono mt-0.5 truncate">${targetCommit ? `${escapeHtml(targetCommit.author)} • ${escapeHtml(targetCommit.date)}` : ''}</div>
          </div>
        </div>
      </div>
    `;
  } else if (gd.comparison_mode === 'single_commit') {
    comparisonCardsHtml = `
      <div class="bg-slate-900/80 p-4 rounded-xl border border-slate-800 flex items-start space-x-3">
        <div class="p-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 mt-0.5 shrink-0">
          <i data-lucide="git-branch" class="w-4 h-4"></i>
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center space-x-2">
            <span class="text-[10px] font-mono uppercase tracking-wider text-emerald-400 font-bold">Initial Repository Commit</span>
            ${targetCommit ? `<span class="px-1.5 py-0.2 rounded font-mono text-[10px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold">${escapeHtml(targetCommit.short_hash)}</span>` : ''}
          </div>
          <div class="text-xs text-white font-semibold truncate mt-0.5">${targetCommit ? escapeHtml(targetCommit.message) : 'Initial Commit'}</div>
          <div class="text-[11px] text-slate-400 font-mono mt-0.5 truncate">${targetCommit ? `${escapeHtml(targetCommit.author)} • ${escapeHtml(targetCommit.date)}` : ''}</div>
        </div>
      </div>
    `;
  }

  if (heroContainer) {
    heroContainer.innerHTML = `
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-slate-800 pb-4">
        <div class="space-y-1">
          <div class="flex items-center space-x-2.5">
            <span class="px-2.5 py-0.5 rounded-lg text-xs font-mono font-bold border ${modeBadgeCls} flex items-center space-x-1.5">
              <i data-lucide="${modeIcon}" class="w-3.5 h-3.5"></i>
              <span>${modePillText}</span>
            </span>
          </div>
          <p class="text-xs text-slate-400 font-mono">${escapeHtml(gd.mode_description)}</p>
        </div>

        <!-- Quick Metrics Bar -->
        <div class="flex items-center space-x-3 bg-slate-900/90 px-4 py-2 rounded-xl border border-slate-800 text-xs">
          <div>
            <span class="text-slate-500 font-mono">Files:</span>
            <span class="font-bold text-white font-mono ml-1">${gd.total_files}</span>
          </div>
          <div class="h-3 w-px bg-slate-700"></div>
          <div>
            <span class="text-slate-500 font-mono">Additions:</span>
            <span class="font-bold text-emerald-400 font-mono ml-1">+${gd.total_additions}</span>
          </div>
          <div class="h-3 w-px bg-slate-700"></div>
          <div>
            <span class="text-slate-500 font-mono">Deletions:</span>
            <span class="font-bold text-rose-400 font-mono ml-1">-${gd.total_deletions}</span>
          </div>
          <div class="h-3 w-px bg-slate-700"></div>
          <div>
            <span class="text-slate-500 font-mono">Net:</span>
            <span class="font-bold ${netCls} font-mono ml-1">${netSign}</span>
          </div>
        </div>
      </div>

      ${comparisonCardsHtml}
    `;
  }

  const impactedEps = gd.impacted_endpoints || [];
  const impactedRouters = gd.impacted_routers || [];
  const impactedDeps = gd.impacted_dependencies || [];
  const impactedSchemas = gd.impacted_schemas || [];
  const totalImpacted = impactedEps.length + impactedRouters.length + impactedDeps.length + impactedSchemas.length;

  if (totalImpacted > 0 && impactContainer) {
    impactContainer.classList.remove('hidden');
    document.getElementById('impact-count-badge').innerText = `${totalImpacted} Component(s)`;
    const impactGrid = document.getElementById('git-arch-impact-grid');

    const methodColors = {
      GET: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
      POST: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
      PUT: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
      DELETE: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
      PATCH: 'bg-teal-500/20 text-teal-400 border-teal-500/30',
    };

    let impactHtml = '';

    impactedEps.forEach(ep => {
      const mCls = methodColors[ep.method] || 'bg-slate-800 text-slate-300 border-slate-700';
      impactHtml += `
        <div class="bg-slate-900/90 p-3 rounded-xl border border-slate-800 flex flex-col justify-between space-y-2 hover:border-indigo-500/50 transition">
          <div>
            <div class="flex items-center space-x-1.5 mb-1">
              <span class="px-2 py-0.2 rounded font-mono font-bold text-[10px] border ${mCls}">${ep.method}</span>
              <span class="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.2 rounded font-mono">Endpoint</span>
            </div>
            <div class="font-mono text-white text-xs font-semibold truncate" title="${escapeHtml(ep.path)}">${escapeHtml(ep.path)}</div>
            <div class="text-slate-400 text-[11px] font-mono truncate">${escapeHtml(ep.func)}()</div>
          </div>
          <button data-action="focusEndpointInGraph" data-arg="${ep.id}" class="w-full py-1 bg-slate-800 hover:bg-indigo-600 text-slate-300 hover:text-white rounded-lg text-[11px] font-medium transition flex items-center justify-center space-x-1 border border-slate-700">
            <i data-lucide="eye" class="w-3 h-3"></i>
            <span>View in Graph</span>
          </button>
        </div>
      `;
    });

    impactedSchemas.forEach(s => {
      impactHtml += `
        <div class="bg-slate-900/90 p-3 rounded-xl border border-slate-800 flex flex-col justify-between space-y-2 hover:border-fuchsia-500/50 transition">
          <div>
            <div class="flex items-center space-x-1.5 mb-1">
              <span class="px-2 py-0.2 rounded font-mono font-bold text-[10px] bg-fuchsia-500/20 text-fuchsia-300 border border-fuchsia-500/30">Schema</span>
            </div>
            <div class="font-mono text-white text-xs font-semibold truncate">${escapeHtml(s.name)}</div>
            <div class="text-slate-400 text-[11px] font-mono truncate">${escapeHtml(s.file)}</div>
          </div>
          <button data-action="switchTab" data-arg="schemas" class="w-full py-1 bg-slate-800 hover:bg-fuchsia-600 text-slate-300 hover:text-white rounded-lg text-[11px] font-medium transition flex items-center justify-center space-x-1 border border-slate-700">
            <i data-lucide="database" class="w-3 h-3"></i>
            <span>View Models</span>
          </button>
        </div>
      `;
    });

    impactedRouters.forEach(r => {
      impactHtml += `
        <div class="bg-slate-900/90 p-3 rounded-xl border border-slate-800 flex flex-col justify-between space-y-2 hover:border-purple-500/50 transition">
          <div>
            <div class="flex items-center space-x-1.5 mb-1">
              <span class="px-2 py-0.2 rounded font-mono font-bold text-[10px] bg-purple-500/20 text-purple-300 border border-purple-500/30">Router</span>
            </div>
            <div class="font-mono text-white text-xs font-semibold truncate">${escapeHtml(r.var_name)}</div>
            <div class="text-slate-400 text-[11px] font-mono truncate">Prefix: ${escapeHtml(r.prefix || '/')}</div>
          </div>
          <button data-action="switchTab" data-arg="routes" class="w-full py-1 bg-slate-800 hover:bg-purple-600 text-slate-300 hover:text-white rounded-lg text-[11px] font-medium transition flex items-center justify-center space-x-1 border border-slate-700">
            <i data-lucide="list-tree" class="w-3 h-3"></i>
            <span>View Matrix</span>
          </button>
        </div>
      `;
    });

    impactedDeps.forEach(d => {
      impactHtml += `
        <div class="bg-slate-900/90 p-3 rounded-xl border border-slate-800 flex flex-col justify-between space-y-2 hover:border-sky-500/50 transition">
          <div>
            <div class="flex items-center space-x-1.5 mb-1">
              <span class="px-2 py-0.2 rounded font-mono font-bold text-[10px] bg-sky-500/20 text-sky-300 border border-sky-500/30">Dependency</span>
            </div>
            <div class="font-mono text-white text-xs font-semibold truncate">${escapeHtml(d.name)}</div>
            <div class="text-slate-400 text-[11px] font-mono truncate">${escapeHtml(d.kind)}</div>
          </div>
          <button data-action="switchTab" data-arg="deps" class="w-full py-1 bg-slate-800 hover:bg-sky-600 text-slate-300 hover:text-white rounded-lg text-[11px] font-medium transition flex items-center justify-center space-x-1 border border-slate-700">
            <i data-lucide="boxes" class="w-3 h-3"></i>
            <span>View Tree</span>
          </button>
        </div>
      `;
    });

    impactGrid.innerHTML = impactHtml;
  } else if (impactContainer) {
    impactContainer.classList.add('hidden');
  }

  renderGitFilesAndDiffs();
  lucide.createIcons();
}

function renderGitFilesAndDiffs() {
  const gd = ARCH_DATA.git_diff;
  if (!gd || !gd.files) return;

  const fileListContainer = document.getElementById('git-file-list');
  const diffCardsContainer = document.getElementById('git-diff-cards-container');
  const sidebarCount = document.getElementById('git-sidebar-file-count');
  const showingCount = document.getElementById('diff-showing-count');

  const statusBadgeClasses = {
    modified: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
    added: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    deleted: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
    untracked: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
    renamed: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
  };

  const statusLetters = {
    modified: 'M',
    added: 'A',
    deleted: 'D',
    untracked: 'U',
    renamed: 'R',
  };

  const q = (currentGitSearchQuery || '').toLowerCase();
  const filteredFiles = gd.files.filter(f => {
    if (currentGitStatusFilter !== 'ALL' && f.status !== currentGitStatusFilter) return false;
    if (q && !f.file_path.toLowerCase().includes(q)) return false;
    return true;
  });

  if (sidebarCount) sidebarCount.innerText = `${filteredFiles.length} of ${gd.files.length} files`;
  if (showingCount) showingCount.innerText = filteredFiles.length;

  if (fileListContainer) {
    fileListContainer.innerHTML = filteredFiles.map((f, idx) => {
      const sCls = statusBadgeClasses[f.status] || 'bg-slate-800 text-slate-300 border-slate-700';
      const sLetter = statusLetters[f.status] || 'M';
      const fileBase = f.file_path.split('/').pop();
      const fileDir = f.file_path.includes('/') ? f.file_path.substring(0, f.file_path.lastIndexOf('/')) : '';

      return `
        <div data-action="jumpToGitFile" data-arg="${idx}" class="p-2 rounded-xl bg-slate-900/60 hover:bg-slate-800/80 border border-slate-800 hover:border-slate-700 cursor-pointer transition flex items-center justify-between group">
          <div class="flex items-center space-x-2 min-w-0 pr-2">
            <span class="w-5 h-5 flex items-center justify-center rounded font-mono font-bold text-[10px] border ${sCls} shrink-0">${sLetter}</span>
            <div class="min-w-0">
              <div class="font-mono text-xs text-white font-medium truncate group-hover:text-indigo-300">${escapeHtml(fileBase)}</div>
              ${fileDir ? `<div class="font-mono text-[10px] text-slate-500 truncate">${escapeHtml(fileDir)}</div>` : ''}
            </div>
          </div>
          <div class="flex items-center space-x-1 font-mono text-[10px] shrink-0">
            ${f.additions ? `<span class="text-emerald-400">+${f.additions}</span>` : ''}
            ${f.deletions ? `<span class="text-rose-400">-${f.deletions}</span>` : ''}
            ${!f.additions && !f.deletions && f.is_binary ? `<span class="text-slate-500">bin</span>` : ''}
          </div>
        </div>
      `;
    }).join('') || '<div class="p-4 text-center text-xs text-slate-500 font-mono">No matching files</div>';
  }

  if (diffCardsContainer) {
    diffCardsContainer.innerHTML = filteredFiles.map((f, idx) => {
      const sCls = statusBadgeClasses[f.status] || 'bg-slate-800 text-slate-300 border-slate-700';

      let diffContentHtml = '';

      if (f.is_binary) {
        diffContentHtml = `
          <div class="p-6 text-center text-xs text-slate-400 font-mono bg-slate-900/40 rounded-xl border border-slate-800">
            <i data-lucide="file-type" class="w-6 h-6 mx-auto mb-2 text-slate-500"></i>
            <div>Binary file changed (${escapeHtml(f.file_path)})</div>
            <div class="text-[11px] text-slate-500 mt-0.5">Direct visual text diff not displayable for binary formats</div>
          </div>
        `;
      } else if (!f.hunks || f.hunks.length === 0) {
        diffContentHtml = `
          <div class="p-4 text-center text-xs text-slate-400 font-mono bg-slate-900/40 rounded-xl border border-slate-800">
            ${f.status === 'deleted' ? 'File deleted' : 'No diff content available'}
          </div>
        `;
      } else {
        diffContentHtml = `
          <div class="diff-viewer font-mono text-xs overflow-x-auto bg-[#070b14] rounded-xl border border-slate-800 divide-y divide-slate-800/40">
            ${f.hunks.map(hunk => `
              <div class="diff-hunk-header px-4 py-1.5 bg-indigo-950/40 text-indigo-300 text-[11px] font-semibold border-y border-indigo-800/30 flex items-center space-x-2 select-none">
                <i data-lucide="corner-down-right" class="w-3 h-3 text-indigo-400"></i>
                <span>${escapeHtml(hunk.header)}</span>
              </div>
              ${hunk.lines.map(l => {
                let lineCls = 'text-slate-300';
                let bgCls = 'hover:bg-slate-800/30';
                let oldGutterBg = 'bg-slate-900/40 text-slate-600';
                let newGutterBg = 'bg-slate-900/40 text-slate-600';
                let prefix = ' ';

                if (l.type === 'add') {
                  lineCls = 'text-emerald-300 font-medium';
                  bgCls = 'bg-emerald-950/30 border-l-2 border-emerald-500';
                  oldGutterBg = 'bg-emerald-950/50 text-emerald-600/70';
                  newGutterBg = 'bg-emerald-950/50 text-emerald-400 font-bold';
                  prefix = '+';
                } else if (l.type === 'del') {
                  lineCls = 'text-rose-300 font-medium';
                  bgCls = 'bg-rose-950/30 border-l-2 border-rose-500';
                  oldGutterBg = 'bg-rose-950/50 text-rose-400 font-bold';
                  newGutterBg = 'bg-rose-950/50 text-rose-600/70';
                  prefix = '-';
                }

                return `
                  <div class="diff-line flex ${bgCls} text-[11px] leading-relaxed transition">
                    <div class="diff-gutter w-12 text-right pr-2 select-none border-r border-slate-800/80 ${oldGutterBg} shrink-0">${l.old_lineno !== null ? l.old_lineno : ''}</div>
                    <div class="diff-gutter w-12 text-right pr-2 select-none border-r border-slate-800/80 ${newGutterBg} shrink-0">${l.new_lineno !== null ? l.new_lineno : ''}</div>
                    <div class="diff-code px-3 py-0.5 ${lineCls} flex-1 whitespace-pre break-all font-mono">${prefix} ${escapeHtml(l.content)}</div>
                  </div>
                `;
              }).join('')}
            `).join('')}
          </div>
        `;
      }

      return `
        <div id="git-file-card-${idx}" class="git-diff-card glass-panel rounded-2xl p-4 shadow-xl border border-slate-700/80 space-y-3 transition">

          <!-- File Card Header -->
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800 pb-3">
            <div class="flex items-center space-x-2.5 min-w-0">
              <span class="px-2.5 py-0.5 rounded-lg text-xs font-mono font-bold uppercase border ${sCls}">${f.status}</span>
              <span class="font-mono text-xs font-bold text-white truncate" title="${escapeHtml(f.file_path)}">${escapeHtml(f.file_path)}</span>
              ${f.old_path ? `<span class="text-[11px] text-slate-500 font-mono truncate">(from ${escapeHtml(f.old_path)})</span>` : ''}
            </div>

            <div class="flex items-center space-x-2 shrink-0">
              <div class="flex items-center space-x-1.5 font-mono text-xs bg-slate-900/80 px-2.5 py-1 rounded-lg border border-slate-800">
                <span class="text-emerald-400 font-bold">+${f.additions}</span>
                <span class="text-slate-600">/</span>
                <span class="text-rose-400 font-bold">-${f.deletions}</span>
              </div>
              <button data-action="copyGitFileDiff" data-arg="${idx}" class="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg transition border border-slate-700 text-xs flex items-center space-x-1" title="Copy Diff">
                <i data-lucide="copy" class="w-3.5 h-3.5"></i>
              </button>
              <button data-action="toggleGitFileCollapse" data-arg="${idx}" id="git-toggle-btn-${idx}" class="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg transition border border-slate-700 text-xs" title="Toggle Collapse">
                <i data-lucide="chevron-up" class="w-3.5 h-3.5"></i>
              </button>
            </div>
          </div>

          <!-- Collapsible Diff Body -->
          <div id="git-diff-body-${idx}" class="git-diff-body space-y-2">
            ${diffContentHtml}
          </div>

        </div>
      `;
    }).join('') || '<div class="glass-panel p-8 rounded-2xl text-center text-slate-400 text-xs font-mono">No matching file diffs found</div>';
  }

  lucide.createIcons();
}

function filterGitFiles(query) {
  currentGitSearchQuery = query;
  renderGitFilesAndDiffs();
}

function filterGitStatus(status) {
  currentGitStatusFilter = status;
  document.querySelectorAll('.git-filter-pill').forEach(btn => {
    btn.classList.remove('bg-indigo-600', 'text-white');
    btn.classList.add('text-slate-400');
  });
  const activeBtn = document.getElementById(`git-filter-${status}`);
  if (activeBtn) {
    activeBtn.classList.add('bg-indigo-600', 'text-white');
    activeBtn.classList.remove('text-slate-400');
  }
  renderGitFilesAndDiffs();
}

function toggleGitFileCollapse(idx) {
  const body = document.getElementById(`git-diff-body-${idx}`);
  const btn = document.getElementById(`git-toggle-btn-${idx}`);
  if (!body || !btn) return;
  const isHidden = body.classList.contains('hidden');
  if (isHidden) {
    body.classList.remove('hidden');
    btn.innerHTML = '<i data-lucide="chevron-up" class="w-3.5 h-3.5"></i>';
  } else {
    body.classList.add('hidden');
    btn.innerHTML = '<i data-lucide="chevron-down" class="w-3.5 h-3.5"></i>';
  }
  lucide.createIcons();
}

function expandAllGitDiffs() {
  document.querySelectorAll('.git-diff-body').forEach(b => b.classList.remove('hidden'));
  document.querySelectorAll('[id^="git-toggle-btn-"]').forEach(btn => {
    btn.innerHTML = '<i data-lucide="chevron-up" class="w-3.5 h-3.5"></i>';
  });
  lucide.createIcons();
}

function collapseAllGitDiffs() {
  document.querySelectorAll('.git-diff-body').forEach(b => b.classList.add('hidden'));
  document.querySelectorAll('[id^="git-toggle-btn-"]').forEach(btn => {
    btn.innerHTML = '<i data-lucide="chevron-down" class="w-3.5 h-3.5"></i>';
  });
  lucide.createIcons();
}

function copyGitFileDiff(idx) {
  const gd = ARCH_DATA.git_diff;
  if (!gd || !gd.files || !gd.files[idx]) return;
  const f = gd.files[idx];
  navigator.clipboard.writeText(f.raw_diff || '').then(() => {
    alert(`Diff for ${f.file_path} copied to clipboard!`);
  });
}

function copyAllGitDiffs() {
  const gd = ARCH_DATA.git_diff;
  if (!gd || !gd.files) return;
  const allDiffs = gd.files.map(f => f.raw_diff).join('\n\n');
  navigator.clipboard.writeText(allDiffs).then(() => {
    alert('All Git diffs copied to clipboard!');
  });
}

function jumpToGitFile(idx) {
  const card = document.getElementById(`git-file-card-${idx}`);
  const body = document.getElementById(`git-diff-body-${idx}`);
  const btn = document.getElementById(`git-toggle-btn-${idx}`);
  if (body && body.classList.contains('hidden')) {
    body.classList.remove('hidden');
    if (btn) btn.innerHTML = '<i data-lucide="chevron-up" class="w-3.5 h-3.5"></i>';
    lucide.createIcons();
  }
  if (card) {
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    card.classList.add('ring-2', 'ring-indigo-500');
    setTimeout(() => card.classList.remove('ring-2', 'ring-indigo-500'), 1500);
  }
}
