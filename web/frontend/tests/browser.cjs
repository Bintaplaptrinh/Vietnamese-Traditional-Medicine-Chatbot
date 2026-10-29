// Browser regression with a local SSE fixture; no model API requests.
const {spawn} = require('node:child_process');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../out');
const requests = [];
const uploads = [];
const graphRequests = [];
let graphFixture;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const server = http.createServer(async (req, res) => {
  if (req.url.startsWith('/api/graph')) {
    const params = new URL(req.url, 'http://fixture').searchParams;
    graphRequests.push(Object.fromEntries(params));
    res.writeHead(200, {'Content-Type': 'application/json'});
    if (graphFixture) {
      const afterNode = Number(params.get('after_node') || 0), afterEdge = Number(params.get('after_edge') || 0);
      const take = 2500;
      const nodes = graphFixture.nodes.slice(afterNode, afterNode + take), edges = graphFixture.edges.slice(afterEdge, afterEdge + take);
      const more = afterNode + nodes.length < graphFixture.nodes.length || afterEdge + edges.length < graphFixture.edges.length;
      return res.end(JSON.stringify({status: 'ready', snapshot: 'large-fixture', nodes, edges,
        total_nodes: graphFixture.nodes.length, total_edges: graphFixture.edges.length,
        next: more ? {after_node: afterNode + nodes.length, after_edge: afterEdge + edges.length} : null}));
    }
    return res.end(JSON.stringify({status: 'ready', snapshot: 'fixture', nodes: [{id: 'a', label: 'Bloop', branch: 'graph', type: 'Concept'}, {id: 'b', label: 'Questions', branch: 'graph', type: 'Concept'}],
      edges: [{id: 'ab', from: 'a', to: 'b', label: 'supports', subject: 'Bloop', predicate: 'supports', object: 'Questions', source: 'Fixture', document: 'sample.pdf', page: 1, review_status: 'pending'}]}));
  }
  if (req.url === '/api/documents') {
    if (req.method === 'POST') {
      let raw = ''; for await (const part of req) raw += part;
      uploads.push({contentType: req.headers['content-type'], raw});
      await sleep(300);
      res.writeHead(202, {'Content-Type': 'application/json'});
      return res.end(JSON.stringify({id: 'f'.repeat(64), name: 'uploaded.pdf', status: 'queued'}));
    }
    res.writeHead(200, {'Content-Type': 'application/json'});
    return res.end(JSON.stringify({documents: [{id: 'document:a', name: 'sample.pdf', pages: 1, status: 'parsed'}], jobs: []}));
  }
  if (req.url === '/api/documents/' + 'f'.repeat(64)) {
    res.writeHead(200, {'Content-Type': 'application/json'});
    return res.end(JSON.stringify({id: 'f'.repeat(64), name: 'uploaded.pdf', status: 'ready', processed_units: 1, total_units: 1}));
  }
  if (req.url === '/api/chat') {
    let raw = ''; for await (const part of req) raw += part;
    requests.push(JSON.parse(raw));
    res.writeHead(200, {'Content-Type':'text/event-stream'});
    await sleep(700);
    const result = {answer:'Một không gian nhỏ cho những câu hỏi lớn. **Bloop** sẽ cùng bạn tìm hiểu từng bước. [1](#cite-1)\n\nBạn có thể chọn mức effort phù hợp và mở nguồn ngay trong cuộc trò chuyện.',
      route:'graph', citations:[{id:1,kind:'graph',subject:'Bloop',predicate:'supports',object:'Questions',source:'Fixture'}],
      clarification:{options:['Tìm trên internet','Bổ sung chi tiết']},
      usage:{elapsed_seconds:3.37,input_tokens:1234,output_tokens:156}};
    if (requests.at(-1).messages.at(-1).content === 'Visual fixture') {
      result.answer = 'Nhóm A có 12 người. [1](#cite-1)\n\nNhóm B có 18 người. [1](#cite-1)';
      result.verification_status = 'verified';
      result.visualization = {kind:'bar', language:'vi', values:[12,18], unit:'người', items:[
        {text:'Nhóm A có 12 người.', citations:[1]}, {text:'Nhóm B có 18 người.', citations:[1]}]};
    }
    if (requests.at(-1).messages.at(-1).content === 'Checklist fixture') {
      result.answer = 'Đeo kính bảo hộ. [1](#cite-1)\n\nBuộc tóc gọn. [1](#cite-1)';
      result.verification_status = 'verified';
      result.visualization = {kind:'checklist', language:'vi', items:[
        {text:'Đeo kính bảo hộ.', citations:[1]}, {text:'Buộc tóc gọn.', citations:[1]}]};
    }
    if (['Steps fixture', 'Steps text fixture'].includes(requests.at(-1).messages.at(-1).content)) {
      const items = Array.from({length:7}, (_, i) => ({text:`Bước ${i+1}: Thao tác ${i+1}.`, citations:[1]}));
      result.answer = 'Chỉ dành cho nhân viên đã được đào tạo. [1](#cite-1)\n\n'
        + items.map(item=>`${item.text} [1](#cite-1)`).join('\n\n') + '\n\nLưu ý: Giữ khô. [1](#cite-1)';
      result.verification_status = 'verified';
      result.visualization = requests.at(-1).messages.at(-1).content === 'Steps fixture' ? {kind:'steps', language:'vi', items,
        context:[{text:'Chỉ dành cho nhân viên đã được đào tạo.',citations:[1]}],
        notes:[{text:'Lưu ý: Giữ khô.',citations:[1]}]} : null;
    }
    for (const item of [{type:'result',...result},{type:'token',content:result.answer},{type:'done'}]) res.write(`data: ${JSON.stringify(item)}\n\n`);
    return res.end();
  }
  const filename = path.join(root, req.url === '/' ? 'index.html' : req.url.split('?')[0]);
  if (!filename.startsWith(root) || !fs.existsSync(filename)) {res.writeHead(404); return res.end();}
  const types = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.gif':'image/gif'};
  res.writeHead(200, {'Content-Type':types[path.extname(filename)] || 'application/octet-stream'});
  fs.createReadStream(filename).pipe(res);
});
let chrome, ws;
(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const profile = fs.mkdtempSync('/tmp/bloop-chrome-');
  chrome = spawn('/usr/bin/google-chrome', ['--headless=new','--no-sandbox','--disable-dev-shm-usage','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'], {stdio:'ignore'});
  let port;
  for (let i=0;i<100;i++) {
    const file = path.join(profile,'DevToolsActivePort');
    if (fs.existsSync(file)) {port=fs.readFileSync(file,'utf8').split('\n')[0]; break;}
    await sleep(100);
  }
  assert(port, 'Chrome did not start');
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws = new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise(r=>ws.addEventListener('open',r,{once:true}));
  let next = 0; const pending = new Map(); const errors = [];
  ws.addEventListener('message', e => {const m=JSON.parse(e.data); if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);} if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);});
  const cdp = (method,params={}) => new Promise((resolve,reject)=>{const id=++next;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
  const evaluate = async expression => {const r=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});assert(!r.exceptionDetails, JSON.stringify(r.exceptionDetails));return r.result.value;};
  await cdp('Runtime.enable'); await cdp('Page.enable');
  await cdp('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:`http://127.0.0.1:${server.address().port}`});
  for(let i=0;i<100;i++){if(await evaluate('Boolean(window.marked && window.DOMPurify && document.querySelector("#effort") && typeof showThinking === "function")'))break;await sleep(100);}
  assert(await evaluate('Boolean(window.marked && window.DOMPurify)'), 'Markdown CDN unavailable');
  for (let i=0;i<50;i++) { if (await evaluate('document.querySelector("#graph-count").textContent.includes("2 nút")')) break; await sleep(100); }
  assert(await evaluate('!document.querySelector("#graph-view").hidden && document.querySelector("#chat-view").hidden'));
  assert.deepEqual(await evaluate('Array.from(document.querySelector("#graph-branch").options, o => o.value)'), ['graph','mesh','vietherbs']);
  assert(await evaluate('Boolean(document.querySelector("#knowledge-network canvas"))'));
  await evaluate('document.querySelector(".graph-node-select").value="a"; document.querySelector(".graph-node-select").dispatchEvent(new Event("change"))');
  assert(await evaluate('document.querySelector("#graph-detail").textContent.includes("Bloop")'));
  assert(await evaluate('Boolean(document.querySelector("#add-pdf")) && document.querySelector("#pdf-file").accept.includes(".pdf")'));
  fs.writeFileSync('/tmp/bloop-graph.png',Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  graphFixture = {
    nodes: Array.from({length: 6503}, (_, i) => ({id: `n${i}`, label: `Concept ${i}`, branch: 'graph'})),
    edges: Array.from({length: 6001}, (_, i) => ({id: `e${i}`, from: `n${i}`, to: `n${(i + 1) % 6000}`, label: 'relates', review_status: 'pending', source: `Source ${i}`})),
  };
  await evaluate('document.querySelector("#graph-reset").click()');
  for (let i = 0; i < 150; i++) { if (await evaluate('Boolean(network?.renderer && network.graph.order === 6503)')) break; await sleep(100); }
  assert.deepEqual(await evaluate('[network.graph.order, network.graph.size]'), [6503, 6001]);
  assert(await evaluate('document.querySelector("#graph-count").textContent.includes("6503 nút")'));
  assert(await evaluate('document.querySelector("#graph-renderer").textContent.includes("WebGL")'));
  assert(await evaluate('Boolean(network.layout?.worker)'));
  for (let i = 0; i < 100; i++) { if (await evaluate('network.graph.getNodeAttribute("n0", "x") !== 3 * Math.sqrt(0.5)')) break; await sleep(100); }
  assert(await evaluate('network.graph.getNodeAttribute("n0", "x") !== 3 * Math.sqrt(0.5)'), 'The layout worker must update node positions');
  assert(graphRequests.some(r => r.after_node === '5000' && r.snapshot === 'large-fixture'));
  assert(await evaluate('document.querySelectorAll(".graph-node-select option").length <= 201'));
  await evaluate('document.querySelector(".graph-node-picker input").value = "Concept 6502"; document.querySelector(".graph-node-picker input").dispatchEvent(new Event("input", {bubbles: true}))');
  for (let i = 0; i < 100; i++) { if (await evaluate('Boolean(document.querySelector(".graph-node-select option[value=n6502]"))')) break; await sleep(100); }
  assert(await evaluate('Boolean(document.querySelector(".graph-node-select option[value=n6502]"))'));
  await evaluate('document.querySelector(".graph-node-select").value="n6502"; document.querySelector(".graph-node-select").dispatchEvent(new Event("change"))');
  assert(await evaluate('document.querySelector("#graph-detail").textContent.includes("Concept 6502")'));
  assert.equal(await evaluate('network.layout.isRunning()'), false);
  await evaluate('network.renderer.emit("clickEdge", {edge: "e6000"})');
  assert(await evaluate('document.querySelector("#graph-detail").textContent.includes("Source 6000")'));
  await evaluate('document.querySelector("#graph-fit").click()'); await sleep(300);
  fs.writeFileSync('/tmp/bloop-graph-large.png', Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  // A device without WebGL still exposes every node through the bounded picker.
  await evaluate('window.savedGraphGPU = GraphGPU; GraphGPU = {...GraphGPU, Sigma: class { constructor() { throw new Error("No WebGL"); } }}; document.querySelector("#graph-reset").click()');
  for (let i = 0; i < 100; i++) { if (await evaluate('document.querySelector("#graph-renderer").textContent.includes("không khả dụng")')) break; await sleep(100); }
  assert(await evaluate('document.querySelector("#graph-renderer").textContent.includes("không khả dụng")'));
  assert(await evaluate('network.nodes.has("n6502") && document.querySelectorAll(".graph-node-select option").length <= 201'));
  graphFixture = null;
  await evaluate('GraphGPU = window.savedGraphGPU; document.querySelector("#graph-reset").click()');
  for (let i = 0; i < 100; i++) { if (await evaluate('Boolean(network?.renderer && network.graph.order === 2)')) break; await sleep(100); }
  await evaluate('window.oldNetwork = network; const gpuCanvas = network.mount.querySelector("canvas"); gpuCanvas.dispatchEvent(new Event("webglcontextlost", {cancelable: true})); gpuCanvas.dispatchEvent(new Event("webglcontextrestored"))');
  for (let i = 0; i < 100; i++) { if (await evaluate('Boolean(network !== window.oldNetwork && network?.renderer)')) break; await sleep(100); }
  assert(await evaluate('window.oldNetwork.destroyed && Boolean(network.renderer)'), 'WebGL context recovery must rebuild the renderer');
  await evaluate('const uploadTransfer = new DataTransfer(); uploadTransfer.items.add(new File(["%PDF-fixture"], "uploaded.pdf", {type: "application/pdf"})); document.querySelector("#pdf-file").files=uploadTransfer.files; document.querySelector("#pdf-file").dispatchEvent(new Event("change"))');
  assert(await evaluate('document.querySelector("#add-pdf").disabled'));
  for (let i=0;i<30;i++) { if (await evaluate('!document.querySelector("#add-pdf").disabled')) break; await sleep(100); }
  assert.equal(uploads.length, 1);
  assert(uploads[0].contentType.startsWith('multipart/form-data') && uploads[0].raw.includes('uploaded.pdf'));
  assert(await evaluate('document.querySelector("#upload-status").textContent.includes("Hoàn tất")'));
  await evaluate('document.querySelector("#task-chat").click()');
  assert(await evaluate('document.querySelector("#chat-form").contains(document.querySelector("#effort"))'));
  assert.deepEqual(await evaluate('Array.from(document.querySelector("#source-mode").options, o => o.value)'), ['graph','web','hybrid']);
  assert(await evaluate('!document.querySelector("#route") && !document.querySelector("#ask-user")'));
  assert(await evaluate('document.querySelector(".mascot-stage").hidden && Boolean(document.querySelector("#mascot"))'), 'Hide the mascot while preserving it');
  for (const width of [320, 390, 768, 1280]) {
    await cdp('Emulation.setDeviceMetricsOverride', {width, height: 900, deviceScaleFactor: 1, mobile: width < 601});
    assert(await evaluate('document.documentElement.scrollWidth <= innerWidth'), `Empty chat overflow at ${width}px`);
    assert(await evaluate('(() => { const f = document.querySelector("#chat-form").getBoundingClientRect(), m = document.querySelector("main").getBoundingClientRect(); return Math.abs(f.top + f.height / 2 - (m.top + m.height / 2)) < 30 && f.width > 200; })()'), `Composer should start centered at ${width}px`);
  }
  assert.equal(await evaluate('document.querySelector(".effort-trigger").textContent.includes("Low")'), true);
  assert(await evaluate('document.querySelector("#effort-options").hidden'));
  await evaluate('document.querySelector(".effort-trigger").click()');
  assert(await evaluate('document.querySelector(".effort-trigger").textContent.includes("Low")'));
  assert(await evaluate('!document.querySelector("#effort-options").hidden'));
  await evaluate('document.querySelector("#effort").value=2; document.querySelector("#effort").dispatchEvent(new Event("input", {bubbles:true}))');
  await evaluate('document.querySelector(".effort-trigger").dispatchEvent(new KeyboardEvent("keydown", {key:"Escape", bubbles:true}))');
  assert(await evaluate('document.querySelector("#effort-options").hidden && document.querySelector(".effort-trigger").textContent.includes("High")'));
  assert(await evaluate('getComputedStyle(document.querySelector("#chat-form"), "::after").content === "none"'));
  assert.equal(await evaluate('document.querySelectorAll(".astral-star").length'), 32);
  assert.equal(await evaluate('getComputedStyle(document.querySelector("#chat-form")).backgroundColor'), 'rgb(11, 11, 13)');
  await evaluate('document.querySelector("#message").dispatchEvent(new Event("input", {bubbles:true}))');
  assert(await evaluate('document.querySelector(".astral-field").classList.contains("is-typing")'));
  await sleep(300);
  fs.writeFileSync('/tmp/bloop-high-effort.png',Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await evaluate('document.querySelector(".effort-trigger").click()');
  await sleep(250);
  fs.writeFileSync('/tmp/bloop-effort-menu.png',Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await evaluate('document.querySelector(".effort-trigger").click()');

  await evaluate('document.querySelector(".source-trigger").click()');
  await sleep(300);
  assert(await evaluate('document.querySelector(".source-trigger").getAttribute("aria-expanded") === "true"'));
  assert.equal(await evaluate('document.querySelectorAll("[role=menuitemradio]").length'), 3);
  assert(await evaluate('document.querySelector("#source-options").getBoundingClientRect().left >= 0'));
  await evaluate('document.querySelector("[role=menuitemradio]:last-of-type").click()');
  assert.equal(await evaluate('document.querySelector("#source-mode").value'), 'hybrid');
  await evaluate('document.querySelector(".source-trigger").click()');
  await sleep(300);
  await evaluate('document.querySelector("[role=menuitemradio]").click()');
  assert.equal(await evaluate('document.querySelector("#source-mode").value'), 'graph');
  fs.writeFileSync('/tmp/bloop-chat-water.png',Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await evaluate('document.querySelector("#effort").value=1; document.querySelector("#effort").dispatchEvent(new Event("input", {bubbles: true})); document.querySelector("#message").value="Chào Bloop"; document.querySelector("#chat-form").requestSubmit()');
  await sleep(150);
  assert(await evaluate('!document.querySelector(".astral-field")'), 'Astral effect must stop outside High effort');
  assert(await evaluate('document.querySelector("#chat-form").classList.contains("is-dropping")'), 'First send should start the water drop');
  await evaluate('composerDrop.pause(); composerDrop.currentTime = 600');
  assert(await evaluate('(() => { const r = document.querySelector("#chat-form").getBoundingClientRect(); return r.width < 80 && r.height > 50; })()'), 'Composer should contract into a droplet');
  fs.writeFileSync('/tmp/bloop-chat-droplet.png',Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await evaluate('composerDrop.currentTime = 1050; composerDrop.play()');
  assert.equal(await evaluate('document.querySelectorAll(".thinking-dots span").length'),3);
  assert(await evaluate('Boolean(document.querySelector(".thinking-avatar"))'));
  assert(await evaluate('document.querySelector("#source-mode").disabled'));
  fs.writeFileSync('/tmp/bloop-thinking.png',Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await sleep(900);
  assert(await evaluate('!document.querySelector("#chat-form").classList.contains("is-dropping") && !document.querySelector("#chat-form").inert'), 'Composer should settle and become usable');
  assert(await evaluate('(() => { const f = document.querySelector("#chat-form").getBoundingClientRect(), m = document.querySelector("main").getBoundingClientRect(); return f.top > m.top + m.height / 2 && f.bottom < innerHeight; })()'), 'Composer should land at the bottom');
  assert(await evaluate('document.querySelectorAll(".reveal-character").length>0'));
  assert.equal(requests[0].effort,'medium');assert.equal(requests[0].route,'graph');assert.equal(requests[0].ask_user,true);
  assert.equal(await evaluate('document.querySelector("#source-mode").disabled'), false);
  const usage=await evaluate('document.querySelector(".evidence-usage").textContent');
  assert(usage.includes('3.37s') && usage.includes('1,234') && !usage.includes('model calls') && !usage.includes('graph'));
  await evaluate('document.querySelector(".citation-link").click()');
  for (let i=0;i<30;i++) { if (await evaluate('document.querySelector("#citation-dialog").open')) break; await sleep(50); }
  assert(await evaluate('document.querySelector("#citation-dialog").open'));
  assert(await evaluate('document.querySelector("#citation-content blockquote").textContent === "Fixture"'));
  assert(await evaluate('document.querySelector(".evidence-relations").textContent.includes("supports")'));
  await sleep(400);
  fs.writeFileSync('/tmp/bloop-evidence.png',Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await evaluate('document.querySelector("#citation-dialog").close()');
  await sleep(3500);
  await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'));
  assert(await evaluate('document.querySelector("#message").getBoundingClientRect().width > 90'));
  assert(await evaluate('document.querySelector(".chat-start .chat-bubble").getBoundingClientRect().width > 200'), 'Assistant bubble must not collapse around metadata');
  fs.writeFileSync('/tmp/bloop-mobile.png',Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await evaluate('Array.from(document.querySelectorAll(".clarification-options button")).find(b=>b.textContent.includes("internet")).click()');
  await sleep(150);
  assert.equal(await evaluate('document.querySelector(".thinking-label").textContent'), 'Searching the internet');
  await sleep(800); assert.equal(requests[1].route,'web');assert.equal(requests[1].ask_user,true);
  assert.equal(requests[1].messages.at(-1).content, requests[0].messages.at(-1).content);
  await evaluate('document.querySelector("#message").value="Câu hỏi tiếp theo"; document.querySelector("#chat-form").requestSubmit()');
  assert(await evaluate('!composerDrop'), 'Follow-up messages should keep the composer at the bottom');
  await sleep(950);assert.equal(requests[2].route,'graph');
  for (const mode of ['web','hybrid']) {
    await evaluate(`document.querySelector("#source-mode").value="${mode}"; document.querySelector("#message").value="Chọn nguồn"; document.querySelector("#chat-form").requestSubmit()`);
    await sleep(950); assert.equal(requests.at(-1).route,mode);
    assert.equal(await evaluate('document.querySelector("#source-mode").value'),mode);
  }
  for (const width of [320,390,600,601,768]) {
    await cdp('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:true});
    assert(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), `Overflow at ${width}px`);
    assert(await evaluate('document.querySelector("#message").getBoundingClientRect().width > 90'), `Input too small at ${width}px`);
  }
  await cdp('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await evaluate('document.querySelector("#message").value="Ít chuyển động"; document.querySelector("#chat-form").requestSubmit()');
  await sleep(950); assert.equal(await evaluate('document.querySelector(".chat-start:last-child").querySelectorAll(".reveal-character").length'),0);
  await evaluate('document.querySelector("#task-graph").click()');
  for (let i = 0; i < 100; i++) { if (await evaluate('Boolean(network?.renderer)')) break; await sleep(100); }
  assert(await evaluate('Boolean(network.renderer) && !network.layout'), 'Reduced motion must disable automatic layout');
  // First-send behavior must also work when motion is reduced from the start.
  await evaluate('window.fixtureBeforeReload = true');
  await cdp('Page.reload');
  for (let i = 0; i < 100; i++) { if (await evaluate('Boolean(!window.fixtureBeforeReload && document.querySelector("#task-chat") && typeof selectTask === "function")')) break; await sleep(100); }
  await evaluate('document.querySelector("#task-chat").click(); document.querySelector("#message").value="Reduced motion first message"; document.querySelector("#chat-form").requestSubmit()');
  assert(await evaluate('appShell.classList.contains("chat-started") && !composerDrop && !form.inert'), 'Reduced motion should dock immediately');
  await sleep(950);
  // Resizing during a mobile drop must restore the responsive, usable form.
  await cdp('Emulation.setEmulatedMedia', {features: [{name: 'prefers-reduced-motion', value: 'no-preference'}]});
  await evaluate('window.fixtureBeforeReload = true');
  await cdp('Page.reload');
  for (let i = 0; i < 100; i++) { if (await evaluate('Boolean(!window.fixtureBeforeReload && document.querySelector("#task-chat") && typeof selectTask === "function")')) break; await sleep(100); }
  await cdp('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await sleep(150);
  await evaluate('document.querySelector("#task-chat").click(); document.querySelector("#message").value="Mobile first message"; document.querySelector("#chat-form").requestSubmit()');
  await sleep(150);
  assert(await evaluate('Boolean(composerDrop)'), 'Mobile first send should animate');
  await cdp('Emulation.setDeviceMetricsOverride', {width: 320, height: 844, deviceScaleFactor: 1, mobile: true});
  await sleep(150);
  assert(await evaluate('!composerDrop && !form.inert && !form.parentElement.style.height && document.documentElement.scrollWidth <= innerWidth'), 'Resize should safely finish the drop');
  // Verified visuals travel through the real SSE handler and retain citations.
  await sleep(950);
  await evaluate('document.querySelector("#message").value="Visual fixture"; document.querySelector("#chat-form").requestSubmit()');
  await sleep(1100);
  assert(await evaluate('Boolean(document.querySelector(".chat-start:last-child .visual-answer"))'));
  assert.equal(await evaluate('document.querySelector(".chat-start:last-child").querySelectorAll("[data-visual-item]").length'),2);
  assert(await evaluate('document.querySelector(".chat-start:last-child").textContent.includes("18 người")'));
  await evaluate('document.querySelector(".chat-start:last-child .visual-answer button").click()');
  assert.equal(await evaluate('document.querySelector(".chat-start:last-child .visual-answer button").getAttribute("aria-pressed")'),'true');
  assert(await evaluate('Boolean(document.querySelector(".chat-start:last-child .citation-link"))'));
  await evaluate('document.querySelector(".chat-start:last-child .visual-answer button").click()');
  assert.equal(await evaluate('document.querySelector(".chat-start:last-child").querySelectorAll("[data-visual-item]").length'),2);
  assert(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Visual must fit mobile viewport');
  await evaluate('document.querySelector("#message").value="Checklist fixture"; document.querySelector("#chat-form").requestSubmit()');
  await sleep(1100);
  assert.equal(await evaluate('document.querySelector(".chat-start:last-child").querySelectorAll("[data-visual-item]").length'),2);
  assert(await evaluate(`(() => {
    const answer=document.querySelector('.chat-start:last-child');
    return answer.textContent.includes('Các biện pháp') && answer.textContent.includes('Đeo kính bảo hộ.')
      && !answer.textContent.includes('Bước') && answer.querySelector('.citation-link')
      && document.documentElement.scrollWidth <= innerWidth;
  })()`), 'Independent measures should render as a cited checklist without process steps');
  await evaluate('document.querySelector("#message").value="Steps fixture"; document.querySelector("#chat-form").requestSubmit()');
  await sleep(1100);
  assert(await evaluate(`(() => {
    const answer=document.querySelector('.chat-start:last-child');
    return answer.querySelectorAll('[data-visual-item]').length === 7
      && (answer.textContent.match(/Bước 1/g)||[]).length === 1
      && answer.querySelector('[data-visual-supporting="context"]').textContent.includes('đào tạo')
      && answer.querySelector('[data-visual-supporting="notes"]').textContent.includes('Giữ khô')
      && !answer.querySelector('[data-visual-item]:last-child').textContent.includes('Lưu ý')
      && answer.querySelectorAll('.citation-link').length === 9
      && document.documentElement.scrollWidth <= innerWidth;
  })()`), 'Ordered steps must retain seven actions, context and a separate cited note without duplicate labels');
  await evaluate('document.querySelector(".chat-start:last-child .visual-answer button").click()');
  assert(await evaluate(`(() => {
    const answer=document.querySelector('.chat-start:last-child');
    return answer.querySelectorAll('.visual-answer-content p').length === 9
      && !answer.querySelector('[data-visual-item]') && answer.textContent.includes('Bước 7: Thao tác 7.')
      && (answer.textContent.match(/Lưu ý/g)||[]).length === 1;
  })()`), 'Text toggle must keep paragraph breaks for every step and preserve the note once');
  await evaluate('document.querySelector("#message").value="Steps text fixture"; document.querySelector("#chat-form").requestSubmit()');
  await sleep(1100);
  assert(await evaluate(`(() => {
    const answer=document.querySelector('.chat-start:last-child');
    return !answer.querySelector('.visual-answer') && answer.querySelectorAll('p').length === 9
      && answer.textContent.includes('Bước 7: Thao tác 7.');
  })()`), 'Text-only or rejected visual must still show each step in its own paragraph');
  assert(await evaluate(`(() => {
    const target = document.createElement('div');
    const metadata = {verification_status:'verified', citations:[{id:1}], visualization:{kind:'cards',language:'en',items:[
      {text:'<script>window.visualAttack=1</script>Safe',citations:[1]}, {text:'Other',citations:[1]}]}};
    const rendered=renderVisualAnswer(target,metadata,'Safe text');
    const safe=rendered && !target.querySelector('script') && !window.visualAttack;
    metadata.visualization.kind='steps'; metadata.visualization.notes=[{text:'Uncited note',citations:[999]}];
    const notesRejected=!renderVisualAnswer(document.createElement('div'),metadata,'Safe text');
    delete metadata.visualization.notes;
    metadata.visualization.kind='bar'; metadata.visualization.values=[NaN,2]; metadata.visualization.unit='x';
    return safe && notesRejected && !renderVisualAnswer(document.createElement('div'),metadata,'Safe text');
  })()`), 'Visual renderer must sanitize claims and reject invalid chart values');
  assert.equal(errors.length,0,errors.join('\n'));
  console.log('Browser checks passed: 6,503 nodes / 6,001 edges, all-page loading, WebGL, layout worker, node/edge inspection, GPU fallback/recovery, Graph/Chat, PDF upload/status, citations, mobile layout, reduced motion.');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{ws?.close();chrome?.kill('SIGTERM');server.closeAllConnections();server.close();});
