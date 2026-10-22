/* Trình duyệt mã toàn màn hình, kiểu kho Git: cây thư mục, mở tệp (có chú thích bằng chứng), tìm kiếm tệp/nội dung, nhảy tới định nghĩa.
   Dữ liệu từ /api/runs/<id>/code/*: chỉ gồm phần mã nằm trong phạm vi của lần chạy (bản sao tại commit + chỉ mục), không phải đĩa tuỳ ý.
   Nội dung mã là dữ liệu KHÔNG TIN CẬY: luôn đi qua html`` (tự thoát), không bao giờ được thực thi. */
import { rowsHtml, scrollToLine, SEVERITY } from './code-view.js';
import { $, $$, api, app, empty, fmt, html, icon, mount, on, toast } from './lib.js';
import { flagMenu } from './review.js';

const MODES = [['all', 'Tất cả'], ['ev', 'Có bằng chứng'], ['read', 'Agent đã đọc']];
let EX = null;

export async function openExplorer(runId, { path = null, line = null } = {}) {
  closeExplorer();
  const [tr, run] = await Promise.all([api(`/api/runs/${runId}/code`), api(`/api/runs/${runId}`)]);
  EX = { canReview: !app.readOnly && !['queued', 'running'].includes(run.status), id: runId, files: tr.files, source: tr.source, mode: tr.files.some((f) => f.annotations) ? 'ev' : 'all', nameQ: '', expanded: new Set(), cur: null, d: null, show: { bad: true, ok: true, info: true, hit: true, read: true }, hist: [], hi: -1, panel: 'sym', results: null, sym: null, busy: false };
  const el = document.createElement('div'); el.id = 'explorer'; el.className = 'explorer'; document.body.appendChild(el); EX.el = el;
  wire(el);
  const first = path || tr.files.find((f) => f.bad)?.path || tr.files.find((f) => f.annotations)?.path || tr.files[0]?.path;
  draw();
  if (first) await go(first, line, true);
  document.addEventListener('keydown', keys); document.addEventListener('keyup', keys); window.addEventListener('rfcv:rv', redraw);
}
const redraw = () => { if (EX) draw(); };  // cờ bằng chứng đổi ở nơi khác (hoặc ngay trong thẻ chú thích)
export function closeExplorer() {
  if (!EX) return;
  EX.el.remove(); document.removeEventListener('keydown', keys); document.removeEventListener('keyup', keys); window.removeEventListener('rfcv:rv', redraw); EX = null;
}
function keys(e) {
  if (!EX) return;
  EX.el.classList.toggle('ctrl', e.ctrlKey || e.metaKey);
  if (e.type === 'keydown' && e.key === 'Escape' && !document.querySelector('#cmdk:not([hidden])')) { closeExplorer(); }
  if (e.type === 'keydown' && e.altKey && e.key === 'ArrowLeft') back(-1);
  if (e.type === 'keydown' && e.altKey && e.key === 'ArrowRight') back(1);
}

/* ---------- điều hướng ---------- */
async function load(path, opts = {}) {
  const q = new URLSearchParams({ path }); if (opts.around) q.set('around', opts.around); if (opts.start) q.set('start', opts.start); if (opts.end) q.set('end', opts.end);
  EX.d = await api(`/api/runs/${EX.id}/code/file?${q}`); EX.cur = path;
}
async function go(path, line = null, fresh = false) {
  try { await load(path, { around: line || undefined }); } catch (e) { toast(e.message, 'bad'); return; }
  const at = line || EX.d.annotations.find((a) => a.severity === 'bad')?.line_start || EX.d.annotations[0]?.line_start || EX.d.start;
  if (!fresh) EX.hist = EX.hist.slice(0, EX.hi + 1);
  if (fresh || EX.hist[EX.hi]?.path !== path || EX.hist[EX.hi]?.line !== at) { EX.hist.push({ path, line: at }); EX.hi = EX.hist.length - 1; }
  path.split('/').slice(0, -1).reduce((acc, p) => { const k = acc ? acc + '/' + p : p; EX.expanded.add(k); return k; }, '');
  draw(); requestAnimationFrame(() => scrollToLine(at, false, EX.el));
}
async function back(step) {
  const i = EX.hi + step; if (i < 0 || i >= EX.hist.length) return;
  EX.hi = i; const h = EX.hist[i]; await load(h.path, { around: h.line }); draw(); requestAnimationFrame(() => scrollToLine(h.line, false, EX.el));
}

/* ---------- cây ---------- */
function buildTree(files) {
  const root = { name: '', path: '', kids: new Map(), files: [] };
  for (const f of files) {
    const parts = f.path.split('/'); let n = root;
    parts.slice(0, -1).forEach((p, i) => { const k = parts.slice(0, i + 1).join('/'); if (!n.kids.has(p)) n.kids.set(p, { name: p, path: k, kids: new Map(), files: [] }); n = n.kids.get(p); });
    n.files.push(f);
  }
  return root;
}
const visible = (f) => (EX.mode === 'ev' ? f.annotations > 0 : EX.mode === 'read' ? f.read > 0 : true) && (!EX.nameQ || f.path.toLowerCase().includes(EX.nameQ.toLowerCase()));
function stats(n) { let bad = 0, ann = 0, read = 0, files = 0; const walk = (x) => { x.files.filter(visible).forEach((f) => { bad += f.bad; ann += f.annotations; read += f.read ? 1 : 0; files++; }); x.kids.forEach(walk); }; walk(n); return { bad, ann, read, files }; }
function treeHtml(n, depth = 0) {
  const dirs = [...n.kids.values()].sort((a, b) => a.name.localeCompare(b.name)), out = [];
  for (const d of dirs) {
    const s = stats(d); if (!s.files) continue;
    const open = EX.expanded.has(d.path) || !!EX.nameQ;
    out.push(html`<div class="tn dir" style="padding-left:${8 + depth * 14}px" data-dir="${d.path}">${icon('chevron', 12, open ? 'open' : '')}${icon('folder', 14)}<span class="nm">${d.name}</span>${s.bad ? html`<span class="bd bad">${s.bad}</span>` : s.ann ? html`<span class="bd ok">${s.ann}</span>` : ''}</div>`);
    if (open) out.push(treeHtml(d, depth + 1));
  }
  for (const f of n.files.filter(visible).sort((a, b) => a.path.localeCompare(b.path))) {
    out.push(html`<div class="tn file ${f.path === EX.cur ? 'on' : ''}" style="padding-left:${22 + depth * 14}px" data-file="${f.path}" title="${f.path}">${icon('file', 13)}<span class="nm">${f.path.split('/').pop()}</span>${f.bad ? html`<span class="bd bad" title="${f.bad} chỗ lệch đặc tả">✗ ${f.bad}</span>` : f.annotations ? html`<span class="bd ok" title="${f.annotations} chú thích">${f.annotations}</span>` : ''}${f.read ? html`<i class="rdot" title="Agent đã đọc ${f.read} dòng"></i>` : ''}</div>`);
  }
  return html`${out}`;
}

/* ---------- vẽ ---------- */
function viewer() {
  const d = EX.d; if (!d) return empty('Chọn một tệp ở cây bên trái');
  const c = EX, anns = d.annotations, cnt = (s) => anns.filter((a) => a.severity === s).length;
  const vis = anns.filter((a) => c.show[a.severity]);
  const rangeOf = (n) => { let sev = null; for (const a of vis) if (n >= a.line_start && n <= a.line_end && a.kind !== 'verdict') { if (a.severity === 'bad') return 'bad'; sev = sev === 'ok' ? 'ok' : a.severity; } return sev; };
  const endAt = new Map(); vis.forEach((a) => { (endAt.get(a.line_end) || endAt.set(a.line_end, []).get(a.line_end)).push(a); });
  const parts = d.path.split('/');
  return html`<div class="ex-bar"><div class="crumb">${parts.map((p, i) => html`${i ? html`<i>/</i>` : ''}<span class="${i === parts.length - 1 ? 'last' : ''}">${p}</span>`)}</div>
      <span class="chip">${fmt.int(d.total)} dòng</span><span class="chip ${d.source === 'trace' ? 'warn' : 'ok'}">${d.source === 'trace' ? 'chỉ dòng agent đã đọc' : 'toàn bộ tệp'}</span>
      <span class="grow"></span>${['bad', 'ok', 'info'].map((s) => html`<button class="fchip ${c.show[s] ? 'on ' + s : ''}" data-xf="${s}">${icon(SEVERITY[s][0], 12)}${SEVERITY[s][1]} <b>${cnt(s)}</b></button>`)}
      <button class="fchip ${c.show.hit ? 'on hit' : ''}" data-xf="hit">${icon('zap', 12)}Độ phủ <b>${d.hits.length}</b></button><button class="fchip ${c.show.read ? 'on' : ''}" data-xf="read" title="Đánh dấu dòng agent đã đọc">${icon('eye', 12)}Agent đã đọc <b>${d.read.length}</b></button></div>
    <div class="ex-code codeframe codeview" id="ex-code">${d.start > 1 ? html`<button class="more" data-more="-1">⋯ tải ${Math.min(3000, d.start - 1)} dòng phía trên (đang từ dòng ${d.start})</button>` : ''}${rowsHtml(d, { rangeOf, endAt, show: c.show, matches: new Set(), q: '', trace: d.source === 'trace', flag: (a) => flagMenu(EX.id, a.requirement_id, a.evidence_id, EX.canReview) })}${d.end < d.total && d.source !== 'trace' ? html`<button class="more" data-more="1">⋯ tải thêm phía dưới (còn ${fmt.int(d.total - d.end)} dòng)</button>` : ''}</div>
    <div class="legend-line"><span><b style="color:var(--critical-text)">✗</b> lệch đặc tả</span><span><b style="color:var(--good-text)">✓</b> khớp</span><span>${icon('zap', 12)} thực thi khi kiểm thử kích hoạt</span><span><i class="rdot"></i> dòng agent đã đọc</span><span><kbd>Ctrl</kbd>+bấm hoặc bấm đúp một tên hàm để tra định nghĩa · <kbd>Alt</kbd>+←/→ quay lại/tiến</span></div>`;
}
function panel() {
  const d = EX.d, s = EX.sym, r = EX.results;
  const body = EX.panel === 'sym' ? (d?.symbols?.length ? html`<div class="pl">${d.symbols.map((x) => html`<a href="#" class="pi" data-line="${x.line_start}"><span class="k ${x.kind}">${x.kind === 'function' ? 'ƒ' : x.kind === 'macro' ? '#' : x.kind[0]}</span><span class="nm">${x.name}</span><span class="muted mono">${x.line_start}</span></a>`)}</div>` : html`<div class="muted small pad">Không có ký hiệu (chưa có chỉ mục mã hoặc tệp không phải mã).</div>`)
    : EX.panel === 'ann' ? html`<div class="pl">${d.annotations.length ? d.annotations.map((a) => html`<a href="#" class="pi" data-line="${a.line_start}"><span class="k ${a.severity}">${a.severity === 'bad' ? '✗' : a.severity === 'ok' ? '✓' : 'i'}</span><span class="nm">${a.title}</span><span class="muted mono">${a.line_start}</span></a>`) : html`<div class="muted small pad">Tệp này không có chú thích bằng chứng.</div>`}</div>`
      : EX.panel === 'def' ? (s ? defPanel(s) : html`<div class="muted small pad">Bấm đúp hoặc Ctrl+bấm một tên hàm/macro trong mã để tra.</div>`)
        : r ? resultsPanel(r) : html`<div class="muted small pad">Gõ vào ô tìm kiếm rồi nhấn Enter để tìm tên tệp và nội dung.</div>`;
  return html`<div class="tabs mini">${[['sym', 'Ký hiệu'], ['ann', 'Chú thích'], ['def', 'Tra cứu'], ['res', 'Tìm kiếm']].map(([k, l]) => html`<button data-panel="${k}" class="${EX.panel === k ? 'on' : ''}">${l}</button>`)}</div>${body}`;
}
const loc = (f, l) => html`<span class="mono small">${f}:${l}</span>`;
function defPanel(s) {
  if (!s.indexed) return html`<div class="muted small pad">Lần chạy này chưa có chỉ mục mã nên không tra được ký hiệu.</div>`;
  const sec = (title, rows) => (rows.length ? html`<h5>${title} <span class="muted">${rows.length}</span></h5><div class="pl">${rows}</div>` : '');
  return html`<div class="pad"><b class="mono" style="font-size:14px">${s.name}</b></div>
    ${sec('Định nghĩa', s.definitions.map((x) => html`<a href="#" class="pi" data-open="${x.file}|${x.line_start}"><span class="k ${x.kind}">${x.kind === 'function' ? 'ƒ' : x.kind[0]}</span><span class="nm">${loc(x.file, x.line_start)} <span class="muted">${x.kind}</span></span></a>`))}
    ${sec('Được gọi bởi', s.callers.map((x) => html`<a href="#" class="pi" data-open="${x.file}|${x.line}"><span class="k">←</span><span class="nm"><b>${x.caller}</b> ${loc(x.file, x.line)}</span></a>`))}
    ${sec('Gọi tới', s.callees.map((x) => html`<a href="#" class="pi" data-sym="${x.callee}"><span class="k">→</span><span class="nm"><b>${x.callee}</b></span><span class="muted mono">${x.line}</span></a>`))}
    ${sec('Tham chiếu', s.references.map((x) => html`<a href="#" class="pi" data-open="${x.file}|${x.line}"><span class="k">·</span><span class="nm">${loc(x.file, x.line)} <span class="muted">trong ${x.container}</span></span></a>`))}
    ${s.definitions.length + s.references.length + s.callers.length === 0 ? html`<div class="muted small pad">Không thấy ký hiệu này trong chỉ mục (có thể là ký hiệu bên ngoài phạm vi mã).</div>` : ''}`;
}
function resultsPanel(r) {
  return html`${r.files.length ? html`<h5>Tên tệp <span class="muted">${r.files.length}</span></h5><div class="pl">${r.files.map((p) => html`<a href="#" class="pi" data-open="${p}|"><span class="k">${icon('file', 12)}</span><span class="nm mono small">${p}</span></a>`)}</div>` : ''}
    <h5>Nội dung <span class="muted">${r.matches.length}${r.truncated ? '+' : ''}</span></h5><div class="pl">${r.matches.map((m) => html`<a href="#" class="pi col" data-open="${m.path}|${m.line}"><span class="mono small muted">${m.path}:${m.line}</span><code class="snip">${m.text}</code></a>`)}</div>
    ${!r.matches.length && !r.files.length ? html`<div class="muted small pad">Không có kết quả.</div>` : ''}${r.truncated ? html`<div class="muted small pad">Kết quả bị cắt (quá nhiều hoặc quá lâu). Hãy gõ cụ thể hơn.</div>` : ''}`;
}
function draw() {
  if (!EX) return;
  const keep = { tree: $('.ex-tree', EX.el)?.scrollTop || 0, code: $('#ex-code', EX.el)?.scrollTop || 0 }, hadCode = !!$('#ex-code', EX.el);
  const root = buildTree(EX.files);
  mount(EX.el, html`<div class="ex-head"><button class="btn sm" data-xclose>${icon('x', 14)}Đóng</button><b>Trình duyệt mã</b><span class="muted small">${EX.files.length} tệp · ${EX.source === 'index' ? 'chỉ mục mã của lần chạy' : EX.source === 'workspace' ? 'bản sao phạm vi tại commit' : 'chỉ các dòng agent đã đọc'}</span><span class="grow"></span>
      <button class="icon-btn" data-xback title="Quay lại (Alt+←)" ${EX.hi > 0 ? '' : 'disabled'}>${icon('chevron', 16, 'flip')}</button><button class="icon-btn" data-xfwd title="Tiến (Alt+→)" ${EX.hi < EX.hist.length - 1 ? '' : 'disabled'}>${icon('chevron', 16)}</button>
      <span class="search-mini wide">${icon('search', 13)}<input type="search" id="ex-q" placeholder="Tìm tên tệp (gõ) hoặc nội dung / ký hiệu (Enter)…" value="${EX.nameQ}" aria-label="Tìm trong mã"></span></div>
    <div class="ex-body"><aside class="ex-tree"><div class="seg mini" style="margin:8px">${MODES.map(([k, l]) => html`<button data-xmode="${k}" class="${EX.mode === k ? 'on' : ''}">${l}</button>`)}</div><div class="tree">${treeHtml(root)}</div></aside>
      <section class="ex-main">${viewer()}</section><aside class="ex-side">${panel()}</aside></div>`);
  $('.ex-tree', EX.el).scrollTop = keep.tree; if (hadCode && EX.d) $('#ex-code', EX.el).scrollTop = keep.code;
}

/* ---------- tra cứu ---------- */
async function lookup(name, jump = false) {
  if (!/^[A-Za-z_]\w*$/.test(name)) return;
  EX.sym = await api(`/api/runs/${EX.id}/code/symbol?name=${encodeURIComponent(name)}`); EX.panel = 'def';
  const defs = EX.sym.definitions.filter((x) => x.kind !== 'prototype');
  if (jump && defs.length === 1) { await go(defs[0].file, defs[0].line_start); return; }
  draw();
}
function wordAt(e) {
  let node, off;
  if (document.caretPositionFromPoint) { const p = document.caretPositionFromPoint(e.clientX, e.clientY); node = p?.offsetNode; off = p?.offset; }
  else if (document.caretRangeFromPoint) { const r = document.caretRangeFromPoint(e.clientX, e.clientY); node = r?.startContainer; off = r?.startOffset; }
  if (!node || node.nodeType !== 3) return null;
  const t = node.textContent; let a = off, b = off;
  while (a > 0 && /\w/.test(t[a - 1])) a--; while (b < t.length && /\w/.test(t[b])) b++;
  return t.slice(a, b) || null;
}

function wire(el) {
  on(el, 'click', '[data-xclose]', closeExplorer);
  on(el, 'click', '[data-xback]', () => back(-1)); on(el, 'click', '[data-xfwd]', () => back(1));
  on(el, 'click', '[data-dir]', (d) => { const p = d.dataset.dir; EX.expanded.has(p) ? EX.expanded.delete(p) : EX.expanded.add(p); draw(); });
  on(el, 'click', '[data-file]', (f) => go(f.dataset.file));
  on(el, 'click', '[data-xmode]', (b) => { EX.mode = b.dataset.xmode; draw(); });
  on(el, 'click', '[data-xf]', (b) => { EX.show[b.dataset.xf] = !EX.show[b.dataset.xf]; draw(); });
  on(el, 'click', '[data-panel]', (b) => { EX.panel = b.dataset.panel; draw(); });
  on(el, 'click', '[data-line]', (a, e) => { e.preventDefault(); scrollToLine(Number(a.dataset.line), true, EX.el); });
  on(el, 'click', '[data-open]', (a, e) => { e.preventDefault(); const [p, l] = a.dataset.open.split('|'); go(p, l ? Number(l) : null); });
  on(el, 'click', '[data-sym]', (a, e) => { e.preventDefault(); lookup(a.dataset.sym); });
  on(el, 'click', '[data-tab]', (a, e) => { e.preventDefault(); const run = EX.id; closeExplorer(); location.hash = `#/runs/${run}/tab/summary`; });
  on(el, 'click', '[data-ev]', async (a, e) => { e.preventDefault(); const x = await api(`/api/runs/${EX.id}/evidence/${encodeURIComponent(a.dataset.ev)}`); const { openDrawer } = await import('./lib.js'); openDrawer(`Bằng chứng · ${x.kind}`, html`<div class="section row"><span class="chip accent">${x.tier}</span><span class="chip">${x.polarity}</span><span class="muted small">do ${x.produced_by}</span></div><pre class="code">${JSON.stringify(x.record, null, 1)}</pre>`); });
  on(el, 'click', '[data-more]', async (b) => {
    const d = EX.d, dir = Number(b.dataset.more), W = 3000;
    const part = dir > 0 ? await api(`/api/runs/${EX.id}/code/file?path=${encodeURIComponent(d.path)}&start=${d.end + 1}&end=${d.end + W}`) : await api(`/api/runs/${EX.id}/code/file?path=${encodeURIComponent(d.path)}&start=${Math.max(1, d.start - W)}&end=${d.start - 1}`);
    EX.d = { ...d, lines: dir > 0 ? [...d.lines, ...part.lines] : [...part.lines, ...d.lines], start: dir > 0 ? d.start : part.start, end: dir > 0 ? part.end : d.end }; draw();
  });
  on(el, 'input', '#ex-q', (i) => { EX.nameQ = i.value; const t = $('.tree', EX.el); const root = buildTree(EX.files); mount(t, treeHtml(root)); });
  on(el, 'keydown', '#ex-q', async (i, e) => {
    if (e.key !== 'Enter') return; const q = i.value.trim(); if (q.length < 2) return;
    EX.results = await api(`/api/runs/${EX.id}/code/search?q=${encodeURIComponent(q)}`); EX.panel = 'res'; const keepQ = EX.nameQ; draw(); EX.nameQ = keepQ; $('#ex-q', EX.el)?.focus();
  });
  el.addEventListener('click', (e) => { const code = e.target.closest('.cl code'); if (code && (e.ctrlKey || e.metaKey)) { const w = wordAt(e); if (w) { e.preventDefault(); lookup(w, true); } } });
  el.addEventListener('dblclick', (e) => { if (!e.target.closest('.cl code')) return; const w = String(getSelection()).trim(); if (/^[A-Za-z_]\w*$/.test(w)) lookup(w); });
}
