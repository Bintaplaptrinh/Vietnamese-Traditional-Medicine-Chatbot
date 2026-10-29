import { ComposerControls, EvidenceDialog, PagePanel } from '../components/workspace';
import { Runtime } from '../components/runtime';

export default function Workspace() {
  return <>

  <aside className="task-sidebar" aria-label="Tasks">
    <span className="task-label">WORKSPACE</span>
    <ul className="menu menu-md">
      <li><button id="task-graph" className="menu-active" type="button" aria-controls="graph-view" aria-current="page"><span aria-hidden="true">◈</span> Graph</button></li>
      <li><button id="task-chat" type="button" aria-controls="chat-view"><span aria-hidden="true">◌</span> Chat</button></li>
    </ul>
  </aside>
  <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="/" aria-label="Bloop home"><span className="brand-symbol" aria-hidden="true">b.</span>bloop<span className="brand-dot">°</span></a>
      <span className="connection"><span aria-hidden="true"></span>YOUR LITTLE AI COMPANION</span>
    </header>
    <main>
      <PagePanel task="graph"><section id="graph-view" className="graph-view" aria-label="Đồ thị tri thức">
        <div className="graph-heading"><div><span className="eyebrow">KNOWLEDGE WORKSPACE</span><h1>Graph<span>.</span></h1><p>Khám phá tri thức và nguồn tài liệu.</p></div><span id="graph-count" className="badge">Đang tải…</span></div>
        <form id="graph-search" className="graph-toolbar">
          <label htmlFor="graph-branch" className="sr-only">Nhánh ontology</label>
          <select id="graph-branch" className="select select-sm"><option value="graph">Knowledge graph</option><option value="mesh">MeSH</option><option value="vietherbs">VietHerbs</option></select>
          <label htmlFor="graph-query" className="sr-only">Tìm khái niệm</label><input id="graph-query" className="input input-sm" placeholder="Tìm tên, thuật ngữ…" maxLength={500} />
          <button className="btn btn-sm" type="submit">Tìm</button><button id="graph-reset" className="btn btn-sm" type="button">Toàn cảnh</button>
          <button id="graph-fit" className="btn btn-sm" type="button">Vừa màn hình</button>
          <button id="graph-layout" className="btn btn-sm" type="button" disabled aria-pressed="false">Sắp xếp</button>
        </form>
        <p id="graph-status" className="graph-status" role="status" aria-live="polite"></p>
        <p id="graph-renderer" className="graph-status" role="status" aria-live="polite"></p>
        <div className="graph-workspace"><div id="knowledge-network" aria-label="Graph tương tác: kéo để di chuyển, cuộn để phóng to"></div><div id="graph-detail" className="graph-detail" aria-live="polite">Chọn một nút hoặc cạnh để xem thông tin và nguồn.</div>
          <button id="add-pdf" className="btn btn-circle add-pdf" type="button" aria-label="Thêm tài liệu PDF" title="Thêm tài liệu PDF">+</button><input id="pdf-file" type="file" accept=".pdf,application/pdf" hidden />
        </div>
        <p id="upload-status" role="status" aria-live="polite"></p>
        <details className="documents-panel"><summary>Tài liệu PDF <span id="document-count"></span></summary><ul id="document-list" className="document-list"></ul></details>
      </section>
      </PagePanel><PagePanel task="chat"><div id="chat-view" className="chat-view" hidden>
      <section className="mascot-stage" aria-label="Interactive mascot" hidden>
        <div className="intro"><span className="eyebrow">A LITTLE FRIEND. A BIG IMAGINATION.</span><h1>Hey, I’m Bloop<span>.</span></h1><p>Something on your mind? I’m all ears.</p></div>
        <div className="mascot-space">
          <div className="orbit orbit-one" aria-hidden="true"></div><div className="orbit orbit-two" aria-hidden="true"></div>
          <span className="spark spark-one" aria-hidden="true">✦</span><span className="spark spark-two" aria-hidden="true">+</span>
          <button id="mascot" className="mascot" data-state="idle" aria-label="Touch Bloop to change expression. Hold to change size.">
            <span className="mascot-body" aria-hidden="true">
              <span className="mascot-gloss"></span>
              <span className="face"><span className="cheek cheek-left"></span><span className="cheek cheek-right"></span><span className="eye eye-left"></span><span className="eye eye-right"></span><span className="mouth"></span></span>
            </span>
            <span className="mascot-bubble" aria-hidden="true"></span>
            <span className="sleep-mark" aria-hidden="true">z<span>z</span></span>
          </button>
          <div className="mascot-shadow" aria-hidden="true"></div>
        </div>
        <p id="mascot-status" className="mascot-status" aria-live="polite">Tap to say hello <span>·</span> Hold to grow</p>
      </section>
      <section className="conversation" aria-label="Chat with Bloop">
        <div className="chat-intro"><span className="eyebrow">A LITTLE SPACE. A FLOW OF IDEAS.</span><h1>What’s on your mind<span>?</span></h1><p>Let your thoughts flow.</p></div>
        <div id="messages" className="messages" role="log" aria-label="Conversation" aria-live="off" hidden></div>
        <p id="error" className="error-message" role="alert" hidden></p>
        <div className="composer-dock">
        <form id="chat-form" className="composer">
          <label className="sr-only" htmlFor="message">Your message</label>
          <input id="message" className="input input-ghost" placeholder="Tell me what’s on your mind…" autoComplete="off" maxLength={1048576} required />
          <ComposerControls />
          <button id="send" className="btn btn-primary btn-circle" type="submit" aria-label="Send message"><svg width="21" height="21" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg></button>
        </form>
        </div>
        <p className="composer-note">A small space for your big ideas.</p>
      </section>
      </div>
    </PagePanel></main>
    <footer><span>MADE FOR A LITTLE CONNECTION</span><span>Powered by Gemma <span className="footer-dot">✦</span></span></footer>
  </div>
<EvidenceDialog /><Runtime /></>;
}
