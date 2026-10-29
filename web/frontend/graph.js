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
const rendererStatus = document.querySelector('#graph-renderer');
const layoutButton = document.querySelector('#graph-layout');
let network;
let graphController;
let loadVersion = 0;
let indexingTimer;

function selectTask(task) {
  window.dispatchEvent(new CustomEvent('workspace:task', { detail: task }));
  const graph = task === 'graph';
  graphView.hidden = !graph; chatView.hidden = graph;
  appShell.classList.toggle('graph-open', graph);
  for (const [button, active] of [[graphButton, graph], [chatButton, !graph]]) {
    button.classList.toggle('menu-active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  if (graph) { if (network) network.redraw(); loadGraph(); loadDocuments(); }
  else {
    ++loadVersion; graphController?.abort(); clearTimeout(indexingTimer); network?.stopLayout();
    if (!busy) input.focus();
  }
}
graphButton.addEventListener('click', () => selectTask('graph'));
chatButton.addEventListener('click', () => selectTask('chat'));

async function api(url, options) {
  const response = await fetch(url, options);
  const value = await response.json();
  if (!response.ok) {
    const error = new Error(typeof value.detail === 'string' ? value.detail : 'Không thể xử lý yêu cầu.');
    error.status = response.status; throw error;
  }
  return value;
}

function describeNode(node, edges) {
  graphDetail.replaceChildren();
  const name = document.createElement('strong'); name.textContent = node.label;
  const meta = document.createElement('p'); meta.textContent = `${node.branch} · ${node.type || 'Concept'}`;
  const id = document.createElement('p'); id.textContent = node.uri || node.id;
  graphDetail.append(name, meta, id);
  const relations = edges.filter(edge => edge.from === node.id || edge.to === node.id);
  const count = document.createElement('p'); count.textContent = `${relations.length} quan hệ`; graphDetail.append(count);
  let shown = 0;
  const more = document.createElement('button'); more.type = 'button'; more.className = 'btn btn-sm';
  const appendRelations = () => {
    more.remove();
    for (const edge of relations.slice(shown, shown + 25)) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-sm';
      button.textContent = `${edge.from === node.id ? '→' : '←'} ${edge.label} · ${edge.from === node.id ? edge.object || edge.to : edge.subject || edge.from}`;
      button.addEventListener('click', () => describeEdge(edge)); graphDetail.append(button);
    }
    shown += 25;
    if (shown < relations.length) { more.textContent = `Thêm quan hệ (${relations.length - shown})`; graphDetail.append(more); }
  };
  more.addEventListener('click', appendRelations); appendRelations();
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

async function renderNetwork(data, version) {
  if (network) network.destroy();
  network = null; networkContainer.replaceChildren();
  graphDetail.textContent = 'Chọn một nút hoặc cạnh để xem thông tin và nguồn.';
  layoutButton.disabled = true; rendererStatus.textContent = '';
  if (!data.nodes.length) return;
  rendererStatus.textContent = 'Đang chuẩn bị graph đầy đủ…';
  const current = network = new FullGraphNetwork(networkContainer, data, {
    onNode: describeNode, onEdge: describeEdge,
    onStatus: text => { if (version === loadVersion) rendererStatus.textContent = text; },
    onRestore: () => {
      if (version === loadVersion) renderNetwork(data, version).catch(error => { rendererStatus.textContent = error.message; });
    },
    onLayout: running => {
      layoutButton.textContent = running ? 'Dừng sắp xếp' : 'Sắp xếp';
      layoutButton.setAttribute('aria-pressed', String(running));
    },
  });
  await current.initialize(() => version === loadVersion);
  if (version === loadVersion) layoutButton.disabled = !current.renderer || !data.edges.length;
}

async function loadGraph(restarted = false) {
  const version = ++loadVersion;
  if (graphController) graphController.abort();
  graphController = new AbortController(); clearTimeout(indexingTimer);
  network?.destroy(); network = null; networkContainer.replaceChildren();
  layoutButton.disabled = true; rendererStatus.textContent = '';
  graphStatus.textContent = 'Đang tải graph…';
  document.querySelector('#graph-count').textContent = 'Đang tải…';
  const params = new URLSearchParams({branch: branchSelect.value, q: queryInput.value, limit: '5000'});
  const data = {nodes: [], edges: []};
  try {
    let page;
    do {
      page = await api(`/api/graph?${params}`, {signal: graphController.signal});
      if (version !== loadVersion) return;
      if (data.snapshot && data.snapshot !== page.snapshot) throw Object.assign(new Error('Kho tri thức đã cập nhật.'), {status: 409});
      data.snapshot = page.snapshot; data.status = page.status;
      for (const node of page.nodes) data.nodes.push(node);
      for (const edge of page.edges) data.edges.push(edge);
      graphStatus.textContent = `Đang tải đầy đủ: ${data.nodes.length} nút · ${data.edges.length} cạnh…`;
      if (page.next) {
        if (String(page.next.after_node) === params.get('after_node') && String(page.next.after_edge) === params.get('after_edge')) throw new Error('Không thể tải trang graph tiếp theo.');
        params.set('snapshot', page.snapshot);
        for (const [key, value] of Object.entries(page.next)) params.set(key, value);
      }
    } while (page.next);
    document.querySelector('#graph-count').textContent = `${data.nodes.length} nút · ${data.edges.length} cạnh`;
    graphStatus.textContent = data.status === 'failed' ? 'Chưa thể tạo kho tri thức. Kiểm tra cấu hình và log backend.' : data.status === 'indexing' ? 'Đang tạo kho tri thức chung. Graph sẽ xuất hiện khi hoàn tất.' :
      !data.nodes.length ? 'Không tìm thấy khái niệm phù hợp.' : 'Đã tải toàn bộ kết quả. Cạnh tím: chưa chấp nhận · Cạnh nâu: cách ly.';
    await renderNetwork(data, version);
    if (data.status === 'indexing' && !graphView.hidden) indexingTimer = setTimeout(loadGraph, 5000);
  } catch (err) {
    if (err.name === 'AbortError' || version !== loadVersion) return;
    if (err.status === 409 && !restarted) return loadGraph(true);
    graphStatus.textContent = `${err.message} Chọn Toàn cảnh để tải lại.`;
    document.querySelector('#graph-count').textContent = 'Chưa tải xong';
  }
}

document.querySelector('#graph-search').addEventListener('submit', event => { event.preventDefault(); loadGraph(); });
branchSelect.addEventListener('change', () => loadGraph());
document.querySelector('#graph-reset').addEventListener('click', () => { queryInput.value = ''; loadGraph(); });
document.querySelector('#graph-fit').addEventListener('click', () => network?.fit());
layoutButton.addEventListener('click', () => network?.toggleLayout());
document.addEventListener('visibilitychange', () => { if (document.hidden) network?.stopLayout(); });
reducedMotion.addEventListener('change', () => { if (reducedMotion.matches) network?.stopLayout(); });

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
