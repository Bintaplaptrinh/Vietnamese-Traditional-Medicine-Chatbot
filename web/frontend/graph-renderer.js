/* WebGL drawing, worker-based Barnes-Hut layout, and a bounded accessible picker. */
class FullGraphNetwork {
  constructor(container, data, {onNode, onEdge, onStatus, onLayout, onRestore}) {
    this.container = container;
    this.data = data;
    this.onStatus = onStatus;
    this.onLayout = onLayout;
    this.onRestore = onRestore;
    this.nodes = new Map(data.nodes.map(node => [node.id, node]));
    this.edges = new Map(data.edges.map(edge => [edge.id, edge]));
    this.onNode = onNode;
    this.onEdge = onEdge;
    this.cleanups = [];
    this.mount = document.createElement('div');
    this.mount.className = 'graph-canvas';
    this.mount.tabIndex = 0;
    this.mount.setAttribute('aria-label', 'Graph: phím mũi tên để di chuyển, + và − để thu phóng');
    container.append(this.mount);
    this.createPicker();
  }

  async initialize(isCurrent) {
    if (!window.GraphGPU) { this.unavailable(); return; }
    const {MultiDirectedGraph, Sigma} = GraphGPU;
    const graph = this.graph = new MultiDirectedGraph();
    // Yield between batches so search, cancellation, and progress remain responsive.
    for (let start = 0; start < this.data.nodes.length; start += 2000) {
      if (this.destroyed || !isCurrent()) return;
      for (let i = start; i < Math.min(start + 2000, this.data.nodes.length); i++) {
        const node = this.data.nodes[i];
        const angle = i * Math.PI * (3 - Math.sqrt(5));
        const radius = 3 * Math.sqrt(i + 0.5);
        graph.addNode(node.id, {label: node.label, x: radius * Math.cos(angle), y: radius * Math.sin(angle),
          size: 3.5, color: {graph: '#558cdb', mesh: '#9871be', vietherbs: '#4f9a7b'}[node.branch] || '#558cdb'});
      }
      await new Promise(resolve => setTimeout(resolve, 0));
    }
    for (let start = 0; start < this.data.edges.length; start += 4000) {
      if (this.destroyed || !isCurrent()) return;
      for (let i = start; i < Math.min(start + 4000, this.data.edges.length); i++) {
        const edge = this.data.edges[i];
        graph.addDirectedEdgeWithKey(edge.id, edge.from, edge.to, {label: edge.label, size: 1,
          color: edge.review_status === 'quarantine' ? '#b66b2e' : edge.review_status && edge.review_status !== 'accepted' ? '#a887c6' : '#b5bcc8'});
      }
      await new Promise(resolve => setTimeout(resolve, 0));
    }
    if (this.destroyed || !isCurrent()) return;
    graph.updateEachNodeAttributes((id, attributes) => ({...attributes, size: Math.min(9, 3 + Math.log2(1 + graph.degree(id)))}));
    try {
      this.renderer = new Sigma(graph, this.mount, {
        defaultEdgeType: 'arrow', enableEdgeEvents: true, allowInvalidContainer: true,
        hideEdgesOnMove: false, hideLabelsOnMove: true, renderEdgeLabels: false,
        labelDensity: graph.order < 1000 ? 0.7 : 0.07,
        labelGridCellSize: graph.order < 1000 ? 80 : 140,
        labelRenderedSizeThreshold: graph.order < 1000 ? 0 : 9,
        labelSize: 12, stagePadding: 35, minCameraRatio: 0.0001, maxCameraRatio: 3,
        zoomDuration: reducedMotion.matches ? 0 : 150,
        doubleClickZoomingDuration: reducedMotion.matches ? 0 : 150,
        inertiaDuration: reducedMotion.matches ? 0 : 200,
      });
    } catch (error) {
      this.mount.replaceChildren();
      this.unavailable();
      return;
    }
    this.renderer.on('clickNode', ({node}) => this.selectNode(node));
    this.renderer.on('clickEdge', ({edge}) => this.onEdge(this.edges.get(edge)));
    this.listen(this.mount, 'keydown', event => this.keydown(event));
    for (const canvas of this.mount.querySelectorAll('canvas')) {
      this.listen(canvas, 'webglcontextlost', event => {
        event.preventDefault(); this.contextLost = true; this.stopLayout();
        this.onStatus('WebGL tạm dừng. Bạn vẫn có thể tra cứu mọi nút bên dưới.');
      });
      this.listen(canvas, 'webglcontextrestored', () => {
        if (this.destroyed || !this.contextLost) return;
        this.contextLost = false;
        this.onRestore();
      });
    }
    this.onStatus('WebGL · Toàn bộ graph · Cuộn để thu phóng, kéo để di chuyển.');
    if (!reducedMotion.matches && !document.hidden && !graphView.hidden && graph.size) this.startLayout();
  }

  listen(target, type, handler) {
    target.addEventListener(type, handler);
    this.cleanups.push(() => target.removeEventListener(type, handler));
  }

  unavailable() {
    this.onStatus('WebGL không khả dụng trên trình duyệt này. Tra cứu mọi nút và quan hệ bằng bộ chọn bên dưới.');
    this.mount.textContent = 'Bật tăng tốc đồ họa trong trình duyệt để hiển thị graph.';
  }

  createPicker() {
    const picker = this.picker = document.createElement('div'); picker.className = 'graph-node-picker';
    const filter = document.createElement('input'); filter.className = 'input input-sm'; filter.placeholder = 'Tra cứu nút đã tải…';
    filter.setAttribute('aria-label', 'Lọc tất cả nút đã tải');
    const select = this.select = document.createElement('select'); select.className = 'select select-sm graph-node-select';
    select.setAttribute('aria-label', 'Chọn nút graph');
    const previous = document.createElement('button'); previous.className = 'btn btn-sm'; previous.type = 'button'; previous.textContent = '←'; previous.setAttribute('aria-label', 'Trang nút trước');
    const next = document.createElement('button'); next.className = 'btn btn-sm'; next.type = 'button'; next.textContent = '→'; next.setAttribute('aria-label', 'Trang nút tiếp');
    const count = document.createElement('span'); count.className = 'graph-picker-count'; count.setAttribute('role', 'status');
    let matches = this.data.nodes, page = 0, filterTimer;
    const update = () => {
      select.replaceChildren();
      const placeholder = document.createElement('option'); placeholder.textContent = 'Chọn một nút…'; placeholder.value = ''; select.append(placeholder);
      for (const node of matches.slice(page * 200, (page + 1) * 200)) {
        const option = document.createElement('option'); option.value = node.id; option.textContent = node.label; select.append(option);
      }
      previous.disabled = page === 0; next.disabled = (page + 1) * 200 >= matches.length;
      count.textContent = matches.length ? `${page * 200 + 1}–${Math.min((page + 1) * 200, matches.length)} / ${matches.length}` : '0 nút';
    };
    this.listen(filter, 'input', () => {
      clearTimeout(filterTimer);
      filterTimer = setTimeout(() => {
        const query = filter.value.normalize('NFC').toLocaleLowerCase();
        matches = this.data.nodes.filter(node => `${node.label} ${node.id}`.normalize('NFC').toLocaleLowerCase().includes(query)); page = 0; update();
      }, 150);
    });
    this.cleanups.push(() => clearTimeout(filterTimer));
    this.listen(previous, 'click', () => { page--; update(); });
    this.listen(next, 'click', () => { page++; update(); });
    this.listen(select, 'change', () => this.selectNode(select.value, true));
    picker.append(filter, select, previous, count, next); this.container.append(picker); update();
  }

  selectNode(id, focus = false) {
    const node = this.nodes.get(id); if (!node) return;
    this.stopLayout();
    const relations = this.graph?.hasNode(id) && this.renderer
      ? this.graph.edges(id).map(key => this.edges.get(key))
      : this.data.edges.filter(edge => edge.from === id || edge.to === id);
    this.onNode(node, relations);
    if (!this.renderer) return;
    if (this.selected) this.graph.mergeNodeAttributes(this.selected, {highlighted: false, forceLabel: false});
    this.selected = id;
    this.graph.mergeNodeAttributes(id, {highlighted: true, forceLabel: true});
    if (focus) {
      const point = this.renderer.getNodeDisplayData(id);
      this.renderer.getCamera().animate({x: point.x, y: point.y, ratio: Math.min(0.08, this.renderer.getCamera().ratio)}, {duration: reducedMotion.matches ? 0 : 250});
    }
  }

  startLayout() {
    if (!this.renderer || !this.graph.size || this.destroyed || this.contextLost) return;
    try {
      if (!this.layout) {
        this.layout = new GraphGPU.Layout(this.graph, {settings: {
          barnesHutOptimize: true, barnesHutTheta: 0.7, gravity: 1,
          scalingRatio: 10, slowDown: 5, strongGravityMode: true,
        }});
        this.listen(this.layout.worker, 'error', () => { this.stopLayout(); this.onStatus('WebGL · Không thể chạy sắp xếp nền. Graph vẫn hiển thị đầy đủ.'); });
      }
      this.layout.start(); this.onLayout(true);
      clearTimeout(this.layoutTimer);
      // Bounded work prevents continuous battery and CPU use after settling.
      this.layoutTimer = setTimeout(() => this.stopLayout(), 8000);
    } catch (error) {
      this.stopLayout(); this.onStatus('WebGL · Graph đầy đủ; sắp xếp nền không khả dụng.');
    }
  }

  stopLayout() { clearTimeout(this.layoutTimer); this.layout?.stop(); this.onLayout(false); }
  toggleLayout() { this.layout?.isRunning() ? this.stopLayout() : this.startLayout(); }
  fit() { this.stopLayout(); this.renderer?.getCamera().animatedReset({duration: reducedMotion.matches ? 0 : 250}); }
  redraw() { this.renderer?.resize(); this.renderer?.refresh(); }

  keydown(event) {
    if (!this.renderer) return;
    const camera = this.renderer.getCamera(), state = camera.getState(), step = state.ratio * 0.1;
    const changes = {ArrowLeft: {x: state.x - step}, ArrowRight: {x: state.x + step}, ArrowUp: {y: state.y + step}, ArrowDown: {y: state.y - step},
      '+': {ratio: Math.max(0.0001, state.ratio / 1.4)}, '=': {ratio: Math.max(0.0001, state.ratio / 1.4)}, '-': {ratio: Math.min(3, state.ratio * 1.4)}}[event.key];
    if (changes) { event.preventDefault(); camera.setState(changes); }
  }

  destroy() {
    this.destroyed = true; this.stopLayout();
    for (const cleanup of this.cleanups) cleanup();
    this.layout?.kill(); this.renderer?.kill(); this.mount.remove(); this.picker.remove();
    this.nodes.clear(); this.edges.clear();
  }
}
