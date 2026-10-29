The committed `../assets/graph-gpu.min.js` bundles Sigma 3.0.2, Graphology 0.26.0,
and the ForceAtlas2 0.10.1 worker. The app serves these locally and requires no
Node process or rendering-library CDN at runtime. Runtime licenses are included
in `../assets/graph-gpu-LICENSE.txt`.

To rebuild after an intentional dependency change:

```sh
cd frontend/vendor
npm ci
npm run build
```

Graph browsing loads every page for the selected ontology branch or search.
`GET /api/graph` returns at most 5,000 nodes and 5,000 edges per page by default
(`limit` accepts 1–10,000). This is a transfer batch size, not a display limit.
While `next` is present, pass its `after_node` and `after_edge` values together
with `snapshot` and the original `branch` and `q`. A changed snapshot returns
409; the UI discards the partial result and restarts once. The full view includes
isolated concepts. Search includes all matching concepts and one-hop neighbors.

Sigma draws nodes and directed edges with WebGL, using the browser's graphics
backend. ForceAtlas2 uses a Web Worker with Barnes-Hut repulsion. Layout stops
after eight seconds, when selecting a node, when hiding the page, or when
switching to chat. The layout button can resume it. Reduced-motion preferences
disable automatic layout. Sparse labels reduce clutter; node and edge details
remain available through selection. Node browsing uses 200 options per page and
local filtering over all loaded nodes. Relations can be expanded in batches.

WebGL acceleration depends on the browser and device configuration; software
rendering is possible. If WebGL cannot initialize, all loaded nodes and their
relations remain available through the picker. The implementation does not use
WebGPU or WebAssembly. All data still resides in browser memory, so the maximum
practical graph size depends on the device.

Validation:

```sh
PYTHONPATH=backend python -m pytest backend/tests/test_graph_display.py -q
node frontend/tests/browser.cjs
```

The browser test uses a local fixture with 6,503 nodes and 6,001 edges, including
isolated nodes. It checks all-page loading, WebGL initialization, the layout
worker, lookup beyond the first picker page, edge provenance, unavailable-WebGL
fallback, chat, uploads, responsive layouts, and reduced motion. Headless Chrome
may use software WebGL; this test does not measure physical GPU performance.
