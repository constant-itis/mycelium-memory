
const PALETTE = [
  "#d5be8b","#9cbba6","#96b8c8","#cf9791","#b2a3c8",
  "#8dbdb5","#c8a07d","#aaa2c7","#a8be88","#91aac9",
  "#c795a1","#b7ac8d","#92b4aa","#c8a8bc","#b1bab5"
];
const PROJECT_COLORS = {};
let palIdx = 0;
function colorFor(project) {
  const key = project || "(none)";
  if (!PROJECT_COLORS[key]) PROJECT_COLORS[key] = PALETTE[palIdx++ % PALETTE.length];
  return PROJECT_COLORS[key];
}
function colorForCommunity(c) { return PALETTE[(c || 0) % PALETTE.length]; }

function setStatus(msg, err) {
  const el = document.getElementById("status");
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("err", !!err);
  el.style.display = msg ? "block" : "none";
}
window.addEventListener("error", e => setStatus("JS error: " + e.message, true));
window.addEventListener("unhandledrejection", e => setStatus("promise error: " + (e.reason?.message || e.reason), true));

// --- renderer selection: 3D WebGL if available, else 2D Cytoscape fallback ---
function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl") || c.getContext("experimental-webgl");
    return !!(gl && typeof gl.getParameter === "function");
  } catch (e) { return false; }
}
// ENGINE is fixed by capability: WebGL -> 3d-force-graph, else cytoscape 2D.
// LAYOUT is the user toggle: 'flat' (FA2 planar, pinned to z=0) vs
// '3d' (nodes seeded from FA2 then relaxed into a rotatable volume).
const WEBGL_OK = webglAvailable() && typeof ForceGraph3D !== "undefined";
let RENDER_MODE = "2d";
let layoutMode = "flat";

function updateModeSwitch() {
  document.querySelectorAll("#mode-switch button").forEach(b => {
    b.classList.toggle("active", b.dataset.mode === layoutMode);
    if (b.dataset.mode === "3d") b.disabled = !WEBGL_OK;   // no WebGL => flat only
  });
  const hint = document.getElementById("hint");
  if (hint && !WEBGL_OK)
    hint.innerHTML = '<span class="dia">◆</span> 2D (no WebGL) · hover to trace · click to drill · esc back';
}
function setLayoutMode(mode) {
  if (mode === layoutMode || (mode === "3d" && !WEBGL_OK)) return;
  layoutMode = mode;
  RENDER_MODE = mode === "3d" ? "3d" : "2d";
  if (Graph) { Graph._destructor(); Graph = null; }
  if (cy) { cy.destroy(); cy = null; }
  document.getElementById("graph").replaceChildren();
  updateModeSwitch(); renderCurrent();
}
document.querySelectorAll("#mode-switch button").forEach(b => {
  b.addEventListener("click", () => setLayoutMode(b.dataset.mode));
});
updateModeSwitch();

const GraphCtor = (typeof graphology === "function") ? graphology
                : (typeof graphology === "object" ? graphology.Graph : null);
const gLib = (typeof graphologyLibrary !== "undefined") ? graphologyLibrary : null;

let Graph = null;   // 3d-force-graph instance
let pendingFit = false;
let cy = null;      // cytoscape instance
let RAW = null;     // last fetched payload {level, nodes, edges, ...}
const view = { level: "projects", project: null, memory: null, community: null };
let selectedId = null;
let lens = "projects";          // 'projects' | 'communities'
let FULL = null;                // cached whole-graph {nodes, edges}
let globalComm = null;          // {memId: communityId} from global Louvain
let commAgg = null;             // { cid: {size, projects, access, members, pinned} }

// highlight/focus state (hover or selection dims everything else)
let curLinks = [];
const adj = {};                 // id -> Set(neighbor ids)
let hlActive = false;
const hlNodes = new Set();      // node ids to keep bright
const hlKeys = new Set();       // link _keys to keep bright
const DIM_NODE = "rgba(110,118,129,0.10)";
const DIM_LINK = "rgba(110,118,129,0.04)";

function buildAdjacency(links) {
  for (const k in adj) delete adj[k];
  curLinks = links;
  links.forEach(l => {
    (adj[l._s] || (adj[l._s] = new Set())).add(l._t);
    (adj[l._t] || (adj[l._t] = new Set())).add(l._s);
  });
}
function setHighlight(id) {
  hlNodes.clear(); hlKeys.clear();
  hlActive = id != null;
  if (id != null) {
    hlNodes.add(id);
    curLinks.forEach(l => {
      if (l._s === id || l._t === id) { hlNodes.add(l._s); hlNodes.add(l._t); hlKeys.add(l._key); }
    });
  }
  applyHighlight();
  if (cy) updateLabels();
}
function applyHighlight() {
  if (RENDER_MODE === "3d" && Graph) {
    Graph.nodeColor(Graph.nodeColor());
    Graph.linkColor(Graph.linkColor());
    Graph.linkWidth(Graph.linkWidth());
    Graph.linkDirectionalParticles(Graph.linkDirectionalParticles());
  } else if (cy) {
    cy.batch(() => {
      if (!hlActive) { cy.elements().removeClass("dim hl"); return; }
      cy.elements().removeClass("hl").addClass("dim");
      hlNodes.forEach(id => {
        const n = cy.getElementById(String(id));
        if (n) n.removeClass("dim").addClass("hl");
      });
      cy.edges().forEach(e => {
        if (hlKeys.has(e.data("key"))) e.removeClass("dim").addClass("hl");
      });
    });
  }
}
function hoverOrSelect(hoverId) { setHighlight(hoverId != null ? hoverId : selectedId); }
// let the browser paint a status update before a synchronous FA2 layout
const nextFrame = () => new Promise(r => requestAnimationFrame(() => setTimeout(r, 0)));

// ------------------------------------------------------------------ nav
let _navFromHash = false;
let navVersion = 0;
async function api(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(response.status === 404 ? "That memory no longer exists." : "Could not load data (" + response.status + "). Try again.");
  return response.json();
}
function seededRandom(seed) { return () => { seed = (Math.imul(seed, 1664525) + 1013904223) | 0; return (seed >>> 0) / 4294967296; }; }

function currentHash() {
  if (view.level === "communities") return "#/communities";
  if (view.level === "community") return "#/community/" + view.community;
  if (view.level === "project") return "#/project/" + encodeURIComponent(view.project);
  if (view.level === "ego") return "#/ego/" + view.memory;
  return "#/";
}
function syncHash() {
  if (!_navFromHash) { if (location.hash !== currentHash()) history.pushState(null, "", currentHash()); }
}
async function routeFromHash() {
  const h = location.hash || "";
  let m;
  if (h === "#/communities") return navCommunities();
  if ((m = h.match(/^#\/community\/(\d+)$/))) return navCommunity(parseInt(m[1]));
  if ((m = h.match(/^#\/project\/(.+)$/))) return navProject(decodeURIComponent(m[1]));
  if ((m = h.match(/^#\/ego\/(\d+)$/))) return navEgo(parseInt(m[1]));
  return navProjects();
}
window.addEventListener("hashchange", () => {
  _navFromHash = true;
  Promise.resolve(routeFromHash()).finally(() => { _navFromHash = false; });
});

async function _navProjects() {
  const version = ++navVersion; resetInspector();
  tooltip.style.display="none";
  lens = "projects"; view.level = "projects"; view.project = null; view.memory = null; view.community = null; selectedId = null;
  updateLensSwitch();
  setStatus("loading projects…");
  const payload = await api("/api/graph/projects");
  if (version !== navVersion) return;
  RAW = payload;
  setStatus("laying out…"); await nextFrame();
  if (version !== navVersion) return;
  computeLayout(RAW);
  updateBreadcrumb(); syncHash(); renderCurrent();
  showPaneIfMobile("main");
}
async function _navProject(name) {
  const version = ++navVersion; resetInspector();
  tooltip.style.display="none";
  lens = "projects"; view.level = "project"; view.project = name; view.memory = null; view.community = null; selectedId = null;
  updateLensSwitch();
  setStatus("loading " + name + "…");
  const payload = await api("/api/graph/project/" + encodeURIComponent(name));
  if (version !== navVersion) return;
  RAW = payload;
  setStatus("detecting communities + layout…"); await nextFrame();
  if (version !== navVersion) return;
  computeLayout(RAW);
  updateBreadcrumb(); syncHash(); renderCurrent();
  showPaneIfMobile("main");
}
async function _navEgo(id) {
  const version = ++navVersion; resetInspector();
  tooltip.style.display="none";
  view.level = "ego"; view.memory = id; selectedId = id;
  setStatus("loading ego #" + id + "…");
  const payload = await api("/api/graph/ego/" + id);
  if (version !== navVersion) return;
  RAW = payload;
  // recover project context so breadcrumb + esc work on a direct ego deep-link
  const centerNode = RAW.nodes && (RAW.nodes.find(n => n.is_center) || RAW.nodes.find(n => n.id === id));
  if (centerNode) view.project = centerNode.project || "(none)";
  if (lens === "communities") view.community = globalComm?.[String(id)] ?? null;
  if (version !== navVersion) return;
  computeLayout(RAW);
  updateBreadcrumb(); syncHash(); renderCurrent();
  showDetail(id, false);
  showPaneIfMobile("main");
}

// ----------------------------------------------------- community lens
function updateLensSwitch() {
  document.querySelectorAll("#lens-switch button").forEach(b =>
    b.classList.toggle("active", b.dataset.lens === lens));
}
let fullPromise = null;
async function ensureFull() {
  if (!fullPromise) fullPromise = loadFull().catch(e => { fullPromise = null; throw e; });
  return fullPromise;
}
async function loadFull() {
  if (FULL && globalComm && commAgg) return;
  setStatus("loading full graph…"); await nextFrame();
  FULL = await api("/api/graph/full");
  setStatus("detecting global communities…"); await nextFrame();
  globalComm = {};
  if (GraphCtor && gLib && gLib.communitiesLouvain) {
    const g = new GraphCtor({ type: "undirected", multi: false, allowSelfLoops: false });
    FULL.nodes.forEach(n => { if (!g.hasNode(String(n.id))) g.addNode(String(n.id)); });
    FULL.edges.forEach(e => {
      const s = String(e.source), t = String(e.target);
      if (s !== t && g.hasNode(s) && g.hasNode(t) && !g.hasEdge(s, t)) g.addUndirectedEdge(s, t, { weight: e.strength || 1 });
    });
    // higher resolution => more, smaller, more topical communities (default 1
    // lumps ~1/3 of all memories into one giant blob via the hub over-connection)
    try { globalComm = gLib.communitiesLouvain(g, { getEdgeWeight: "weight", resolution: 1.5, rng: seededRandom(42) }) || {}; }
    catch (err) { console.warn("global louvain failed", err); }
  }
  commAgg = {};
  FULL.nodes.forEach(n => {
    const c = globalComm[String(n.id)];
    if (c == null) return;
    const a = commAgg[c] || (commAgg[c] = { size: 0, projects: {}, access: 0, members: [], pinned: 0 });
    a.size++; a.access += n.access_count || 0; a.members.push(n.id); if (n.pinned) a.pinned++;
    a.projects[n.project] = (a.projects[n.project] || 0) + 1;
  });
}
function communityLabel(cid) {
  const a = commAgg && commAgg[cid];
  if (!a) return "community " + cid;
  const top = Object.entries(a.projects).sort((x, y) => y[1] - x[1]);
  const extra = top.length - 1;
  return top[0][0] + (extra > 0 ? " +" + extra : "");
}
async function _navCommunities() {
  const version = ++navVersion; resetInspector();
  tooltip.style.display="none";
  lens = "communities"; view.level = "communities"; view.project = null; view.memory = null; view.community = null; selectedId = null;
  updateLensSwitch();
  await ensureFull();
  if (version !== navVersion) return;
  const MIN = 5;
  const kept = Object.keys(commAgg).filter(c => commAgg[c].size >= MIN);
  const keptSet = new Set(kept.map(Number));
  const nodes = kept.map(c => ({
    id: "c" + c, kind: "community", label: communityLabel(c),
    count: commAgg[c].size, access: commAgg[c].access, pinned: commAgg[c].pinned,
    _cid: c, projects: commAgg[c].projects,
  }));
  const memComm = {}; FULL.nodes.forEach(n => memComm[n.id] = globalComm[String(n.id)]);
  const em = {};
  FULL.edges.forEach(e => {
    const ca = memComm[e.source], cb = memComm[e.target];
    if (ca == null || cb == null || ca === cb || !keptSet.has(ca) || !keptSet.has(cb)) return;
    const a = Math.min(ca, cb), b = Math.max(ca, cb), k = a + "|" + b;
    em[k] = (em[k] || 0) + (e.strength || 0);
  });
  const edges = Object.entries(em).map(([k, w]) => {
    const [a, b] = k.split("|"); return { source: "c" + a, target: "c" + b, weight: w, strength: w };
  });
  RAW = { level: "communities", nodes, edges, _hidden: Object.keys(commAgg).length - kept.length };
  if (version !== navVersion) return;
  computeLayout(RAW);
  updateBreadcrumb(); syncHash(); renderCurrent();
  showPaneIfMobile("main");
}
async function _navCommunity(cid) {
  const version = ++navVersion; resetInspector();
  tooltip.style.display="none";
  lens = "communities"; view.level = "community"; view.community = cid; view.memory = null; selectedId = null;
  updateLensSwitch();
  await ensureFull();
  if (version !== navVersion) return;
  const members = new Set((commAgg[cid] && commAgg[cid].members) || []);
  const byId = {}; FULL.nodes.forEach(n => byId[n.id] = n);
  const nodes = [...members].map(id => {
    const n = byId[id];
    return { id, kind: "memory", label: n.label, content_preview: n.label,
             project: n.project, access_count: n.access_count, pinned: n.pinned };
  });
  const edges = FULL.edges.filter(e => members.has(e.source) && members.has(e.target))
    .map(e => ({ source: e.source, target: e.target, strength: e.strength }));
  RAW = { level: "community", community: cid, nodes, edges };
  setStatus("laying out…"); await nextFrame();
  if (version !== navVersion) return;
  computeLayout(RAW);
  updateBreadcrumb(); syncHash(); renderCurrent();
  showPaneIfMobile("main");
}
document.querySelectorAll("#lens-switch button").forEach(b => {
  b.addEventListener("click", () => { b.dataset.lens === "communities" ? navCommunities() : navProjects(); });
});

function updateBreadcrumb() {
  const bc = document.getElementById("breadcrumb");
  const parts = [];
  if (lens === "communities") {
    parts.push(`<span class="crumb ${view.level==='communities'?'cur':''}" data-nav="communities"><span class="dia">◆</span> all communities</span>`);
    if (view.level === "community" || (view.level === "ego" && view.community != null)) {
      parts.push('<span class="sep">›</span>');
      parts.push(`<span class="crumb ${view.level==='community'?'cur':''}" data-nav="community">${escapeHtml(communityLabel(view.community))}</span>`);
    }
  } else {
    parts.push(`<span class="crumb ${view.level==='projects'?'cur':''}" data-nav="projects"><span class="dia">◆</span> all projects</span>`);
    if (view.project != null) {
      parts.push('<span class="sep">›</span>');
      parts.push(`<span class="crumb ${view.level==='project'?'cur':''}" data-nav="project">${escapeHtml(view.project)}</span>`);
    }
  }
  if (view.level === "ego") {
    parts.push('<span class="sep">›</span>');
    parts.push(`<span class="crumb cur">#${view.memory} ego</span>`);
  }
  bc.innerHTML = parts.join(" ");
  bc.querySelectorAll(".crumb[data-nav]").forEach(el => {
    el.addEventListener("click", () => {
      const nav = el.dataset.nav;
      if (nav === "projects") navProjects();
      else if (nav === "communities") navCommunities();
      else if (nav === "project" && view.project != null) navProject(view.project);
      else if (nav === "community" && view.community != null) navCommunity(view.community);
    });
  });
}

// ----------------------------------------- community + FA2/LinLog layout
const POS_SCALE = 1;
function computeLayout(data) {
  data._community = {};
  data._pos = null;
  if (!GraphCtor || !gLib || !data.nodes.length) return;
  try {
    const g = new GraphCtor({ type: "undirected", multi: false, allowSelfLoops: false });
    const N = data.nodes.length;
    data.nodes.forEach((n, i) => {
      const id = String(n.id);
      if (!g.hasNode(id)) g.addNode(id, {
        x: Math.cos(2 * Math.PI * i / N), y: Math.sin(2 * Math.PI * i / N),
      });
    });
    const wkey = data.level === "projects" ? "weight" : "strength";
    data.edges.forEach(e => {
      const s = String(e.source), t = String(e.target);
      if (s !== t && g.hasNode(s) && g.hasNode(t) && !g.hasEdge(s, t))
        g.addUndirectedEdge(s, t, { weight: (e[wkey] || 1) });
    });

    // Louvain communities (Level 1 coloring)
    if (data.level === "project" && gLib.communitiesLouvain) {
      try { data._community = gLib.communitiesLouvain(g, { getEdgeWeight: "weight", rng: seededRandom(42) }) || {}; }
      catch (err) { console.warn("louvain failed", err); }
    }

    // Seed initial positions by community so FA2 pulls them into separate
    // lobes instead of one dense ball (the Gephi cluster-init trick).
    const comm = data._community || {};
    const commIds = [...new Set(Object.values(comm))];
    const commAngle = {};
    commIds.forEach((c, i) => { commAngle[c] = 2 * Math.PI * i / Math.max(1, commIds.length); });
    let idx = 0;
    g.forEachNode(node => {
      const c = comm[node];
      let cx, cy;
      if (c != null && commAngle[c] != null) {
        const a = commAngle[c]; cx = Math.cos(a) * 120; cy = Math.sin(a) * 120;
      } else {
        const a = 2 * Math.PI * idx / g.order; cx = Math.cos(a); cy = Math.sin(a);
      }
      const j = (parseInt(node) || idx);
      g.setNodeAttribute(node, "x", cx + Math.cos(j) * 9);
      g.setNodeAttribute(node, "y", cy + Math.sin(j) * 9);
      idx++;
    });

    // ForceAtlas2 with LinLog + Barnes-Hut so clusters separate spatially
    if (gLib.layoutForceAtlas2 && g.size > 0) {
      const settings = gLib.layoutForceAtlas2.inferSettings(g);
      settings.linLogMode = true;
      settings.barnesHutOptimize = true;
      settings.gravity = 0.5;
      settings.scalingRatio = data.level === "projects" ? 15 : 20;
      settings.outboundAttractionDistribution = true;
      const iters = N > 250 ? 240 : 320;
      data._pos = gLib.layoutForceAtlas2(g, { iterations: iters, getEdgeWeight: "weight", settings });
    }
    if (!data._pos) {
      data._pos = {}; g.forEachNode((id, a) => { data._pos[id] = {x:a.x, y:a.y}; });
    }
    const pts = Object.values(data._pos);
    const xs = pts.map(p=>p.x), ys = pts.map(p=>p.y);
    const minX=Math.min(...xs), maxX=Math.max(...xs), minY=Math.min(...ys), maxY=Math.max(...ys);
    const scale = Math.max(1,maxX-minX,maxY-minY);
    const extent = Math.max(500, Math.sqrt(N)*90);
    pts.forEach(p=>{ p.x=(p.x-(minX+maxX)/2)/scale*extent; p.y=(p.y-(minY+maxY)/2)/scale*extent; });
  } catch (err) { console.warn("layout failed", err); }
}

// ------------------------------------------------------ build + sparsify
function sparsify(links, K, minW) {
  // keep, per node, its top-K strongest incident links (union),
  // plus any link touching the selected node
  const byNode = {};
  links.forEach((l, i) => {
    (byNode[l.source] = byNode[l.source] || []).push(i);
    (byNode[l.target] = byNode[l.target] || []).push(i);
  });
  const keep = new Set();
  Object.values(byNode).forEach(idxs => {
    idxs.sort((a, b) => links[b]._w - links[a]._w);
    idxs.slice(0, K).forEach(i => keep.add(i));
  });
  return links.filter((l, i) => {
    if (l._w < minW && l.source !== selectedId && l.target !== selectedId) return false;
    if (l.source === selectedId || l.target === selectedId) return true;
    return keep.has(i);
  });
}

function memoryLabel(n) {
  const text = (n.content_preview || n.label || '').split('\n')[0];
  return text.replace(/^(?:\s*\[[^\]]+\]\s*)+/, '').replace(/^[-—: ]+/, '').slice(0,90) || ('Memory #' + n.id);
}
function buildRenderData() {
  if (!RAW) return { nodes: [], links: [] };
  const level = RAW.level;
  const minW = parseFloat(document.getElementById("strength").value);
  const K = parseInt(document.getElementById("knn").value);
  const hideIsolated = document.getElementById("hide-isolated").checked;

  const superLevel = (level === "projects" || level === "communities");
  let links = RAW.edges.map(e => ({
    source: e.source, target: e.target,
    _s: e.source, _t: e.target, _key: e.source + "|" + e.target,
    _w: superLevel ? (e.weight || 0) : (e.strength || 0),
    strength: e.strength, weight: e.weight, count: e.count,
  }));
  // aggregated super-nodes use bundle weight; scale K generously
  links = sparsify(links, K, minW);

  const connected = new Set();
  links.forEach(l => { connected.add(l.source); connected.add(l.target); });

  const nodes = RAW.nodes
    .filter(n => !hideIsolated || connected.has(n.id) || n.id === selectedId)
    .map(n => {
      let color, val;
      if (level === "projects") {
        color = colorFor(n.label);
        val = 3 + Math.log2((n.count || 1) + 1) * 1.6;
      } else if (level === "communities") {
        color = colorForCommunity(parseInt(n._cid));
        val = 3 + Math.log2((n.count || 1) + 1) * 1.6;
      } else if (level === "project") {
        color = colorForCommunity(RAW._community ? RAW._community[String(n.id)] : 0);
        val = 1 + Math.log2((n.access_count || 0) + 1);
      } else if (level === "community") {
        color = colorFor(n.project);   // color members by project => see the mix
        val = 1 + Math.log2((n.access_count || 0) + 1);
      } else { // ego
        color = n.is_center ? "#ffffff" : colorFor(n.project);
        val = n.is_center ? 6 : 1 + Math.log2((n.access_count || 0) + 1);
      }
      const node = {
        id: n.id, name: n.kind === "memory" ? memoryLabel(n) : (n.label || "").slice(0, 80),
        project: n.project || n.label, kind: n.kind,
        val: Math.max(1, val), color, pinned: !!n.pinned, full: n,
      };
      const P = RAW._pos && RAW._pos[String(n.id)];
      if (P) {
        node._px = P.x * POS_SCALE; node._py = P.y * POS_SCALE;
        if (RENDER_MODE === "3d" && layoutMode === "flat") {
          // pin to the FA2 plane (z=0) — clean, deterministic, top-down
          node.fx = node._px; node.fy = node._py; node.fz = 0;
          node.x = node._px; node.y = node._py; node.z = 0;
        } else if (RENDER_MODE === "3d") {
          // 3D: seed from FA2 in-plane + a community-based z, leave UNfixed so
          // the force sim relaxes the clusters into a rotatable volume
          const c = (RAW._community && RAW._community[String(n.id)]) || 0;
          node.x = node._px; node.y = node._py;
          node.z = ((c % 8) - 3.5) * 55 + ((String(n.id).length % 11) - 5) * 4;
        }
        // cytoscape (2D engine) reads _px/_py via the preset layout
      }
      return node;
    });

  return { nodes, links };
}

function renderCurrent(fit = true) {
  const renderedVersion = navVersion;
  const { nodes, links } = buildRenderData();
  buildAdjacency(links);
  const rd = document.getElementById("rendered");
  if (rd) rd.textContent = `${nodes.length.toLocaleString()} nodes · ${links.length.toLocaleString()} links`;
  updateLegend(nodes.length);
  if (RENDER_MODE === "3d") render3D(nodes, links, fit); else render2D(nodes, links, fit);
  updateWorkspace(nodes, links);
  // re-apply persistent selection highlight after a fresh draw
  setTimeout(() => { if(renderedVersion===navVersion) setHighlight(selectedId); }, RENDER_MODE === "3d" ? 400 : 60);
  if (!nodes.length) {
    setStatus("nothing to show at these filters — lower min-strength or uncheck 'hide isolated'", false);
  } else {
    setTimeout(() => {if(renderedVersion===navVersion&&!document.getElementById("status").classList.contains("err"))setStatus("");}, 900);
  }
}

function updateLegend(n) {
  const el = document.getElementById("legend");
  if (!el) return;
  const lvl = RAW ? RAW.level : "projects";
  let html = "";
  if (lvl === "projects")
    html = `<b>project map</b> — ● = project (size ∝ memories) · ─ = cross-project links<br><span class="tip">click a node to drill in · hover to trace links</span>`;
  else if (lvl === "communities")
    html = `<b>community map</b> — ● = detected community (size ∝ members) · label = dominant project · ${n} shown${RAW._hidden ? `, ${RAW._hidden} small hidden` : ""}<br><span class="tip">what mycelium groups together, ignoring project labels · click to open</span>`;
  else if (lvl === "project")
    html = `<b>${escapeHtml(RAW.project)}</b> — ● color = detected community · size ∝ access · ${n} memories<br><span class="tip">click a node for detail · hover to trace · esc = back</span>`;
  else if (lvl === "community")
    html = `<b>${escapeHtml(communityLabel(RAW.community))} cluster</b> — ● color = project (see the cross-project mix) · ${n} members<br><span class="tip">click for detail · hover to trace · esc = back</span>`;
  else
    html = `<b>ego #${RAW.center}</b> — ● white = focused · color = project<br><span class="tip">click a neighbor to re-center · esc = back</span>`;
  el.innerHTML = html;
}

// -------------------------------------------------------------- click
function handleNodeClick(n) {
  if (view.level === "projects") { navProject(n.id); }
  else if (view.level === "communities") { navCommunity((n.full || n)._cid); }
  else if (view.level === "project" || view.level === "community") {
    selectedId = n.id; showDetail(n.id); renderCurrent(false);
  }
  else if (view.level === "ego") { navEgo(n.id); }
}

// -------------------------------------------------------------- 3D
function render3D(nodes, links, fit = true) {
  const container = document.getElementById("graph");
  if (!Graph) {
    const hotThr = () => (RAW && RAW.level === "projects" ? 4 : 5);
    Graph = ForceGraph3D({ controlType: "orbit" })(container)
      .backgroundColor("#101516")
      .nodeRelSize(4)
      .cooldownTicks(180)
      .nodeColor(n => (hlActive && !hlNodes.has(n.id)) ? DIM_NODE : n.color)
      .nodeVal(n => n.val)
      .nodeLabel(() => "")
      .nodeOpacity(0.95)
      .linkColor(l => hlActive
        ? (hlKeys.has(l._key) ? "rgba(255,184,108,0.95)" : DIM_LINK)
        : "rgba(138,167,160,0.22)")
      .linkWidth(l => (hlActive && hlKeys.has(l._key)) ? 2.6 : Math.min(2.5, 0.4 + Math.log2((l._w || 0) + 1) * 0.4))
      .linkOpacity(0.85)
      .linkDirectionalParticles(0)
      .linkDirectionalParticleWidth(2)
      .linkDirectionalParticleSpeed(0.01)
      .showNavInfo(false)
      .onNodeClick(n => handleNodeClick(n))
      .onNodeHover(handleHover)
      .onBackgroundClick(() => { selectedId = null; setHighlight(null); resetInspector(); });
    // The vendored ForceGraph drag handler emits a synthetic pointerup with
    // pointerId=0. OrbitControls must only finish pointers it actually tracks;
    // otherwise it treats the remaining mouse pointer as a touch and reads an
    // absent position. Keep the real pointerup (and multi-touch) handling intact.
    const controls = Graph.controls();
    const onPointerUp = controls._onPointerUp;
    if (onPointerUp && controls._isTrackingPointer) {
      controls._onPointerUp = event => {
        if (controls._isTrackingPointer(event)) onPointerUp(event);
      };
    }
  }
  Graph.graphData({ nodes, links });
  // flat = pinned/static; 3d relaxes for ~2s, so fit again later
  resizeGraph();
  if (fit) {
    const activeGraph = Graph;
    [350, 1400, 2500].forEach(delay => setTimeout(() => { if (Graph === activeGraph && fit) Graph.zoomToFit(400, 80); }, delay));
  }
}

function focusOnNode(node) {
  if (!Graph || !node) return;
  const distance = 80;
  const distRatio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1);
  Graph.cameraPosition(
    { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
    node, 700
  );
}

// -------------------------------------------------------------- 2D
function render2D(nodes, links, fit = true) {
  const container = document.getElementById("graph");
  pendingFit = fit && (!container.clientWidth || !container.clientHeight);
  const elements = [
    ...nodes.map(n => ({ data: {
      id: String(n.id), label: n.name, color: n.color,
      size: 7 + n.val * 1.8, pinned: n.pinned ? 1 : 0,
      full: n.full, kind: n.kind, priority: n.val,
    }})),
    ...links.map(e => ({ data: {
      source: String(e.source), target: String(e.target), key: e._key,
      width: Math.min(1.5, 0.35 + Math.log2((e._w || 0) + 1) * 0.12),
      hot: e._w > (RAW && RAW.level === "projects" ? 4 : 5) ? 1 : 0,
    }})),
  ];
  const posMap = {};
  nodes.forEach(n => { if (n._px != null) posMap[String(n.id)] = { x: n._px, y: n._py }; });
  const havePos = Object.keys(posMap).length > 0;
  const layout = havePos
    ? { name: "preset", positions: node => posMap[node.id()] || { x: 0, y: 0 }, fit, padding: container.clientWidth < 600 ? 30 : 55 }
    : { name: "cose", animate: false, randomize: true, fit, padding: container.clientWidth < 600 ? 30 : 55,
        componentSpacing: 60, nodeRepulsion: 9000, idealEdgeLength: 55, numIter: 1000 };
  if (!cy) {
    cy = cytoscape({
      container, wheelSensitivity: 0.25,
      style: [
        { selector: "node", style: {
          "background-color": "data(color)", "width": "data(size)", "height": "data(size)", "border-width": 1.5, "border-color":"#101516",
          "label":"data(label)", "text-opacity":0, "font-family":"system-ui", "font-size":14, "color":"#c7d4cf", "text-valign":"bottom", "text-margin-y":7, "text-outline-color":"#101516", "text-outline-width":3, "text-max-width":170, "text-wrap":"ellipsis" }},
        { selector: "node[pinned = 1]", style: { "border-width": 2, "border-color": "#ffb347" }},
        { selector: 'node.label-visible', style: {"text-opacity":1}},
        { selector: "edge", style: {
          "width": "data(width)", "line-color": "#637e75",
          "curve-style": "haystack", "opacity": 0.22 }},
        
        { selector: ".dim", style: { "opacity": 0.16, "text-opacity": 0 }},
        { selector: "node.hl", style: { "border-width": 2, "border-color": "#eac092", "opacity": 1 }},
        { selector: "edge.hl", style: { "line-color": "rgba(255,184,108,0.95)", "width": 1.8, "opacity": 1, "z-index": 99 }},
      ],
      elements, layout,
    });
    cy.on("zoom pan resize", queueLabels);
    cy.on("tap", "node", evt => handleNodeClick(evt.target.data("full")));
    cy.on("mouseover", "node", evt => {
      const d = evt.target.data("full");
      tooltip.innerHTML = tooltipHtml(d);
      tooltip.style.display = "block";
      const rp = evt.renderedPosition || evt.target.renderedPosition();
      placeTooltip(rp.x, rp.y + document.getElementById("graph").offsetTop);
      hoverOrSelect(evt.target.data("full").id);
    });
    cy.on("mouseout", "node", () => { tooltip.style.display = "none"; hoverOrSelect(null); });
    cy.on("tap", evt => { if (evt.target === cy) { tooltip.style.display = "none"; selectedId = null; setHighlight(null); resetInspector(); } });
  } else {
    cy.elements().remove();
    cy.add(elements);
    if (fit) cy.layout(layout).run();
    else nodes.forEach(n => { const pos = posMap[String(n.id)]; if(pos) cy.getElementById(String(n.id)).position(pos); });
  }
  updateLabels();
}

// ------------------------------------------------------ shared focus
function focusAndShow(id) {
  if (!RAW?.nodes.some(n=>n.id===id)) return navEgo(id);
  selectedId=id; renderCurrent(false); showDetail(id);
}
function focusNodeById(id) {
  if (RENDER_MODE === "3d") {
    const node = Graph?.graphData().nodes.find(x => x.id === id);
    if (node) focusOnNode(node);
  } else if (cy) {
    const ele = cy.getElementById(String(id));
    if (ele && ele.length) cy.animate({ center: { eles: ele }, zoom: Math.max(cy.zoom(), 1.2) }, { duration: 500 });
  }
}

// ---------------------------------------------------------- tooltip
const tooltip = document.getElementById("tooltip");
function tooltipHtml(full) {
  if (!full) return "";
  if (full.kind === "project") {
    return `<div>${escapeHtml(full.label)}</div><div class="p">${full.count} memories · ${full.internal||0} internal links · ${full.access||0}× accesses</div>`;
  }
  if (full.kind === "community") {
    const top = Object.entries(full.projects || {}).sort((a, b) => b[1] - a[1]).slice(0, 5)
      .map(([p, c]) => `${p} ${c}`).join(" · ");
    return `<div>${escapeHtml(full.label)} cluster</div><div class="p">${full.count} members — ${escapeHtml(top)}</div>`;
  }
  return `<div>${escapeHtml((full.label||"").slice(0,80))}</div><div class="p">#${full.id} · ${escapeHtml(full.project)} · ${full.access_count||0}× accesses</div>`;
}
function handleHover(node) {
  const gEl = document.getElementById("graph");
  if (gEl) gEl.style.cursor = node ? "pointer" : "default";
  if (!node) {
    tooltip.style.display = "none";
    hoverOrSelect(null);   // revert to persistent selection (or clear)
    return;
  }
  tooltip.innerHTML = tooltipHtml(node.full);
  tooltip.style.display = "block";
  document.addEventListener("mousemove", positionTooltip, { once: true });
  hoverOrSelect(node.id);
}
function placeTooltip(x,y) {
  const main=document.querySelector('main');
  tooltip.style.left=Math.max(8,Math.min(main.clientWidth-tooltip.offsetWidth-8,x+14))+'px';
  tooltip.style.top=Math.max(8,Math.min(main.clientHeight-tooltip.offsetHeight-8,y+14))+'px';
}
function positionTooltip(e) { const m=document.querySelector('main').getBoundingClientRect();placeTooltip(e.clientX-m.left,e.clientY-m.top); }
document.querySelector('main').addEventListener('mousemove',e=>{if(tooltip.style.display==='block'&&layoutMode==='3d')positionTooltip(e);});

// ---------------------------------------------------------- detail
let detailVersion = 0;
async function showDetail(id, openMobile = true) {
  const version = ++detailVersion;
  document.getElementById("detail-content").innerHTML = '<div class="empty">Loading memory…</div>';
  setInspectorTab("inspect");
  let d;
  try { d = await api(`/api/memory/${id}`); }
  catch (e) {
    if(version !== detailVersion) return;
    const panel = document.getElementById('detail-content');
    panel.innerHTML = '<div class="empty"><p>' + escapeHtml(e.message) + '</p><button>Try again</button></div>';
    panel.querySelector('button').addEventListener('click',()=>showDetail(id,openMobile));
    return;
  }
  if (version !== detailVersion) return;
  if (d.error) return;
  const m = d.memory;
  document.querySelector('[data-inspector="inspect"]').textContent = "Memory #" + m.id;
  const el = document.getElementById("detail-content");
  el.innerHTML = `<div class="pad">
    <h2><span class="dia">◆</span>#${m.id} ${m.pinned ? '<span class="pinned-badge">📌</span>' : ''}</h2>
    <div style="color:var(--dim); font-size:11px; margin-bottom:6px">${escapeHtml(m.project || "(none)")} · ${m.tier} · ${m.access_count} accesses</div>
    <div class="actions">
      <button id="ego-btn">Explore connections ↗</button>
      <button id="open-project" class="ghost">Project</button>
    </div>
    <h3>Memory</h3>
    <div class="content">${escapeHtml(m.content)}</div>
    <h3>Details</h3>
    <div class="kv">
      <b>confidence</b><span>${(m.confidence || 0).toFixed(2)}</span>
      <b>accesses</b><span>${m.access_count || 0}</span>
      <b>source</b><span>${m.source_type || "—"}</span>
      <b>created</b><span>${shortTime(m.created)}</span>
      <b>last accessed</b><span>${shortTime(m.last_accessed)}</span>
    </div>
    ${d.agents.length ? `
      <h3>Accessed by</h3>
      <div class="kv">
        ${d.agents.map(a => `<b>${escapeHtml(a.agent)}</b><span>${a.access_count}× · ${shortTime(a.last_accessed)}</span>`).join("")}
      </div>` : ""}
    <h3>Strongest connections · ${d.neighbors.length}</h3>
    <div class="neighbors">
      ${d.neighbors.map(n => `
        <button class="n" data-id="${n.id}">
          <span class="s">${n.strength.toFixed(1)}</span>
          ${escapeHtml((n.content || "").split("\\n")[0].slice(0, 70))}
          <div class="meta">#${n.id} · ${escapeHtml(n.project || "(none)")}</div>
        </button>`).join("")}
    </div>
  </div>`;
  el.querySelector("#ego-btn").addEventListener("click", () => navEgo(m.id));
  el.querySelector("#open-project").addEventListener("click", () => navProject(m.project || "(none)"));
  el.querySelectorAll(".neighbors .n").forEach(n => {
    n.addEventListener("click", () => {
      const nid = parseInt(n.dataset.id);
      if (view.level === "ego") navEgo(nid);
      else focusAndShow(nid);
    });
  });
  if (openMobile) { document.body.classList.remove("right-collapsed"); resizeGraph(); showPaneIfMobile("right"); }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;" }[c]));
}
function shortTime(t) {
  if (!t) return "—";
  return String(t).replace("T", " ").split(".")[0];
}

// ---------------------------------------------------------- stats/list
let statsData = {};
async function loadStats() {
  const s = statsData = await api("/api/stats");
  document.getElementById("stats").innerHTML = `<span><b>${s.memories.toLocaleString()}</b> memories</span><span><b>${s.projects}</b> projects</span><span class="live-state"><i></i> Read only</span>`;

}
let projectList = [];
async function loadProjectList() { projectList = await api("/api/projects"); renderProjectList(); }
function renderProjectList() {
  const query = document.getElementById("project-filter").value.toLowerCase();
  const projects = projectList.filter(p=>p.project.toLowerCase().includes(query));
  const el = document.getElementById("proj-list");
  el.innerHTML = projects.map(p=>`<button class="p ${view.project===p.project?'current':''}" data-project="${escapeHtml(p.project)}"><span class="sw" style="background:${colorFor(p.project)}"></span><span class="project-name">${escapeHtml(p.project)}</span><span class="ct">${p.count}</span></button>`).join("") || '<p class="muted">No matching projects.</p>';
  el.querySelectorAll(".p").forEach(row=>row.addEventListener("click",()=>navProject(row.dataset.project)));
}
document.getElementById("project-filter").addEventListener("input",renderProjectList);

// ---------------------------------------------------------- search
let searchTimer, searchVersion = 0;
document.getElementById("q").addEventListener("input", e => {
  clearTimeout(searchTimer);
  const version = ++searchVersion;
  const q = e.target.value.trim();
  const el = document.getElementById("search-results");
  if (!q) { el.innerHTML = ""; return; }
  searchTimer = setTimeout(async () => {
    let data;
    try { data=await api(`/api/search?q=${encodeURIComponent(q)}`); }
    catch(e) { if(version===searchVersion) el.innerHTML='<p class="empty">Search is unavailable. Try again.</p>'; return; }
    if (version !== searchVersion) return;
    el.innerHTML = data.results.slice(0, 12).map(h => `
      <button class="hit" data-id="${h.id}">
        <div>${escapeHtml(h.preview.slice(0, 90))}</div>
        <div style="color:var(--dim);font-size:10px;margin-top:2px">#${h.id} · ${escapeHtml(h.project || "(none)")} · ${h.access_count}×</div>
      </button>`).join("") || `<div class="empty">No matching memories.</div>`;
    el.querySelectorAll(".hit").forEach(h => {
      h.addEventListener("click", () => navEgo(parseInt(h.dataset.id)));
    });
  }, 200);
});

// ---------------------------------------------------------- controls
document.getElementById("strength").addEventListener("input", e => {
  document.getElementById("strength-val").textContent = e.target.value;
});
document.getElementById("knn").addEventListener("input", e => {
  document.getElementById("knn-val").textContent = e.target.value;
});
document.getElementById("apply").addEventListener("click", () => renderCurrent());
document.getElementById("relayout").addEventListener("click", () => {
  if (RENDER_MODE === "3d") { if (Graph) Graph.zoomToFit(600, 60); }
  else if (cy) cy.fit(undefined, 40);
});

document.querySelectorAll("aside .section .head").forEach(h => {
  h.addEventListener("click", () => { const open=h.parentElement.classList.toggle("open"); h.setAttribute("aria-expanded",open); });
});

// ---------------------------------------------------------- mobile
function showPane(name) {
  document.querySelectorAll(".tabbar button").forEach(b => b.classList.toggle("active", b.dataset.pane === name));
  document.querySelectorAll("aside, main").forEach(el => {
    const match =
      (name === "left" && el.classList.contains("left")) ||
      (name === "right" && el.classList.contains("right")) ||
      (name === "main" && el.tagName === "MAIN");
    el.classList.toggle("active", match);
  });
  document.body.classList.toggle("detail-open", name === "right");
  if (name === "main") {
    setTimeout(() => {
      const c = document.getElementById("graph");
      if (RENDER_MODE === "3d" && Graph) Graph.width(c.clientWidth).height(c.clientHeight);
      else if (cy) { cy.resize(); if(pendingFit){cy.fit(undefined,30);pendingFit=false;} }
    }, 60);
  }
}
function showPaneIfMobile(name) { if (window.matchMedia("(max-width: 1100px)").matches) showPane(name); }
document.querySelectorAll(".tabbar button").forEach(b => b.addEventListener("click", () => showPane(b.dataset.pane)));
document.getElementById("fab-back").addEventListener("click", () => showPane("main"));

window.addEventListener("resize", () => {
  const c = document.getElementById("graph");
  if (RENDER_MODE === "3d") { if (Graph) Graph.width(c.clientWidth).height(c.clientHeight); }
  else if (cy) { cy.resize(); if(c.clientWidth&&c.clientHeight)cy.fit(undefined,c.clientWidth<600?30:55);else pendingFit=true; }
});

// mobile-friendly defaults
if (window.matchMedia("(max-width: 1100px)").matches) {
  document.getElementById("knn").value = 3;
  document.getElementById("knn-val").textContent = "3";
}

// ---------------------------------------------------------- rails + keys
function resizeGraph() {
  const c = document.getElementById("graph");
  if (RENDER_MODE === "3d" && Graph) Graph.width(c.clientWidth).height(c.clientHeight);
  else if (cy) cy.resize();
}
function toggleRail(side) {
  document.body.classList.toggle(side === "left" ? "left-collapsed" : "right-collapsed");
  setTimeout(resizeGraph, 60);
}
document.getElementById("toggle-left").addEventListener("click", () => toggleRail("left"));
document.getElementById("toggle-right").addEventListener("click", () => toggleRail("right"));

function navUp() {
  if (view.level === "ego") {
    if (lens === "communities") { view.community != null ? navCommunity(view.community) : navCommunities(); }
    else { view.project != null ? navProject(view.project) : navProjects(); }
  }
  else if (view.level === "project") navProjects();
  else if (view.level === "community") navCommunities();
}
document.addEventListener("keydown", e => {
  const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || "");
  if (e.key === "/" && !typing) { e.preventDefault(); document.body.classList.remove("left-collapsed"); showPaneIfMobile("left"); document.querySelector('[data-section="search"]').classList.add("open"); document.getElementById("q").focus(); resizeGraph(); }
  else if (e.key === "Escape") {
    if (typing) { document.activeElement.blur(); return; }
    if (hlActive) { selectedId = null; setHighlight(null); resetInspector(); } else navUp();
  }
  else if (e.key === "[" && !typing) toggleRail("left");
  else if (e.key === "]" && !typing) toggleRail("right");
});

// Workspace summaries, labels, activity, and controls.
let visibleNodes = [], visibleLinks = [];
let inspectorTab = 'inspect';
function setInspectorTab(tab) {
  inspectorTab = tab;
  document.getElementById('detail-content').hidden = tab !== 'inspect';
  document.getElementById('activity-content').hidden = tab !== 'activity';
  document.querySelectorAll('[data-inspector]').forEach(b=>{
    b.classList.toggle('active',b.dataset.inspector===tab);
    b.setAttribute('aria-pressed',b.dataset.inspector===tab);
  });
}
function resetInspector() {
  detailVersion++;
  document.querySelector('[data-inspector="inspect"]').textContent = 'Overview';
  if (RAW) renderOverview();
}
function updateWorkspace(nodes, links) {
  visibleNodes = nodes; visibleLinks = links;
  lastGoodView={view:{...view},lens,raw:RAW};
  const titles = {projects:'Your memory atlas',communities:'Emerging communities',project:view.project,community:communityLabel(view.community),ego:'Memory #'+view.memory};
  const descriptions = {projects:'Explore the projects your memories connect.',communities:'See what groups together across project boundaries.',project:'Explore memories and the communities within this project.',community:'A shared neighborhood, colored by project.',ego:'One memory and its strongest connected neighbors.'};
  document.getElementById('view-title').textContent = titles[view.level];
  document.getElementById('view-description').textContent = descriptions[view.level];
  document.querySelectorAll('.crumb[data-nav]').forEach(el=>{
    el.setAttribute('role','button'); el.tabIndex=0;
    el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();el.click();}});
  });
  renderProjectList();
  if (selectedId == null) renderOverview();
  document.getElementById('hint').textContent = layoutMode === 'flat' ? 'Drag to pan · scroll to zoom · click to explore' : 'Drag to orbit · scroll to zoom · click to explore';
  document.querySelectorAll('#mode-switch button,#lens-switch button').forEach(b=>b.setAttribute('aria-pressed',b.classList.contains('active')));
  document.getElementById('graph-labels').hidden=layoutMode!=='3d';
}
function renderOverview() {
  if (!RAW) return;
  const superLevel = ['projects','communities'].includes(RAW.level);
  const noun = RAW.level === 'projects' ? 'projects' : RAW.level === 'communities' ? 'communities' : 'memories';
  const top = [...visibleNodes].sort((a,b)=>b.val-a.val).slice(0,6);
  const omitted = RAW.nodes.length - visibleNodes.length;
  const hidden = RAW._hidden || 0;
  const text = RAW.level === 'projects'
    ? 'Each dot is a project. Follow a link to see where knowledge crosses boundaries, or open a project to find the memories inside.'
    : RAW.level === 'communities'
    ? 'These groups emerge from memory connections. They can span many projects. Their names come from the most represented project.'
    : RAW.level === 'ego'
    ? 'Explore the strongest neighbors of this memory. Select any memory to follow its connections.'
    : 'Select a memory to read it, inspect its history, and explore the connections around it.';
  document.getElementById('detail-content').innerHTML = `<div class="pad"><div class="eyebrow">${superLevel?'Network overview':'Inside the map'}</div><h2>${superLevel?'Knowledge, connected.':'Follow a thought.'}</h2><p class="intro">${text}</p><div class="metric-grid"><div class="metric"><b>${visibleNodes.length.toLocaleString()}</b><span>${noun} in view</span></div><div class="metric"><b>${visibleLinks.length.toLocaleString()}</b><span>${superLevel?'connection bundles':'connections'} shown</span></div></div><p class="view-note">${omitted ? `${omitted} ${noun} hidden by filters. `:''}${hidden?`${hidden} communities with fewer than 5 members are outside this overview. `:''}${RAW.level==='ego'?'Up to 40 neighbors, ranked by strength. ':''}Showing the strongest links per node${selectedId!=null?', plus all links for the selected memory':''}.</p><h3>Reading the map</h3><div class="legend-item"><span class="legend-circle"></span>Size reflects ${superLevel?'memory count':'access count'}</div><div class="legend-item"><span class="legend-colors"><i></i><i></i><i></i></span>Color identifies ${RAW.level==='project'||RAW.level==='communities'?'a detected community':'a project'}</div><div class="legend-item"><span class="legend-line"></span>${superLevel?'Links bundle shared connections':'Lines connect related memories'}</div><h3>${superLevel?'Largest in this view':'Most accessed in this view'}</h3><div>${top.map(n=>`<button class="top-node" data-top-id="${escapeHtml(n.id)}"><span class="sw" style="background:${n.color}"></span><span class="node-name">${escapeHtml(n.name)}</span><span class="node-count">${superLevel?n.full.count:(n.full.access_count||0)}</span><span aria-hidden="true">↗</span></button>`).join('')}</div><p class="view-note">Hover to trace a neighborhood.<br>Press Esc to clear selection or move up.<br>Use / to search every memory.</p></div>`;
  document.querySelectorAll('[data-top-id]').forEach(b=>b.addEventListener('click',()=>{
    const node=visibleNodes.find(n=>String(n.id)===b.dataset.topId); if(node)handleNodeClick(node);
  }));
}
function updateLabels() {
  if (!cy) return;
  const enabled = document.getElementById('show-labels').checked;
  const sorted = cy.nodes().toArray().sort((a,b)=>Number(b.id()===String(selectedId))-Number(a.id()===String(selectedId)) || Number(b.hasClass('hl'))-Number(a.hasClass('hl')) || b.data('priority')-a.data('priority'));
  const occupied=[];
  const labelFont=11/cy.zoom();
  cy.style().selector('node').style({'font-size':labelFont,'text-margin-y':6/cy.zoom(),'text-outline-width':2.5/cy.zoom(),'text-max-width':170/cy.zoom(),'width':n=>Math.max(n.data('size'),7/cy.zoom()),'height':n=>Math.max(n.data('size'),7/cy.zoom())}).update();
  cy.batch(()=>{
    cy.nodes().removeClass('label-visible');
    if (!enabled) return;
    sorted.forEach((n,i)=>{
      const p=n.renderedPosition(), size=n.renderedWidth(), text=n.data('label');
      const superNode=['project','community'].includes(n.data('kind'));
      if ((!superNode && i>7 && !n.hasClass('hl') && cy.zoom()<1.4) || p.x<20 || p.x>cy.width()-20 || p.y<10 || p.y>cy.height()-30) return;
      const font=11;
      if (i>27 && cy.zoom()<1.2) return;
      const width=Math.min(170,text.length*font*.54);
      const box={x:p.x-width/2-6,y:p.y+size/2+3,w:width+12,h:font+10};
      if(occupied.some(r=>box.x<r.x+r.w&&box.x+box.w>r.x&&box.y<r.y+r.h&&box.y+box.h>r.y))return;
      occupied.push(box);n.addClass('label-visible');
    });
  });
}
let labelFrame=0;
function queueLabels(){cancelAnimationFrame(labelFrame);labelFrame=requestAnimationFrame(updateLabels);}
// Canvas text over the WebGL view avoids an additional Three.js dependency.
function draw3DLabels(){
  requestAnimationFrame(draw3DLabels);
  if(layoutMode!=='3d'||!Graph||!document.getElementById('show-labels').checked)return;
  const canvas=document.getElementById('graph-labels'), dpr=Math.min(devicePixelRatio||1,2);
  const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;
  if(canvas.width!==w*dpr||canvas.height!==h*dpr){canvas.width=w*dpr;canvas.height=h*dpr;}
  const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const occupied=[];ctx.font='11px system-ui';ctx.textAlign='center';ctx.lineJoin='round';
  const nodes=[...Graph.graphData().nodes].sort((a,b)=>b.val-a.val);
  nodes.forEach((n,i)=>{
    if(hlActive&&!hlNodes.has(n.id))return;
    if(i>23&&!hlNodes.has(n.id))return;
    if(!Number.isFinite(n.x)||!Number.isFinite(n.y)||!Number.isFinite(n.z))return;
    const p=Graph.graph2ScreenCoords(n.x,n.y,n.z),label=n.name.length>29?n.name.slice(0,28)+'…':n.name;
    const width=ctx.measureText(label).width;
    const box={x:p.x-width/2-4,y:p.y+15,w:width+8,h:18};
    if(box.x<0||box.x+box.w>w||box.y<0||box.y+box.h>h||occupied.some(r=>box.x<r.x+r.w&&box.x+box.w>r.x&&box.y<r.y+r.h&&box.y+box.h>r.y))return;
    occupied.push(box);ctx.strokeStyle='#101516';ctx.lineWidth=4;ctx.strokeText(label,p.x,p.y+27);ctx.fillStyle='#d0ddd5';ctx.fillText(label,p.x,p.y+27);
  });
}
requestAnimationFrame(draw3DLabels);
let activityLoaded=false, activityVersion=0;
async function loadActivity(){
  const version=++activityVersion,el=document.getElementById('activity-content');
  el.innerHTML='<div class="empty">Loading recent recalls…</div>';
  try{
    const rows=await api('/api/recent');if(version!==activityVersion)return;
    el.innerHTML=`<div class="pad"><div class="activity-head"><span class="eyebrow">Last ${rows.length} recalls</span><button id="refresh-activity">Refresh</button></div><p class="intro">What was searched, and which memories came back. Open a result to explore its neighborhood.</p>${rows.map(r=>`<article class="recall"><time>${escapeHtml(shortTime(r.timestamp))}</time><p>${escapeHtml(r.query||'Untitled recall')}</p><div class="recall-meta">${escapeHtml(r.project||'All projects')} · ${Array.isArray(r.results)?r.results.length:0} results</div><div class="recall-links">${(Array.isArray(r.results)?r.results:[]).slice(0,8).map(result=>{const id=typeof result==='number'?result:result?.id;return Number.isInteger(id)?`<button data-recall-id="${id}">#${id} ↗</button>`:'';}).join('')}</div></article>`).join('')||'<p class="empty">No recalls yet.</p>'}</div>`;
    el.querySelectorAll('[data-recall-id]').forEach(b=>b.addEventListener('click',()=>{setInspectorTab('inspect');navEgo(Number(b.dataset.recallId));}));
    el.querySelector('#refresh-activity').addEventListener('click',loadActivity);activityLoaded=true;
  }catch(e){el.innerHTML='<div class="empty"><p>Recent recalls could not be loaded.</p><button id="retry-activity">Try again</button></div>';el.querySelector('button').addEventListener('click',loadActivity);}
}
document.querySelectorAll('[data-inspector]').forEach(b=>b.addEventListener('click',()=>{setInspectorTab(b.dataset.inspector);if(inspectorTab==='activity'&&!activityLoaded)loadActivity();}));
document.getElementById('filter-toggle').addEventListener('click',()=>{
 const panel=document.getElementById('filter-panel');panel.hidden=!panel.hidden;document.getElementById('filter-toggle').setAttribute('aria-expanded',!panel.hidden);
});
document.getElementById('apply').addEventListener('click',()=>{document.getElementById('filter-panel').hidden=true;document.getElementById('filter-toggle').setAttribute('aria-expanded',false);});
document.getElementById('show-labels').addEventListener('change',()=>{updateLabels();const c=document.getElementById('graph-labels');c.getContext('2d').clearRect(0,0,c.width,c.height);});
document.getElementById('reset-filters').addEventListener('click',()=>{
  document.getElementById('strength').value=.5;document.getElementById('strength-val').textContent='0.5';
  document.getElementById('knn').value=3;document.getElementById('knn-val').textContent='3';
  document.getElementById('hide-isolated').checked=true;document.getElementById('show-labels').checked=true;renderCurrent();
});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.getElementById('filter-panel').hidden){document.getElementById('filter-panel').hidden=true;document.getElementById('filter-toggle').setAttribute('aria-expanded',false);e.stopImmediatePropagation();}},true);


let lastGoodView = null;
function navigate(fn) {
  return async (...args) => {
    let version;
    try { const work = fn(...args); version=navVersion; await work; }
    catch (e) {
      if(version !== navVersion) return;
      if(lastGoodView){Object.assign(view,lastGoodView.view);lens=lastGoodView.lens;RAW=lastGoodView.raw;selectedId=null;updateBreadcrumb();updateLensSwitch();renderCurrent();}
      setStatus(e.message, true);
      const retry=document.createElement('button');retry.textContent='Back to projects';retry.className='error-recovery';
      retry.addEventListener('click',()=>navProjects());document.getElementById('status').appendChild(retry);
    }
  };
}
const navProjects=navigate(_navProjects),navProject=navigate(_navProject),navEgo=navigate(_navEgo),navCommunities=navigate(_navCommunities),navCommunity=navigate(_navCommunity);

// ---------------------------------------------------------- boot
(async () => {
  await Promise.all([loadStats(), loadProjectList()]);
  await routeFromHash();
  // optional ?sel=<id> to open with a node pre-selected/highlighted
  const sel = new URLSearchParams(location.search).get("sel");
  if (sel) { selectedId = parseInt(sel); showDetail(selectedId); setTimeout(() => setHighlight(selectedId), 500); }
})().catch(e=>{
  setStatus('Could not connect to the memory service. '+e.message,true);
  const retry=document.createElement('button');retry.className='error-recovery';retry.textContent='Try again';retry.onclick=()=>location.reload();document.getElementById('status').appendChild(retry);
});
