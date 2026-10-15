/* Graph and PDF ingestion use the same versioned store as chat retrieval. */
const graphView = document.querySelector('#graph-view');
const chatView = document.querySelector('#chat-view');
const graphButton = document.querySelector('#task-graph');
const chatButton = document.querySelector('#task-chat');
const graphStatus = document.querySelector('#graph-status');
const uploadStatus = document.querySelector('#upload-status');
const networkContainer = document.querySelector('#knowledge-network');
const graphDetail = document.querySelector('#graph-detail');
const branchSelect = document.querySelector('#graph-branch');
const queryInput = document.querySelector('#graph-query');
let network;
let graphController;
let loadVersion = 0;
let indexingTimer;

function selectTask(task) {
  const graph = task === 'graph';
  graphView.hidden = !graph; chatView.hidden = graph;
  appShell.classList.toggle('graph-open', graph);
  for (const [button, active] of [[graphButton, graph], [chatButton, !graph]]) {
    button.classList.toggle('menu-active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  if (graph) { if (network) network.redraw(); loadGraph(); loadDocuments(); }
  else { if (!busy) input.focus(); }
}
graphButton.addEventListener('click', () => selectTask('graph'));
chatButton.addEventListener('click', () => selectTask('chat'));

async function api(url, options) {
  const response = await fetch(url, options);
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Không thể xử lý yêu cầu.');
  return value;
}

function describeNode(node, edges) {
  graphDetail.replaceChildren();
  const name = document.createElement('strong'); name.textContent = node.label;
  const meta = document.createElement('p'); meta.textContent = `${node.branch} · ${node.type || 'Concept'}`;
  const id = document.createElement('p'); id.textContent = node.uri || node.id;
  graphDetail.append(name, meta, id);
  const relations = edges.filter(edge => edge.from === node.id || edge.to === node.id);
  for (const edge of relations.slice(0, 15)) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-sm'; button.textContent = edge.label;
    button.addEventListener('click', () => describeEdge(edge)); graphDetail.append(button);
  }
}

function describeEdge(edge) {
  graphDetail.replaceChildren();
  for (const text of [edge.subject && edge.object ? `${edge.subject} → ${edge.predicate} → ${edge.object}` : edge.label,
    edge.document ? `${edge.document}${edge.page ? ` · Trang ${edge.page}` : ''}` : edge.branch,
    edge.review_status ? `Trạng thái: ${edge.review_status} · Kiểm tra ngữ nghĩa: ${edge.semantic_support || 'unknown'}` : 'Quan hệ thuật ngữ trong ontology nguồn.',
    edge.source || '', edge.text || '']) {
    if (!text) continue;
    const paragraph = document.createElement('p'); paragraph.textContent = text; graphDetail.append(paragraph);
  }
}

function renderNetwork(data) {
  if (network) network.destroy();
  network = null; networkContainer.replaceChildren();
  graphDetail.textContent = 'Chọn một nút hoặc cạnh để xem thông tin và nguồn.';
  if (!window.vis) {
    const list = document.createElement('ul');
    for (const node of data.nodes) {
      const row = document.createElement('li'); const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-sm'; button.textContent = node.label;
      button.addEventListener('click', () => describeNode(node, data.edges)); row.append(button); list.append(row);
    }
    networkContainer.append(list); return;
  }
  const nodes = data.nodes.map(node => ({id: node.id, label: node.label, group: node.branch}));
  const edges = data.edges.map(edge => ({id: edge.id, from: edge.from, to: edge.to, label: edge.label, arrows: 'to',
    dashes: edge.review_status && edge.review_status !== 'accepted', color: edge.review_status === 'quarantine' ? '#b66b2e' : undefined}));
  network = new vis.Network(networkContainer, {nodes, edges}, {
    nodes: {shape: 'dot', size: 12, font: {size: 13}}, edges: {font: {size: 10, align: 'middle'}, smooth: false},
    groups: {graph: {color: '#8bb6ff'}, mesh: {color: '#c4a4eb'}, vietherbs: {color: '#8ccab0'}},
    interaction: {hover: true, keyboard: {enabled: true, bindToWindow: false}},
    physics: {stabilization: {iterations: 160}, enabled: !reducedMotion.matches},
  });
  network.on('click', selection => {
    if (selection.nodes.length) describeNode(data.nodes.find(n => n.id === selection.nodes[0]), data.edges);
    else if (selection.edges.length) describeEdge(data.edges.find(e => e.id === selection.edges[0]));
  });
  // Provide keyboard-accessible nodes alongside the canvas graph.
  const accessible = document.createElement('select'); accessible.className = 'select select-sm graph-node-select'; accessible.setAttribute('aria-label', 'Chọn nút graph');
  const placeholder = document.createElement('option'); placeholder.textContent = 'Chọn một nút…'; placeholder.value = ''; accessible.append(placeholder);
  for (const node of data.nodes) { const option = document.createElement('option'); option.value = node.id; option.textContent = node.label; accessible.append(option); }
  accessible.addEventListener('change', () => { const node = data.nodes.find(n => n.id === accessible.value); if (node) { describeNode(node, data.edges); network.selectNodes([node.id]); network.focus(node.id); } });
  networkContainer.append(accessible);
}

async function loadGraph() {
  const version = ++loadVersion;
  if (graphController) graphController.abort();
  graphController = new AbortController(); clearTimeout(indexingTimer);
  graphStatus.textContent = 'Đang tải graph…';
  try {
    const data = await api(`/api/graph?${new URLSearchParams({branch: branchSelect.value, q: queryInput.value, limit: '80'})}`, {signal: graphController.signal});
    if (version !== loadVersion) return;
    document.querySelector('#graph-count').textContent = `${data.nodes.length} nút · ${data.edges.length} cạnh`;
    graphStatus.textContent = data.status === 'failed' ? 'Chưa thể tạo kho tri thức. Kiểm tra cấu hình và log backend.' : data.status === 'indexing' ? 'Đang tạo kho tri thức chung. Graph sẽ xuất hiện khi hoàn tất.' :
      !data.nodes.length ? 'Không tìm thấy khái niệm phù hợp.' : data.limited ? 'Đang hiển thị tối đa 80 cạnh. Tìm tên để xem vùng graph cụ thể.' : 'Các cạnh nét đứt là phát biểu chưa được chấp nhận.';
    renderNetwork(data);
    if (data.status === 'indexing' && !graphView.hidden) indexingTimer = setTimeout(loadGraph, 5000);
  } catch (err) { if (err.name !== 'AbortError' && version === loadVersion) graphStatus.textContent = err.message; }
}

document.querySelector('#graph-search').addEventListener('submit', event => { event.preventDefault(); loadGraph(); });
branchSelect.addEventListener('change', loadGraph);
document.querySelector('#graph-reset').addEventListener('click', () => { queryInput.value = ''; loadGraph(); });

const statusLabels = {queued: 'Đang chờ', parsing: 'Đang đọc PDF', extracting: 'Đang trích xuất và kiểm tra', indexing: 'Đang cập nhật graph', ready: 'Hoàn tất',
  partial: 'Đã nhập; trích xuất chưa đầy đủ', needs_ocr: 'Cần OCR một số trang', interrupted: 'Tiến trình bị gián đoạn', failed: 'Xử lý thất bại', already_indexed: 'Tài liệu đã có trong kho'};

async function loadDocuments() {
  try {
    const data = await api('/api/documents');
    const list = document.querySelector('#document-list'); list.replaceChildren();
    document.querySelector('#document-count').textContent = `(${data.documents.length})`;
    for (const item of [...data.jobs, ...data.documents.filter(d => !data.jobs.some(j => j.document?.id === d.id))]) {
      const row = document.createElement('li');
      const text = document.createElement('span'); text.textContent = `${item.name} · ${statusLabels[item.status] || item.status}${item.pages ? ` · ${item.pages} trang` : ''}`; row.append(text);
      if (['partial', 'interrupted', 'failed'].includes(item.status) && /^[a-f0-9]{64}$/.test(item.id)) {
        const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn btn-sm'; retry.textContent = 'Tiếp tục';
        retry.addEventListener('click', async () => { retry.disabled = true; try { await api(`/api/documents/${item.id}/retry`, {method: 'POST'}); await monitorJob(item.id); } catch (err) { uploadStatus.textContent = err.message; } finally { retry.disabled = false; } }); row.append(retry);
      }
      list.append(row);
    }
    if (!list.children.length) { const row = document.createElement('li'); row.textContent = 'Chưa có tài liệu được index.'; list.append(row); }
  } catch (err) { uploadStatus.textContent = err.message; }
}

async function monitorJob(id) {
  while (true) {
    const job = await api(`/api/documents/${id}`);
    uploadStatus.textContent = `${job.name} · ${statusLabels[job.status] || job.status}${job.total_units ? ` · ${job.processed_units}/${job.total_units} vùng nội dung` : ''}`;
    if (!['queued', 'parsing', 'extracting', 'indexing'].includes(job.status)) {
      await loadDocuments(); await loadGraph(); return;
    }
    await new Promise(resolve => setTimeout(resolve, 2500));
  }
}

const addPdf = document.querySelector('#add-pdf');
const pdfInput = document.querySelector('#pdf-file');
addPdf.addEventListener('click', () => pdfInput.click());
pdfInput.addEventListener('change', async () => {
  const file = pdfInput.files[0]; if (!file) return;
  addPdf.disabled = true; uploadStatus.textContent = 'Đang tải PDF…';
  try {
    const body = new FormData(); body.append('file', file);
    const job = await api('/api/documents', {method: 'POST', body});
    if (job.status === 'already_indexed') { uploadStatus.textContent = statusLabels[job.status]; await loadDocuments(); }
    else await monitorJob(job.id);
  } catch (err) { uploadStatus.textContent = err.message; }
  finally { addPdf.disabled = false; pdfInput.value = ''; }
});

selectTask('graph');
