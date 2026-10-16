const mascot = document.querySelector('#mascot');
const mascotStage = document.querySelector('.mascot-stage');
const appShell = document.querySelector('.app-shell');
const status = document.querySelector('#mascot-status');
const form = document.querySelector('#chat-form');
const input = document.querySelector('#message');
const send = document.querySelector('#send');
const messages = document.querySelector('#messages');
const error = document.querySelector('#error');
const history = [];
const expressions = ['idle', 'wide', 'idle', 'wink'];
const effort = document.querySelector('#effort');
const sourceMode = document.querySelector('#source-mode');
const effortValues = ['low', 'medium', 'high'];
const effortLabels = ['Thấp', 'Vừa', 'Cao'];
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
let searchOverride = false;
let autoExpressionTimer;
let busy = false;
let expressionIndex = 1;
let expressionTimer;
let sleepTimer;
let holdTimer;
let held = false;
let large = false;

function setState(state, label) {
  if (mascotStage.hidden) return;
  mascot.dataset.state = state;
  status.textContent = label;
}

function resetSleep() {
  clearTimeout(sleepTimer);
  if (!busy && !mascotStage.hidden) sleepTimer = setTimeout(() => setState('sleep', 'Just resting my eyes… tap to wake me'), 45000);
}

function startConversation() {
  if (mascotStage.hidden) return;
  clearTimeout(expressionTimer);
  clearTimeout(sleepTimer);
  clearTimeout(holdTimer);
  clearTimeout(autoExpressionTimer);
  mascotStage.hidden = true;
  appShell.classList.add('chat-started');
}

function scheduleExpressions() {
  clearTimeout(autoExpressionTimer);
  if (busy || mascotStage.hidden || reducedMotion.matches) return;
  autoExpressionTimer = setTimeout(() => {
    if (!busy && !mascotStage.hidden && mascot.dataset.state !== 'sleep' && !holdTimer) {
      const state = expressions[expressionIndex++ % expressions.length];
      setState(state, state === 'wink' ? 'A little spark of curiosity.' : 'I’m here. What’s on your mind?');
    }
    scheduleExpressions();
  }, 3800);
}

effort.addEventListener('input', () => {
  document.querySelector('#effort-label').textContent = effortLabels[Number(effort.value)];
  effort.setAttribute('aria-valuetext', effortLabels[Number(effort.value)]);
});
reducedMotion.addEventListener('change', scheduleExpressions);
scheduleExpressions();

function touch() {
  if (busy) return;
  clearTimeout(expressionTimer);
  clearTimeout(autoExpressionTimer);
  const state = expressions[expressionIndex++ % expressions.length];
  setState(state, { wide: 'Oh! Hello there.', wink: 'You’ve got my attention.', idle: 'Tap to say hello · Hold to grow' }[state]);
  expressionTimer = setTimeout(() => {
    if (!busy) setState('idle', 'Tap to say hello · Hold to grow');
    scheduleExpressions();
  }, 2400);
  resetSleep();
}

mascot.addEventListener('pointermove', (event) => {
  if (reducedMotion.matches || event.pointerType !== 'mouse') return;
  const bounds = mascot.getBoundingClientRect();
  mascot.style.setProperty('--look-x', `${(event.clientX - bounds.left - bounds.width / 2) * .055}px`);
  mascot.style.setProperty('--look-y', `${(event.clientY - bounds.top - bounds.height / 2) * .04}px`);
});
mascot.addEventListener('pointerleave', () => {
  mascot.style.removeProperty('--look-x');
  mascot.style.removeProperty('--look-y');
});

mascot.addEventListener('pointerdown', (e) => {
  if (busy) return;
  held = false;
  mascot.setPointerCapture(e.pointerId);
  holdTimer = setTimeout(() => {
    held = true;
    large = !large;
    mascot.style.setProperty('--mascot-scale', large ? '1.25' : '0.85');
    setState('wide', large ? 'Big feelings, little friend.' : 'Small and happy to be here.');
    resetSleep();
  }, 450);
});
mascot.addEventListener('pointerup', () => { clearTimeout(holdTimer); holdTimer = null; });
mascot.addEventListener('pointercancel', () => { clearTimeout(holdTimer); holdTimer = null; held = true; });
mascot.addEventListener('click', () => {
  if (held) { held = false; return; }
  touch();
});
input.addEventListener('input', () => {
  if (!busy && mascot.dataset.state === 'sleep') setState('idle', 'I’m listening.');
  resetSleep();
});
resetSleep();

function renderMarkdown(element, text) {
  // Keep a readable fallback if the CDN libraries cannot load.
  if (!window.marked || !window.DOMPurify) {
    element.classList.remove('markdown-body');
    element.textContent = text;
    return;
  }
  const html = window.marked.parse(text, { gfm: true, breaks: true, async: false });
  const fragment = window.DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em',
      'del', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'hr', 'a',
      'table', 'thead', 'tbody', 'tr', 'th', 'td'],
    ALLOWED_ATTR: ['href', 'title', 'align', 'start'],
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
    RETURN_DOM_FRAGMENT: true,
  });
  fragment.querySelectorAll('a').forEach(link => {
    const href = link.getAttribute('href');
    if (!href) return;
    try {
      const url = new URL(href, window.location.href);
      if (href.startsWith('#cite-')) { link.className = 'citation-link'; link.target = ''; return; }
      if (!['http:', 'https:', 'mailto:'].includes(url.protocol)) {
        link.removeAttribute('href');
        return;
      }
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    } catch {
      link.removeAttribute('href');
    }
  });
  fragment.querySelectorAll('table').forEach(table => {
    table.classList.add('table', 'table-sm');
    table.querySelectorAll('thead th').forEach(cell => cell.setAttribute('scope', 'col'));
    const wrapper = document.createElement('div');
    wrapper.className = 'markdown-table-region overflow-x-auto';
    wrapper.tabIndex = 0;
    wrapper.setAttribute('role', 'region');
    wrapper.setAttribute('aria-label', 'Table / Bảng');
    table.replaceWith(wrapper);
    wrapper.append(table);
  });
  element.classList.add('markdown-body');
  element.replaceChildren(fragment);
}

function bubble(role, text) {
  messages.hidden = false;
  const row = document.createElement('div');
  row.className = `chat ${role === 'user' ? 'chat-end' : 'chat-start'}`;
  const label = document.createElement('div');
  label.className = 'chat-header';
  label.textContent = role === 'user' ? 'You' : 'Bloop';
  const content = document.createElement('div');
  content.className = 'chat-bubble';
  if (role === 'assistant') renderMarkdown(content, text);
  else content.textContent = text;
  row.append(label, content);
  messages.append(row);
  messages.scrollTop = messages.scrollHeight;
  return content;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  busy = true;
  startConversation();
  clearTimeout(expressionTimer);
  clearTimeout(sleepTimer);
  clearTimeout(holdTimer);
  send.disabled = true;
  input.disabled = true;
  error.hidden = true;
  form.setAttribute('aria-busy', 'true');
  setState('thinking', 'Hmm… let me think about that.');
  bubble('user', text);
  input.value = '';
  const reply = bubble('assistant', '');
  const requestRoute = searchOverride ? 'web' : sourceMode.value;
  showThinking(reply, requestRoute);
  effort.disabled = true;
  sourceMode.disabled = true;
  let answer = '';
  let done = false;
  let metadata = null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 150000);
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [...history.slice(-38), { role: 'user', content: text }], effort: effortValues[Number(effort.value)], route: requestRoute, ask_user: true }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(typeof detail.detail === 'string' ? detail.detail : 'Could not send this message. Please try again.');
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const consume = (block) => {
      const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
      if (!data) return;
      const item = JSON.parse(data);
      if (item.type === 'error') throw new Error(item.message);
      if (item.type === 'token') {
        answer += item.content;
        // Reveal only after the stream confirms the evidence-checked reply is complete.
      }
      if (item.type === 'result') metadata = item;
      if (item.type === 'done') done = true;
    };
    while (true) {
      const { value, done: ended } = await reader.read();
      buffer += decoder.decode(value, { stream: !ended });
      let end;
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        consume(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
      }
      if (ended) break;
    }
    if (buffer.trim()) consume(buffer);
    if (!done || !answer) throw new Error('The response was interrupted. Please try again.');
    renderMarkdown(reply, answer);
    revealReply(reply);
    messages.scrollTop = messages.scrollHeight;
    searchOverride = false;
    if (metadata) attachEvidence(reply, metadata, text);
    history.push({ role: 'user', content: text }, { role: 'assistant', content: answer });
    if (history.length > 38) history.splice(0, history.length - 38);
    setState('wink', 'Your turn. I’m right here.');
    if (!mascotStage.hidden) expressionTimer = setTimeout(() => { if (!busy) setState('idle', 'Tap to say hello · Hold to grow'); }, 2400);
  } catch (err) {
    controller.abort();
    reply.parentElement.remove();
    error.textContent = err.name === 'AbortError' ? 'The response took too long. Please try again.' : (err.message || 'Something went wrong. Please try again.');
    error.hidden = false;
    input.value = text;
    setState('idle', 'Let’s try that again.');
  } finally {
    clearTimeout(timeout);
    busy = false;
    send.disabled = false;
    input.disabled = false;
    effort.disabled = false;
    sourceMode.disabled = false;
    form.removeAttribute('aria-busy');
    if (window.matchMedia('(min-width: 601px)').matches) input.focus();
    resetSleep();
  }
});

function showThinking(reply, route) {
  reply.classList.add('thinking-bubble');
  reply.setAttribute('role', 'status');
  reply.setAttribute('aria-label', 'Bloop đang suy nghĩ');
  const avatar = document.createElement('span');
  avatar.className = 'thinking-avatar'; avatar.setAttribute('aria-hidden', 'true');
  const body = document.createElement('span'); body.className = 'mascot-body';
  for (const side of ['left', 'right']) {
    const eye = document.createElement('span'); eye.className = `eye eye-${side}`; body.append(eye);
  }
  avatar.append(body);
  const label = document.createElement('span'); label.className = 'thinking-label'; label.textContent = route === 'web' ? 'Searching the internet' : route === 'hybrid' ? 'Searching knowledge & internet' : 'Thinking';
  const dots = document.createElement('span'); dots.className = 'thinking-dots'; dots.setAttribute('aria-hidden', 'true');
  for (let i = 0; i < 3; i++) { const dot = document.createElement('span'); dot.textContent = '.'; dots.append(dot); }
  reply.append(avatar, label, dots);
}

function revealReply(reply) {
  reply.classList.remove('thinking-bubble');
  reply.removeAttribute('role'); reply.removeAttribute('aria-label');
  if (reducedMotion.matches) return;
  const walker = document.createTreeWalker(reply, NodeFilter.SHOW_TEXT, {
    acceptNode: node => node.parentElement.closest('pre, code') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  const count = nodes.reduce((sum, node) => sum + node.textContent.length, 0);
  const byWord = count > 6000;
  const segmenter = typeof Intl.Segmenter === 'function' ? new Intl.Segmenter(undefined, { granularity: byWord ? 'word' : 'grapheme' }) : null;
  const segments = nodes.map(node => ({ node, parts: segmenter ? Array.from(segmenter.segment(node.textContent), part => part.segment) : (byWord ? node.textContent.split(/(\s+)/) : Array.from(node.textContent)) }));
  const total = segments.reduce((sum, item) => sum + item.parts.length, 0);
  const step = Math.min(15, 3200 / Math.max(1, total));
  let index = 0;
  for (const { node, parts } of segments) {
    const fragment = document.createDocumentFragment();
    for (const part of parts) {
      const span = document.createElement('span'); span.className = 'reveal-character'; span.textContent = part;
      span.style.animationDelay = `${Math.round(index++ * step)}ms`; fragment.append(span);
    }
    node.replaceWith(fragment);
  }
  // Restore plain text nodes after the animation so long conversations stay light.
  setTimeout(() => {
    reply.querySelectorAll('.reveal-character').forEach(span => span.replaceWith(document.createTextNode(span.textContent)));
    reply.normalize();
  }, Math.ceil(total * step) + 300);
}

function attachEvidence(reply, data, originalQuestion) {
  reply.addEventListener('click', event => {
    const link = event.target.closest('.citation-link');
    if (!link) return;
    event.preventDefault();
    const id = Number(link.getAttribute('href').slice(6));
    const source = data.citations.find(c => c.id === id);
    if (source) showCitation(source, data.citations);
  });
  const info = document.createElement('small');
  info.className = 'evidence-usage';
  const usage = data.usage || {};
  const parts = [Number.isFinite(usage.elapsed_seconds) ? `${usage.elapsed_seconds}s` : ''];
  if (Number.isInteger(usage.input_tokens) && Number.isInteger(usage.output_tokens)) {
    parts.push(`↑ ${usage.input_tokens.toLocaleString()} in`, `↓ ${usage.output_tokens.toLocaleString()} out`);
    info.title = usage.token_usage_partial ? 'Token của các lần gọi API có báo cáo usage' : 'Token được API báo cáo';
  }
  info.textContent = parts.filter(Boolean).join(' · ');
  reply.parentElement.append(info);
  if (!data.clarification) return;
  const choices = document.createElement('div');
  choices.className = 'clarification-options';
  for (const option of data.clarification.options || []) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'btn btn-sm'; button.textContent = option;
    button.addEventListener('click', () => {
      if (busy) return;
      if (/internet/i.test(option)) {
        searchOverride = true;
        input.value = originalQuestion;
        form.requestSubmit();
      } else {
        input.value = /Bổ sung chi tiết|Add details/i.test(option) ? '' : option;
        input.focus();
      }
    });
    choices.append(button);
  }
  reply.parentElement.append(choices);
}

function showCitation(source, sources) {
  const container = document.querySelector('#citation-content');
  container.replaceChildren();
  const title = document.createElement('p');
  title.textContent = source.kind === 'graph' ? `${source.subject} → ${source.predicate} → ${source.object}` : source.title || source.subject;
  container.append(title);
  const provenance = document.createElement('p');
  provenance.textContent = String(source.document || source.source || source.url || 'Graph: nguồn gốc chưa được ghi nhận') + (source.page ? ` · Trang ${source.page}` : '');
  container.append(provenance);
  if (source.kind !== 'graph') {
    try {
      const url = new URL(source.url || source.uri);
      if (['http:', 'https:'].includes(url.protocol)) {
        const link = document.createElement('a'); link.href = url.href; link.textContent = 'Mở nguồn'; link.target = '_blank'; link.rel = 'noopener noreferrer'; container.append(link);
      }
    } catch {}
    const excerpt = document.createElement('blockquote'); excerpt.textContent = source.text; container.append(excerpt);
  } else {
    const excerpt = document.createElement('blockquote'); excerpt.textContent = source.text || source.source; container.append(excerpt);
    const facts = sources.filter(c => c.kind === 'graph');
    const names = [...new Set(facts.flatMap(c => [c.subject, c.object]))];
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', '0 0 600 400'); svg.classList.add('graph-explorer');
    svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Đồ thị các bằng chứng được trích dẫn');
    const positions = new Map(names.map((name,i) => [name, [300+220*Math.cos(i*2*Math.PI/names.length),200+150*Math.sin(i*2*Math.PI/names.length)]]));
    const detail = document.createElement('p'); detail.textContent = 'Chọn một nút để xem các quan hệ.';
    for (const fact of facts) {
      const a = positions.get(fact.subject), b = positions.get(fact.object);
      const line = document.createElementNS(svgNS,'line');
      for (const [k,v] of Object.entries({x1:a[0],y1:a[1],x2:b[0],y2:b[1]})) line.setAttribute(k,v);
      line.classList.add(fact.id === source.id ? 'selected-edge' : 'graph-edge');
      const tooltip = document.createElementNS(svgNS,'title'); tooltip.textContent = fact.predicate; line.append(tooltip); svg.append(line);
    }
    for (const name of names) {
      const [x,y] = positions.get(name);
      const node = document.createElementNS(svgNS,'g'); node.setAttribute('tabindex','0'); node.setAttribute('role','button'); node.setAttribute('aria-label',name);
      const circle = document.createElementNS(svgNS,'circle'); circle.setAttribute('cx',x); circle.setAttribute('cy',y); circle.setAttribute('r',12);
      const label = document.createElementNS(svgNS,'text'); label.setAttribute('x',x); label.setAttribute('y',y+27); label.setAttribute('text-anchor','middle'); label.textContent = name.length>25 ? name.slice(0,25)+'…' : name;
      const select = () => { detail.textContent = facts.filter(f => f.subject === name || f.object === name).map(f => `${f.subject} → ${f.predicate} → ${f.object}`).join('\n'); };
      node.addEventListener('click',select); node.addEventListener('keydown',e => { if (['Enter',' '].includes(e.key)) { e.preventDefault(); select(); } });
      node.append(circle,label); svg.append(node);
    }
    container.append(svg,detail);
  }
  document.querySelector('#citation-dialog').showModal();
}
