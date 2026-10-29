'use client';
import { useEffect } from 'react';

let startup: Promise<void> | undefined;
function loadScript(src: string) {
  return new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Không thể tải ${src}. Vui lòng tải lại trang.`));
    document.body.append(script);
  });
}

// The existing graph renderer and SSE controller keep their DOM, worker and history.
// Load classic scripts in order because they share lexical bindings.
export function Runtime() {
  useEffect(() => {
    startup ??= (async () => {
      for (const src of ['/legacy/marked.js', '/legacy/purify.js', '/legacy/app.js',
        '/assets/graph-gpu.min.js', '/legacy/graph-renderer.js', '/legacy/graph.js']) {
        await loadScript(src);
      }
      window.dispatchEvent(new Event('workspace:ready'));
    })();
    startup.catch(error => {
      const status = document.querySelector('#graph-status');
      if (status) status.textContent = error.message;
    });
  }, []);
  return null;
}
