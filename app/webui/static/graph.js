/*
 * graph.js -- Minimal, dependency-free force-directed graph renderer.
 *
 * Renders only the knowledge-graph nodes/edges actually retrieved for the current question
 * (a handful, not the full ~400-node graph) as an inline, interactive SVG: scroll to zoom
 * (toward the cursor), drag to pan, click a node or edge to inspect its properties and
 * connections. No CDN, no build step -- a small Fruchterman-Reingold-style layout computed in
 * plain JS, then drawn as <circle>/<line>/<text>.
 */
(function (global) {
  "use strict";

  var TYPE_COLORS = {
    Plant: "#7c8aa5",
    ProcessUnit: "#8f7fd6",
    Equipment: "#5b9dff",
    Personnel: "#f2a65a",
    SOP: "#e0b155",
    SafetyProcedure: "#f0895d",
    WorkOrder: "#e8637a",
    InspectionReport: "#4fb0c6",
    Incident: "#e5556a",
    RegulatorySubmission: "#9b7fd4",
    RegulatoryBody: "#7c6aa8",
    Document: "#94a1bd",
    Vendor: "#5fbf8f",
    ProcessParameter: "#4fa0c6",
  };
  var DEFAULT_COLOR = "#8a93ab";
  var MIN_SCALE = 0.5;
  var MAX_SCALE = 4;

  // The single graph panel's current interactive instance (drag/pinch state + escape handler).
  // Window/document-level listeners below are registered once and delegate here, instead of
  // each render() call adding its own (which would leak one stale listener per query asked).
  // Pointer Events unify mouse drag and single/multi-finger touch (pan + pinch-to-zoom).
  var activeInstance = null;
  window.addEventListener("pointermove", function (e) {
    if (activeInstance) activeInstance.onDrag(e);
  });
  window.addEventListener("pointerup", function (e) {
    if (activeInstance) activeInstance.onDragEnd(e);
  });
  window.addEventListener("pointercancel", function (e) {
    if (activeInstance) activeInstance.onDragEnd(e);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && activeInstance) activeInstance.onEscape();
  });

  function colorFor(type) {
    return TYPE_COLORS[type] || DEFAULT_COLOR;
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  function truncate(str, n) {
    if (!str) return "";
    return str.length > n ? str.slice(0, n - 1) + "…" : str;
  }

  // ---------- layout (Fruchterman-Reingold-ish force simulation) ----------

  function layout(nodes, edges, width, height) {
    var n = nodes.length;
    var byId = {};
    nodes.forEach(function (node, i) {
      var angle = (2 * Math.PI * i) / Math.max(n, 1);
      var radius = Math.min(width, height) * 0.32;
      node.x = width / 2 + radius * Math.cos(angle) + (Math.random() - 0.5) * 8;
      node.y = height / 2 + radius * Math.sin(angle) + (Math.random() - 0.5) * 8;
      node.vx = 0;
      node.vy = 0;
      byId[node.id] = node;
    });
    var links = edges
      .filter(function (e) { return byId[e.source] && byId[e.target]; })
      .map(function (e) {
        return { source: byId[e.source], target: byId[e.target], relation: e.relation, properties: e.properties };
      });

    if (n <= 1) return { byId: byId, links: links };

    var area = width * height;
    var k = Math.sqrt(area / Math.max(n, 1)) * 0.9;
    var iterations = 220;
    var temperature = width / 8;

    // Positions are NOT clamped to the canvas during simulation -- per-iteration hard
    // clamping causes unrelated nodes pushed off-canvas in roughly the same direction to
    // collapse onto the same boundary coordinate. Instead the simulation runs freely, then
    // the whole result is fit to the canvas once at the end (fitToBounds).
    for (var iter = 0; iter < iterations; iter++) {
      for (var i = 0; i < n; i++) {
        var a = nodes[i];
        var fx = 0, fy = 0;
        for (var j = 0; j < n; j++) {
          if (i === j) continue;
          var b = nodes[j];
          var dx = a.x - b.x, dy = a.y - b.y;
          var dist = Math.max(Math.sqrt(dx * dx + dy * dy), 0.01);
          var rep = (k * k) / dist;
          fx += (dx / dist) * rep;
          fy += (dy / dist) * rep;
        }
        a.vx = (a.vx || 0) + fx;
        a.vy = (a.vy || 0) + fy;
      }
      links.forEach(function (l) {
        var dx = l.source.x - l.target.x, dy = l.source.y - l.target.y;
        var dist = Math.max(Math.sqrt(dx * dx + dy * dy), 0.01);
        var attr = (dist * dist) / k;
        var ux = dx / dist, uy = dy / dist;
        l.source.vx -= ux * attr * 0.5;
        l.source.vy -= uy * attr * 0.5;
        l.target.vx += ux * attr * 0.5;
        l.target.vy += uy * attr * 0.5;
      });
      var cx = width / 2, cy = height / 2;
      var cooling = temperature * (1 - iter / iterations);
      nodes.forEach(function (node) {
        node.vx += (cx - node.x) * 0.01;
        node.vy += (cy - node.y) * 0.01;
        var speed = Math.max(Math.sqrt(node.vx * node.vx + node.vy * node.vy), 0.01);
        var capped = Math.min(speed, Math.max(cooling, 0.5));
        node.x += (node.vx / speed) * capped;
        node.y += (node.vy / speed) * capped;
        node.vx *= 0.85;
        node.vy *= 0.85;
      });
    }

    var margin = 34;
    fitToBounds(nodes, width, height, margin);
    resolveCollisions(nodes, width, height, margin, 34);
    return { byId: byId, links: links };
  }

  function fitToBounds(nodes, width, height, margin) {
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach(function (n) {
      minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
      minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
    });
    var spanX = Math.max(maxX - minX, 1);
    var spanY = Math.max(maxY - minY, 1);
    var scale = Math.min((width - 2 * margin) / spanX, (height - 2 * margin) / spanY);
    var midX = (minX + maxX) / 2, midY = (minY + maxY) / 2;
    var cx = width / 2, cy = height / 2;
    nodes.forEach(function (n) {
      n.x = cx + (n.x - midX) * scale;
      n.y = cy + (n.y - midY) * scale;
    });
  }

  function resolveCollisions(nodes, width, height, margin, minDist) {
    var n = nodes.length;
    for (var pass = 0; pass < 40; pass++) {
      var moved = false;
      for (var i = 0; i < n; i++) {
        for (var j = i + 1; j < n; j++) {
          var a = nodes[i], b = nodes[j];
          var dx = b.x - a.x, dy = b.y - a.y;
          var dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < minDist) {
            moved = true;
            var angle = dist > 0.001 ? Math.atan2(dy, dx) : (Math.random() * Math.PI * 2);
            var push = (minDist - dist) / 2 + 0.5;
            var ux = Math.cos(angle), uy = Math.sin(angle);
            a.x -= ux * push; a.y -= uy * push;
            b.x += ux * push; b.y += uy * push;
          }
        }
      }
      nodes.forEach(function (node) {
        node.x = Math.max(margin, Math.min(width - margin, node.x));
        node.y = Math.max(margin, Math.min(height - margin, node.y));
      });
      if (!moved) break;
    }
  }

  function svgEl(tag, attrs) {
    var el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  }

  // ---------- render ----------

  function render(container, graphData) {
    container.innerHTML = "";
    var nodes = (graphData && graphData.nodes) || [];
    var edges = (graphData && graphData.edges) || [];

    if (nodes.length === 0) {
      var empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No knowledge-graph entities were linked for this query.";
      container.appendChild(empty);
      return;
    }

    var wrap = document.createElement("div");
    wrap.className = "kg-canvas-wrap";
    container.appendChild(wrap);

    var hint = document.createElement("div");
    hint.className = "kg-hint";
    hint.innerHTML = '<span>pinch/scroll to zoom &middot; drag to pan</span><button type="button" class="kg-reset">Reset view</button>';
    wrap.appendChild(hint);

    var width = container.clientWidth || 480;
    var height = Math.max(220, Math.min(380, 160 + nodes.length * 10));

    var laidOut = nodes.map(function (n) { return Object.assign({}, n); });
    var result = layout(laidOut, edges, width, height);
    var byId = result.byId;

    var svg = svgEl("svg", { viewBox: "0 0 " + width + " " + height, width: "100%", height: height, class: "kg-svg" });

    var defs = svgEl("defs", {});
    var marker = svgEl("marker", {
      id: "kgArrow", viewBox: "0 0 10 10", refX: "9", refY: "5",
      markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse",
    });
    marker.appendChild(svgEl("path", { d: "M 0 0 L 10 5 L 0 10 z", class: "kg-arrow" }));
    defs.appendChild(marker);
    svg.appendChild(defs);

    var viewport = svgEl("g", { class: "kg-viewport" });
    var edgeLayer = svgEl("g", { class: "kg-edges" });
    var nodeLayer = svgEl("g", { class: "kg-nodes" });

    var edgeEls = [];
    result.links.forEach(function (l) {
      var g = svgEl("g", { class: "kg-edge" });
      var hit = svgEl("line", {
        x1: l.source.x, y1: l.source.y, x2: l.target.x, y2: l.target.y,
        class: "kg-edge-hit",
      });
      var line = svgEl("line", {
        x1: l.source.x, y1: l.source.y, x2: l.target.x, y2: l.target.y,
        class: "kg-edge-line", "marker-end": "url(#kgArrow)",
      });
      g.appendChild(hit);
      g.appendChild(line);
      g.setAttribute("data-a", l.source.id);
      g.setAttribute("data-b", l.target.id);
      g.addEventListener("click", function (e) {
        e.stopPropagation();
        selectEdge(l);
      });
      edgeLayer.appendChild(g);
      edgeEls.push({ el: g, link: l });
    });

    var nodeEls = {};
    laidOut.forEach(function (node) {
      var g = svgEl("g", { class: "kg-node", "data-id": node.id, transform: "translate(" + node.x + "," + node.y + ")" });
      var r = node.is_query_entity ? 15 : 11;
      var circle = svgEl("circle", {
        r: r, fill: colorFor(node.type),
        class: node.is_query_entity ? "kg-node-circle kg-node-query" : "kg-node-circle",
      });
      g.appendChild(circle);

      var label = svgEl("text", { class: "kg-node-label", y: r + 13, "text-anchor": "middle" });
      label.textContent = truncate(node.label || node.id, 16);
      g.appendChild(label);

      g.addEventListener("mouseenter", function () { if (!selected) highlightNode(node.id); });
      g.addEventListener("mouseleave", function () { if (!selected) clearHighlight(); });
      g.addEventListener("click", function (e) {
        e.stopPropagation();
        selectNode(node.id);
      });

      nodeLayer.appendChild(g);
      nodeEls[node.id] = g;
    });

    viewport.appendChild(edgeLayer);
    viewport.appendChild(nodeLayer);
    svg.appendChild(viewport);
    wrap.appendChild(svg);

    var detail = document.createElement("div");
    detail.className = "kg-detail hidden";
    wrap.appendChild(detail);

    // ---------- highlight / selection ----------

    var selected = null;

    function connectedEdgeIds(nodeId) {
      return edgeEls.filter(function (e) { return e.link.source.id === nodeId || e.link.target.id === nodeId; });
    }

    function highlightNode(nodeId) {
      var connected = connectedEdgeIds(nodeId).map(function (e) { return e.link; });
      var neighborIds = {};
      neighborIds[nodeId] = true;
      connected.forEach(function (l) { neighborIds[l.source.id] = true; neighborIds[l.target.id] = true; });
      Object.keys(nodeEls).forEach(function (id) {
        nodeEls[id].classList.toggle("kg-node-dim", !neighborIds[id]);
      });
      edgeEls.forEach(function (e) {
        var isConnected = e.link.source.id === nodeId || e.link.target.id === nodeId;
        e.el.classList.toggle("kg-edge-dim", !isConnected);
      });
    }

    function highlightEdge(link) {
      Object.keys(nodeEls).forEach(function (id) {
        nodeEls[id].classList.toggle("kg-node-dim", id !== link.source.id && id !== link.target.id);
      });
      edgeEls.forEach(function (e) {
        e.el.classList.toggle("kg-edge-dim", e.link !== link);
      });
    }

    function clearHighlight() {
      Object.keys(nodeEls).forEach(function (id) { nodeEls[id].classList.remove("kg-node-dim"); });
      edgeEls.forEach(function (e) { e.el.classList.remove("kg-edge-dim"); });
    }

    function clearSelection() {
      selected = null;
      clearHighlight();
      detail.classList.add("hidden");
      detail.innerHTML = "";
    }

    function selectNode(nodeId) {
      var node = byId[nodeId];
      if (!node) return;
      selected = { kind: "node", id: nodeId };
      highlightNode(nodeId);
      renderNodeDetail(node, connectedEdgeIds(nodeId).map(function (e) { return e.link; }));
    }

    function selectEdge(link) {
      selected = { kind: "edge", link: link };
      highlightEdge(link);
      renderEdgeDetail(link);
    }

    function propsRows(props) {
      var keys = Object.keys(props || {});
      if (keys.length === 0) return "";
      return '<div class="kg-detail-props">' + keys.map(function (k) {
        return '<div class="kg-detail-row"><span class="kg-detail-key">' + escapeHtml(k) +
          '</span><span class="kg-detail-val">' + escapeHtml(props[k]) + "</span></div>";
      }).join("") + "</div>";
    }

    function renderNodeDetail(node, connections) {
      var connHtml = connections.length
        ? '<div class="kg-detail-conns">' + connections.map(function (l) {
            var isSource = l.source.id === node.id;
            var otherId = isSource ? l.target.id : l.source.id;
            var arrow = isSource ? "→" : "←";
            return '<button type="button" class="kg-detail-conn" data-jump="' + escapeHtml(otherId) + '">' +
              arrow + " " + escapeHtml(l.relation || "related") + " " + escapeHtml(otherId) + "</button>";
          }).join("") + "</div>"
        : "";
      var docHtml = node.file_path
        ? '<a class="kg-detail-doc" href="/api/source/' + encodeURI(node.file_path) +
          '" target="_blank" rel="noopener">View source document ↗</a>'
        : "";

      detail.innerHTML =
        '<div class="kg-detail-head">' +
          '<span class="kg-detail-dot" style="background:' + colorFor(node.type) + '"></span>' +
          "<strong>" + escapeHtml(node.id) + "</strong>" +
          '<span class="kg-detail-type">' + escapeHtml(node.type || "Unknown") + "</span>" +
          '<button type="button" class="kg-detail-close" aria-label="Close">×</button>' +
        "</div>" +
        (node.label && node.label !== node.id ? '<p class="kg-detail-label">' + escapeHtml(node.label) + "</p>" : "") +
        propsRows(node.properties) +
        connHtml +
        docHtml;
      detail.classList.remove("hidden");

      detail.querySelector(".kg-detail-close").addEventListener("click", function (e) {
        e.stopPropagation();
        clearSelection();
      });
      detail.querySelectorAll(".kg-detail-conn").forEach(function (btn) {
        btn.addEventListener("click", function (e) {
          e.stopPropagation();
          selectNode(btn.getAttribute("data-jump"));
        });
      });
    }

    function renderEdgeDetail(link) {
      detail.innerHTML =
        '<div class="kg-detail-head">' +
          '<strong>' + escapeHtml(link.source.id) + " → " + escapeHtml(link.target.id) + "</strong>" +
          '<button type="button" class="kg-detail-close" aria-label="Close">×</button>' +
        "</div>" +
        '<p class="kg-detail-label">' + escapeHtml(link.relation || "related") + "</p>" +
        propsRows(link.properties) +
        '<div class="kg-detail-conns">' +
          '<button type="button" class="kg-detail-conn" data-jump="' + escapeHtml(link.source.id) + '">view ' + escapeHtml(link.source.id) + "</button>" +
          '<button type="button" class="kg-detail-conn" data-jump="' + escapeHtml(link.target.id) + '">view ' + escapeHtml(link.target.id) + "</button>" +
        "</div>";
      detail.classList.remove("hidden");

      detail.querySelector(".kg-detail-close").addEventListener("click", function (e) {
        e.stopPropagation();
        clearSelection();
      });
      detail.querySelectorAll(".kg-detail-conn").forEach(function (btn) {
        btn.addEventListener("click", function (e) {
          e.stopPropagation();
          selectNode(btn.getAttribute("data-jump"));
        });
      });
    }

    svg.addEventListener("click", function () { clearSelection(); });

    // ---------- zoom (toward cursor) + pan ----------

    var state = { scale: 1, tx: 0, ty: 0 };
    function applyTransform() {
      viewport.setAttribute("transform", "translate(" + state.tx + "," + state.ty + ") scale(" + state.scale + ")");
    }
    function screenToRoot(evt) {
      var pt = svg.createSVGPoint();
      pt.x = evt.clientX;
      pt.y = evt.clientY;
      return pt.matrixTransform(svg.getScreenCTM().inverse());
    }

    function zoomAt(rootPoint, factor) {
      var lx = (rootPoint.x - state.tx) / state.scale;
      var ly = (rootPoint.y - state.ty) / state.scale;
      var newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, state.scale * factor));
      state.tx = rootPoint.x - newScale * lx;
      state.ty = rootPoint.y - newScale * ly;
      state.scale = newScale;
      applyTransform();
    }

    svg.addEventListener("wheel", function (e) {
      e.preventDefault();
      zoomAt(screenToRoot(e), e.deltaY < 0 ? 1.12 : 1 / 1.12);
    }, { passive: false });

    hint.querySelector(".kg-reset").addEventListener("click", function () {
      state = { scale: 1, tx: 0, ty: 0 };
      applyTransform();
    });

    // Pointer Events unify mouse and touch: a single finger drags to pan (same as a mouse
    // drag), and a second finger touching down switches to pinch-to-zoom. Tracked pointers are
    // keyed by pointerId so either finger can lift first without breaking the gesture.
    var pointers = {}; // pointerId -> {x, y} in screen coordinates
    var dragging = false, dragStartX = 0, dragStartY = 0, startTx = 0, startTy = 0;
    var pinching = false, pinchStartDist = 0, pinchStartScale = 1;

    function pointerIds() { return Object.keys(pointers); }

    function distanceBetween(idA, idB) {
      var a = pointers[idA], b = pointers[idB];
      return Math.hypot(a.x - b.x, a.y - b.y);
    }

    function midpointOf(idA, idB) {
      var a = pointers[idA], b = pointers[idB];
      return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    }

    function beginSinglePan(x, y) {
      dragging = true;
      pinching = false;
      dragStartX = x; dragStartY = y;
      startTx = state.tx; startTy = state.ty;
      svg.classList.add("kg-grabbing");
    }

    svg.addEventListener("pointerdown", function (e) {
      if (e.target.closest(".kg-node") || e.target.closest(".kg-edge")) return;
      pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = pointerIds();
      if (ids.length === 1) {
        beginSinglePan(e.clientX, e.clientY);
      } else if (ids.length === 2) {
        dragging = false;
        pinching = true;
        pinchStartDist = Math.max(distanceBetween(ids[0], ids[1]), 1);
        pinchStartScale = state.scale;
      }
    });

    // Drag/pinch/escape need window-level listeners (a gesture continues even if a finger or
    // the cursor leaves the svg). Rather than re-registering a new set on every render() call
    // (which would leak a duplicate listener per query asked in the session), a single set is
    // registered once at module load and delegates to whichever graph instance is current.
    activeInstance = {
      onDrag: function (e) {
        if (!pointers[e.pointerId]) return;
        pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
        var ids = pointerIds();

        if (pinching && ids.length === 2) {
          var dist = Math.max(distanceBetween(ids[0], ids[1]), 1);
          var mid = midpointOf(ids[0], ids[1]);
          var targetScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, pinchStartScale * (dist / pinchStartDist)));
          zoomAt(screenToRoot({ clientX: mid.x, clientY: mid.y }), targetScale / state.scale);
          return;
        }
        if (dragging && ids.length === 1) {
          var rect = svg.getBoundingClientRect();
          var factor = width / rect.width;
          state.tx = startTx + (e.clientX - dragStartX) * factor;
          state.ty = startTy + (e.clientY - dragStartY) * factor;
          applyTransform();
        }
      },
      onDragEnd: function (e) {
        if (e && e.pointerId != null) delete pointers[e.pointerId];
        var ids = pointerIds();
        if (ids.length === 1) {
          // one finger lifted out of a pinch -- resume a plain single-finger pan from here
          beginSinglePan(pointers[ids[0]].x, pointers[ids[0]].y);
        } else if (ids.length === 0) {
          dragging = false;
          pinching = false;
          svg.classList.remove("kg-grabbing");
        }
      },
      onEscape: clearSelection,
    };

    var types = Array.from(new Set(nodes.map(function (n) { return n.type || "Unknown"; }))).sort();
    var legend = document.createElement("div");
    legend.className = "kg-legend";
    types.forEach(function (type) {
      var item = document.createElement("span");
      item.className = "kg-legend-item";
      item.innerHTML = '<span class="kg-legend-dot" style="background:' + colorFor(type) + '"></span>' + type;
      legend.appendChild(item);
    });
    container.appendChild(legend);
  }

  global.FORGEGraph = { render: render };
})(window);
