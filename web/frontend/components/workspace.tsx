'use client';

import { useEffect, useRef, useState, type ReactNode, type CSSProperties } from 'react';
import { flushSync } from 'react-dom';
import { Slide } from '@animate-ui/react/primitives/effects/slide';
import { Fade } from '@animate-ui/react/primitives/effects/fade';
import { AnimatePresence, useReducedMotion } from 'motion/react';

export function PagePanel({ task, children }: { task: string; children: ReactNode }) {
  const [active, setActive] = useState(task === 'graph');
  const reduce = useReducedMotion();
  useEffect(() => {
    const change = (event: Event) => flushSync(() => setActive((event as CustomEvent<string>).detail === task));
    window.addEventListener('workspace:task', change);
    return () => window.removeEventListener('workspace:task', change);
  }, [task]);
  return <Fade className={`page-panel page-panel-${task}`} hidden={!active}
    initial={false} animate={{ opacity: active ? 1 : 0, y: active || reduce ? 0 : 16 }}
    transition={{ duration: reduce ? 0 : 0.28, ease: [0.22, 1, 0.36, 1] }}>
    {children}
  </Fade>;
}

const modes = [
  { value: 'graph', icon: '◈', title: 'Knowledge', detail: 'Chỉ tìm trong kho tri thức của bạn' },
  { value: 'web', icon: '◎', title: 'Internet', detail: 'Tìm và đối chiếu nguồn trên internet' },
  { value: 'hybrid', icon: '✦', title: 'Hybrid', detail: 'Kết hợp kho tri thức và internet' },
];
const levels = [
  { title: 'Low', hint: 'Tra cứu nhanh · 1 vòng', icon: '↗' },
  { title: 'Medium', hint: 'Đối chiếu thêm · 2 vòng', icon: '◒' },
  { title: 'High', hint: 'Nghiên cứu sâu · 3 vòng', icon: '✦' },
];

function AstralField() {
  const field = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const input = document.querySelector('#message');
    let timer: ReturnType<typeof setTimeout>;
    const energize = () => {
      field.current?.classList.add('is-typing');
      clearTimeout(timer);
      timer = setTimeout(() => field.current?.classList.remove('is-typing'), 900);
    };
    input?.addEventListener('input', energize);
    return () => { clearTimeout(timer); input?.removeEventListener('input', energize); };
  }, []);
  return <span ref={field} className="astral-field" aria-hidden="true">
    <span className="astral-haze" />
    {Array.from({ length: 32 }, (_, index) => <i key={index} className={index % 7 === 0 ? 'astral-star is-cross' : 'astral-star'}
      style={{ '--star-x': `${(index * 37 + 9) % 100}%`, '--star-y': `${(index * 23 + 17) % 100}%`,
        '--star-size': `${index % 7 === 0 ? 5 : 1 + index % 3}px`, '--star-delay': `${-index * 0.47}s`,
        '--star-time': `${5 + index % 6}s` } as CSSProperties} />)}
  </span>;
}

export function ComposerControls() {
  const [level, setLevel] = useState(0);
  const [effortOpen, setEffortOpen] = useState(false);
  const effortRoot = useRef<HTMLDivElement>(null);
  const effortTrigger = useRef<HTMLButtonElement>(null);
  const reduce = useReducedMotion();
  const [mode, setMode] = useState('graph');
  const [open, setOpen] = useState(false);
  const [disabled, setDisabled] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const select = useRef<HTMLSelectElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const chosen = modes.find(item => item.value === mode)!;
  useEffect(() => {
    const element = select.current!;
    const observer = new MutationObserver(() => {
      setDisabled(element.disabled);
      if (element.disabled) { setOpen(false); setEffortOpen(false); }
    });
    observer.observe(element, { attributes: true, attributeFilter: ['disabled'] });
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
      if (!effortRoot.current?.contains(event.target as Node)) setEffortOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    return () => { observer.disconnect(); document.removeEventListener('pointerdown', outside); };
  }, []);
  function choose(value: string) {
    if (select.current?.disabled) return;
    select.current!.value = value;
    select.current!.dispatchEvent(new Event('change', { bubbles: true }));
    setMode(value); setOpen(false); trigger.current?.focus();
  }
  return <>
    {level === 2 && <AstralField />}
    <div data-level={['low', 'medium', 'high'][level]} ref={effortRoot} className="effort-control dropdown dropdown-end"
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setEffortOpen(false); }}
      onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); setEffortOpen(false); effortTrigger.current?.focus(); }
      }}>
      <button ref={effortTrigger} type="button" className="btn effort-trigger" disabled={disabled}
        aria-expanded={effortOpen} aria-controls="effort-options" aria-label={`Effort: ${levels[level].title}`}
        onClick={() => { setEffortOpen(value => !value); setOpen(false); }}>
        <svg className="effort-sparkle" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" aria-hidden="true"><path d="m10 3 2.2 6.8L19 12l-6.8 2.2L10 21l-2.2-6.8L1 12l6.8-2.2L10 3Z"/><path d="m19 2 .9 2.1L22 5l-2.1.9L19 8l-.9-2.1L16 5l2.1-.9L19 2Z"/></svg>
        <span>{levels[level].title}</span>
      </button>
      <Fade id="effort-options" className="dropdown-content effort-options" hidden={!effortOpen}
        initial={false} animate={{ opacity: effortOpen ? 1 : 0, y: effortOpen || reduce ? 0 : -6 }}
        transition={{ duration: reduce ? 0 : 0.18 }}>
        <div className="effort-caption"><label htmlFor="effort">Effort</label>
          <output id="effort-label" htmlFor="effort">{levels[level].title}</output><span className="effort-help" title="Higher effort spends more time checking sources" aria-label="Higher effort spends more time checking sources">?</span></div>
        <div className="effort-ends" aria-hidden="true"><span>Faster</span><span>Smarter</span></div>
        <div className="effort-rail" style={{ '--effort-position': `${level * 50}%` } as CSSProperties}>
          <span className="effort-rail-fill" aria-hidden="true" />
          <span className="effort-dots" aria-hidden="true"><i /><i /><i /></span>
          <input id="effort" className="range range-xs" type="range" min="0" max="2" step="1" defaultValue="0"
            aria-label="Effort" aria-valuetext={levels[level].title} aria-describedby="effort-description"
            onInput={event => setLevel(Number(event.currentTarget.value))} />
        </div>
        <span id="effort-description" className="effort-description">{levels[level].hint}</span>
      </Fade>
    </div>
    <div ref={root} className="source-picker dropdown dropdown-top dropdown-end"
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}
      onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); setOpen(false); trigger.current?.focus(); }
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
          event.preventDefault(); setOpen(true);
          requestAnimationFrame(() => {
            const items = Array.from(root.current!.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'));
            const index = items.indexOf(document.activeElement as HTMLButtonElement);
            items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 :
              (index + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length]?.focus();
          });
        }
      }}>
      <select id="source-mode" ref={select} hidden defaultValue="graph" aria-label="Nguồn thông tin"
        onChange={event => setMode(event.currentTarget.value)}>
        {modes.map(item => <option key={item.value} value={item.value}>{item.title}</option>)}
      </select>
      <button ref={trigger} type="button" className="btn source-trigger" disabled={disabled}
        aria-haspopup="menu" aria-expanded={open} aria-controls="source-options" onClick={() => { setOpen(value => !value); setEffortOpen(false); }}>
        <span className="mode-icon" aria-hidden="true">{chosen.icon}</span><span>{chosen.title}</span>
        <span className={`mode-chevron ${open ? 'is-open' : ''}`} aria-hidden="true">⌃</span>
      </button>
      <AnimatePresence>
        {open && <Slide key="source-options" id="source-options" role="menu" aria-label="Nguồn thông tin"
          className="dropdown-content source-options" direction="up" offset={8}
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }}>
          <p className="source-heading">NGUỒN TRẢ LỜI</p>
          {modes.map(item => <button key={item.value} type="button" role="menuitemradio"
            aria-checked={mode === item.value} className={`source-option ${mode === item.value ? 'is-selected' : ''}`}
            onClick={() => choose(item.value)}>
            <span className="mode-icon" aria-hidden="true">{item.icon}</span>
            <span><strong>{item.title}</strong><small>{item.detail}</small></span>
            <span className="mode-check" aria-hidden="true">{mode === item.value ? '✓' : ''}</span>
          </button>)}
          <p className="source-footnote">Mỗi câu trả lời đều đi kèm nguồn dẫn chứng.</p>
        </Slide>}
      </AnimatePresence>
    </div>
  </>;
}

type Citation = {
  id: number; kind: string; title?: string; subject?: string; predicate?: string;
  object?: string; document?: string; source?: string; url?: string; uri?: string;
  page?: number; text?: string;
};
function safeUrl(value?: string) {
  try { const url = new URL(value || ''); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}

export function EvidenceDialog() {
  const dialog = useRef<HTMLDialogElement>(null);
  const [data, setData] = useState<{ source: Citation; sources: Citation[] } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    const show = (event: Event) => { setData((event as CustomEvent).detail); setSelected(null); };
    window.addEventListener('workspace:citation', show);
    return () => window.removeEventListener('workspace:citation', show);
  }, []);
  useEffect(() => { if (data && !dialog.current?.open) dialog.current?.showModal(); }, [data]);
  const source = data?.source;
  const url = safeUrl(source?.url || source?.uri);
  const facts = data?.sources.filter(item => item.kind === 'graph') || [];
  const names = [...new Set(facts.flatMap(item => [item.subject, item.object]).filter(Boolean))] as string[];
  return <dialog ref={dialog} id="citation-dialog" className="modal evidence-modal" aria-labelledby="citation-title"
    onClose={() => setData(null)} onClick={event => { if (event.target === dialog.current) dialog.current.close(); }}>
    <Fade key={source?.id ?? 'empty'} className="modal-box citation-box">
      <header className="evidence-header"><div><span className="eyebrow">KIỂM TRA NGUỒN</span>
        <h2 id="citation-title">Dẫn chứng<span>.</span></h2></div>
        <form method="dialog"><button className="btn btn-circle btn-ghost" aria-label="Đóng dẫn chứng">×</button></form>
      </header>
      {source && <div id="citation-content">
        <div className="evidence-meta"><span className="badge">{source.kind === 'graph' ? '◈ Knowledge graph' : '◎ Nguồn tài liệu'}</span>
          <span>Trích dẫn {source.id}</span>{source.page && <span>Trang {source.page}</span>}</div>
        <h3 className="evidence-title">{source.kind === 'graph' ? `${source.subject} → ${source.predicate} → ${source.object}` : source.title || source.subject || 'Tài liệu nguồn'}</h3>
        <p className="evidence-provenance">{source.document || source.source || source.url || 'Chưa ghi nhận thông tin nguồn'}</p>
        <div className="evidence-section-label">TRÍCH ĐOẠN GỐC</div>
        <blockquote>{source.text || source.source || 'Nguồn này chưa có đoạn trích nguyên văn.'}</blockquote>
        {!!facts.length && <section className="evidence-relations" aria-label="Quan hệ được trích dẫn">
          <div className="evidence-section-label">KẾT NỐI TRI THỨC <span>{facts.length} quan hệ</span></div>
          <div className="evidence-nodes">{names.map(name => <button key={name} type="button"
            className={`btn btn-sm ${selected === name ? 'btn-active' : ''}`} aria-pressed={selected === name}
            onClick={() => setSelected(selected === name ? null : name)}>{name}</button>)}</div>
          <ul>{facts.filter(item => !selected || item.subject === selected || item.object === selected).map(item =>
            <li key={item.id} className={item.id === source.id ? 'selected-relation' : ''}>
              <span>{item.subject}</span><span className="relation-predicate">{item.predicate} →</span><span>{item.object}</span>
            </li>)}</ul>
        </section>}
        <footer className="evidence-footer"><span>Đối chiếu trích đoạn với tài liệu gốc.</span>
          {url && <a className="btn btn-sm" href={url} target="_blank" rel="noopener noreferrer">Mở nguồn ↗</a>}</footer>
      </div>}
    </Fade>
  </dialog>;
}
