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
const effortLabels = ['Low', 'Medium', 'High'];
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
let composerDrop;

function finishComposerDrop() {
  if (!composerDrop) return;
  composerDrop.cancel();
  composerDrop = null;
  form.classList.remove('is-dropping');
  form.parentElement.style.removeProperty('height');
  form.parentElement.classList.remove('is-landing');
  form.inert = false;
}

// Keep the real form and its controls; only its surface travels to the dock.
function dropComposer(from) {
  if (reducedMotion.matches || !form.animate || !from.width) return;
  const dock = form.parentElement;
  const to = form.getBoundingClientRect();
  const radius = getComputedStyle(form).borderRadius;
  const padding = getComputedStyle(form).padding;
  const center = from.left + from.width / 2;
  const startY = from.top + from.height / 2;
  const endY = to.top + to.height / 2;
  dock.style.height = `${to.height}px`;
  form.classList.add('is-dropping');
  form.inert = true;
  const frame = (left, top, width, height, borderRadius, offset, easing = 'ease-in-out') => ({
    left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px`, borderRadius, transform: 'rotate(0deg)', offset, easing,
  });
  composerDrop = form.animate([
    { ...frame(from.left, from.top, from.width, from.height, radius, 0), padding },
    { ...frame(center - 29, startY - 29, 58, 58, '8% 65% 55% 65%', .32), transform: 'rotate(45deg)', padding: '0px' },
    { ...frame(center - 25, startY - 25, 50, 50, '8% 65% 55% 65%', .43, 'cubic-bezier(.5,0,.9,.6)'), transform: 'rotate(45deg)' },
    { ...frame(to.left + to.width / 2 - 26, endY - 26, 52, 52, '8% 65% 55% 65%', .72), transform: 'rotate(45deg)' },
    frame(to.left + to.width / 2 - 66, endY - 14, 132, 28, '50%', .8, 'cubic-bezier(.16,1,.3,1)'),
    { ...frame(to.left, to.top, to.width, to.height, radius, 1), padding },
  ], { duration: 1450, fill: 'both' });
  const flight = composerDrop;
  flight.finished.then(() => {
    if (composerDrop !== flight) return;
    finishComposerDrop();
    dock.classList.add('is-landing');
    if (!busy && !document.querySelector('#chat-view').hidden && window.matchMedia('(min-width: 601px)').matches) input.focus({ preventScroll: true });
  }).catch(() => {});
}

window.addEventListener('resize', finishComposerDrop);
document.querySelector('#task-graph').addEventListener('click', finishComposerDrop);
reducedMotion.addEventListener('change', () => { if (reducedMotion.matches) finishComposerDrop(); });

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
  if (appShell.classList.contains('chat-started')) return;
  const from = form.getBoundingClientRect();
  clearTimeout(expressionTimer);
  clearTimeout(sleepTimer);
  clearTimeout(holdTimer);
  clearTimeout(autoExpressionTimer);
  mascotStage.hidden = true;
  messages.hidden = false;
  appShell.classList.add('chat-started');
  dropComposer(from);
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

function renderVisualAnswer(element, data, plainText) {
  const visual = data?.visualization;
  if (data?.verification_status !== 'verified' || !['cards', 'steps', 'bar', 'checklist'].includes(visual?.kind)) return false;
  const items = visual.items;
  const context = visual.context ?? [], notes = visual.notes ?? [];
  const process = visual.kind === 'steps' || visual.kind === 'checklist';
  const citationIds = new Set((data.citations || []).map(source => source.id));
  const validItem = item => item && typeof item.text === 'string' && item.text.trim() && Array.isArray(item.citations)
    && item.citations.length && item.citations.every(id => Number.isInteger(id) && citationIds.has(id));
  if (!Array.isArray(items) || items.length < 2 || items.length > (process ? 12 : 6)
    || !Array.isArray(context) || !Array.isArray(notes) || items.length + context.length + notes.length > 20
    || (!process && (context.length || notes.length)) || ![...items, ...context, ...notes].every(validItem)) return false;
  if (visual.kind === 'bar' && (!Array.isArray(visual.values) || visual.values.length !== items.length ||
    visual.values.some(value => typeof value !== 'number' || !Number.isFinite(value) || value < 0) ||
    typeof visual.unit !== 'string' || visual.unit.length > 60)) return false;
  const vi = visual.language === 'vi';
  const toolbar = document.createElement('div'); toolbar.className = 'flex flex-wrap items-center justify-between gap-2 mb-3';
  const title = document.createElement('strong');
  title.textContent = ({cards: vi ? 'So sánh' : 'Comparison', steps: vi ? 'Các bước' : 'Steps',
    checklist: vi ? 'Các biện pháp' : 'Checklist', bar: vi ? 'Biểu đồ' : 'Chart'})[visual.kind];
  const toggle = document.createElement('button'); toggle.type = 'button'; toggle.className = 'btn btn-sm btn-ghost';
  toggle.setAttribute('aria-pressed', 'false');
  toolbar.append(title, toggle);
  const body = document.createElement('div'); body.className = 'visual-answer-content';
  let textMode = false;
  function draw() {
    toggle.textContent = textMode ? (vi ? 'Xem trực quan' : 'Visual view') : (vi ? 'Xem văn bản' : 'Text view');
    toggle.setAttribute('aria-pressed', String(textMode));
    if (textMode) { renderMarkdown(body, plainText); return; }
    body.classList.remove('markdown-body');
    body.replaceChildren();
    function renderSupportingItems(entries, position) {
      if (!entries.length) return;
      const group = document.createElement('div'); group.className = 'space-y-3 my-3';
      group.dataset.visualSupporting = position;
      entries.forEach(item => {
        const paragraph = document.createElement('div');
        renderMarkdown(paragraph, `${item.text} ${[...new Set(item.citations)].map(id => `[${id}](#cite-${id})`).join(' ')}`);
        group.append(paragraph);
      });
      body.append(group);
    }
    renderSupportingItems(context, 'context');
    const group = document.createElement('div');
    group.className = visual.kind === 'cards' ? 'grid grid-cols-1 sm:grid-cols-2 gap-3' : 'flex flex-col gap-3';
    const maximum = visual.kind === 'bar' ? Math.max(1, ...visual.values) : 1;
    items.forEach((item, index) => {
      const card = document.createElement('section'); card.className = 'card card-border card-sm bg-base-100 min-w-0';
      card.dataset.visualItem = String(index);
      const content = document.createElement('div'); content.className = 'card-body gap-2';
      if (visual.kind === 'steps' || visual.kind === 'checklist') {
        const step = document.createElement('strong');
        step.textContent = visual.kind === 'steps' ? `${vi ? 'Bước' : 'Step'} ${index + 1}` : `${index + 1}.`;
        content.append(step);
      }
      if (visual.kind === 'bar') {
        const value = document.createElement('output');
        value.textContent = `${new Intl.NumberFormat(vi ? 'vi' : 'en', {maximumFractionDigits: 6}).format(visual.values[index])} ${visual.unit}`.trim();
        const track = document.createElement('div'); track.className = 'bg-base-300 rounded overflow-hidden';
        track.setAttribute('role', 'img'); track.setAttribute('aria-label', value.textContent);
        const fill = document.createElement('div'); fill.className = 'bg-info h-3 rounded';
        fill.style.width = `${visual.values[index] / maximum * 100}%`; track.append(fill); content.append(value, track);
      }
      const claim = document.createElement('div');
      const text = visual.kind === 'steps' ? item.text.replace(
        new RegExp(`^\\s*(?:\\*{1,2})?(?:Bước|Step)\\s+${index + 1}\\s*[:.)-](?:\\*{1,2})?\\s*`, 'i'), '') : item.text;
      renderMarkdown(claim, `${text} ${[...new Set(item.citations)].map(id => `[${id}](#cite-${id})`).join(' ')}`);
      content.append(claim); card.append(content); group.append(card);
    });
    body.append(group);
    renderSupportingItems(notes, 'notes');
  }
  toggle.addEventListener('click', () => { textMode = !textMode; draw(); });
  element.classList.remove('markdown-body'); element.classList.add('visual-answer');
  element.style.whiteSpace = 'normal';
  element.replaceChildren(toolbar, body); draw();
  return true;
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
    if (!renderVisualAnswer(reply, metadata, answer)) renderMarkdown(reply, answer);
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
    if (!composerDrop && !document.querySelector('#chat-view').hidden && window.matchMedia('(min-width: 601px)').matches) input.focus({ preventScroll: true });
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
  window.dispatchEvent(new CustomEvent('workspace:citation', {detail: {source, sources}}));
}
