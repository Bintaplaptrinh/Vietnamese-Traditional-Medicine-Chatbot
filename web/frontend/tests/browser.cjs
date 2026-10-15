// Browser regression with a local SSE fixture; no model API requests.
const {spawn} = require('node:child_process');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const requests = [];
const uploads = [];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const server = http.createServer(async (req, res) => {
  if (req.url.startsWith('/api/graph')) {
    res.writeHead(200, {'Content-Type': 'application/json'});
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
  ws.addEventListener('message', e => {const m=JSON.parse(e.data); if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);} if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);});
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
  await sleep(3900);
  assert.notEqual(await evaluate('document.querySelector("#mascot").dataset.state'),'idle','Automatic expressions should change');
  await evaluate('document.querySelector("#effort").value=1; document.querySelector("#effort").dispatchEvent(new Event("input")); document.querySelector("#message").value="Chào Bloop"; document.querySelector("#chat-form").requestSubmit()');
  await sleep(150);
  assert.equal(await evaluate('document.querySelectorAll(".thinking-dots span").length'),3);
  assert(await evaluate('Boolean(document.querySelector(".thinking-avatar"))'));
  assert(await evaluate('document.querySelector("#source-mode").disabled'));
  fs.writeFileSync('/tmp/bloop-thinking.png',Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await sleep(900);
  assert(await evaluate('document.querySelectorAll(".reveal-character").length>0'));
  assert.equal(requests[0].effort,'medium');assert.equal(requests[0].route,'graph');assert.equal(requests[0].ask_user,true);
  assert.equal(await evaluate('document.querySelector("#source-mode").disabled'), false);
  const usage=await evaluate('document.querySelector(".evidence-usage").textContent');
  assert(usage.includes('3.37s') && usage.includes('1,234') && !usage.includes('model calls') && !usage.includes('graph'));
  await evaluate('document.querySelector(".citation-link").click()');
  assert(await evaluate('document.querySelector("#citation-dialog").open'));
  await evaluate('document.querySelector("#citation-dialog").close()');
  await sleep(3500);
  await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'));
  assert(await evaluate('document.querySelector("#message").getBoundingClientRect().width > 90'));
  assert(await evaluate('document.querySelector(".chat-start .chat-bubble").getBoundingClientRect().width > 200'), 'Assistant bubble must not collapse around metadata');
  fs.writeFileSync('/tmp/bloop-mobile.png',Buffer.from((await cdp('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await evaluate('Array.from(document.querySelectorAll(".clarification-options button")).find(b=>b.textContent.includes("internet")).click()');
  await sleep(950); assert.equal(requests[1].route,'web');assert.equal(requests[1].ask_user,true);
  await evaluate('document.querySelector("#message").value="Câu hỏi tiếp theo"; document.querySelector("#chat-form").requestSubmit()');
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
  assert.equal(errors.length,0,errors.join('\n'));
  console.log('Browser checks passed: Graph/Chat, ontology branches, graph selection, PDF upload/status, chat controls, citations, mobile layout, reduced motion.');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{ws?.close();chrome?.kill('SIGTERM');server.closeAllConnections();server.close();});
