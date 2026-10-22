/* Bằng chứng trên mã: mở tệp mã nguồn với chú thích bằng chứng ngay dưới các dòng liên quan, như bình luận trong code review.
   Chú thích đến từ bằng chứng đã ghi (T1 vị trí và từng khía cạnh khớp/lệch, kết luận dựa trên chúng, độ phủ khi kiểm thử kích hoạt).
   Có bộ lọc (mức độ, tầng, yêu cầu, tìm chữ), danh mục chú thích để nhảy tới vùng cần xem. Nội dung tệp là dữ liệu KHÔNG TIN CẬY. */
import { api, app, empty, html, icon } from './lib.js';
import { flagMenu } from './review.js';

const SEV = { bad: ['x', 'Lệch đặc tả'], ok: ['check', 'Khớp'], info: ['info', 'Định vị'] };

/* Cuộn bên trong khung mã tới một dòng (không cuộn cả trang) và nháy sáng để dễ thấy. */
export function scrollToLine(n, smooth = false, root = document) {
  const el = typeof n === 'number' ? root.querySelector('#L' + n) : n, frame = el?.closest('.codeframe');
  if (!el || !frame) return;
  frame.scrollTo({ top: Math.max(0, el.offsetTop - frame.clientHeight / 3), behavior: smooth ? 'smooth' : 'auto' });
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
}

export const newCodeState = () => ({ files: null, cur: null, data: null, show: { bad: true, ok: true, info: true, hit: true }, tier: '', req: '', q: '', focus: null, autoDone: null, qIdx: 0 });

export async function codeTab(S) {
  const c = S.code;
  if (!c.files) { const t = await api(`/api/runs/${S.id}/code`); c.files = t.files.filter((f) => f.annotations || f.read); c.total = t.files.length; }  // tab này chỉ liệt kê tệp liên quan; cả kho ở trình duyệt mã
  if (!c.files.length) return empty('Chưa có mã nào được định vị', 'Bằng chứng vị trí (T1) xuất hiện khi agent code_reader định vị được đoạn mã và Schema gate xác nhận.');
  if (!c.cur || !c.files.some((f) => f.path === c.cur)) c.cur = c.files[0].path;
  if (!c.data || c.data.path !== c.cur) c.data = await api(`/api/runs/${S.id}/code/file?path=${encodeURIComponent(c.cur)}`);
  const d = c.data, all = d.annotations, cnt = (s) => all.filter((a) => a.severity === s).length;
  const tiers = [...new Set(all.map((a) => a.tier))].sort(), reqs = [...new Set(all.map((a) => a.requirement_id))].sort();
  const vis = all.filter((a) => c.show[a.severity] && (!c.tier || a.tier === c.tier) && (!c.req || a.requirement_id === c.req));
  const rangeOf = (n) => { let sev = null; for (const a of vis) if (n >= a.line_start && n <= a.line_end && a.kind !== 'verdict') { if (a.severity === 'bad') return 'bad'; sev = sev === 'ok' ? 'ok' : a.severity; } return sev; };
  const endAt = new Map(); vis.forEach((a) => { (endAt.get(a.line_end) || endAt.set(a.line_end, []).get(a.line_end)).push(a); });
  const q = c.q.trim().toLowerCase(), matches = q ? d.lines.filter((l) => l.text.toLowerCase().includes(q)).map((l) => l.n) : [];
  const rows = rowsHtml(d, { rangeOf, endAt, show: c.show, matches: new Set(matches), q, trace: d.source === 'trace', flag: (a) => flagMenu(S.id, a.requirement_id, a.evidence_id, !!S.canReview) });
  if (c.focus == null && c.autoDone !== d.path) { const first = all.find((a) => a.severity === 'bad') || all[0]; c.focus = first ? first.line_start : null; }  // mở tệp là tới ngay chỗ đáng xem
  c.autoDone = d.path;
  if (c.focus) { const f = c.focus; c.focus = null; requestAnimationFrame(() => scrollToLine(f)); }
  const outline = [...vis].sort((a, b) => ({ bad: 0, ok: 1, info: 2 }[a.severity] - { bad: 0, ok: 1, info: 2 }[b.severity]) || a.line_start - b.line_start);
  return html`<div class="row" style="margin-bottom:10px"><select id="code-file" aria-label="Tệp mã">${c.files.map((f) => html`<option value="${f.path}" ${f.path === c.cur ? 'selected' : ''}>${f.path} (${f.annotations} chú thích${f.bad ? `, ${f.bad} lệch` : ''})</option>`)}</select>
      <span class="chip ${d.source === 'workspace' ? 'ok' : 'warn'}" title="${d.source === 'workspace' ? 'Bản sao phạm vi tại đúng commit trong thư mục lần chạy' : 'Chỉ các dòng agent đã đọc, lấy từ trace'}">${d.source === 'trace' ? `${d.total} dòng agent đã đọc` : 'toàn bộ tệp'}</span><button class="btn sm" data-explorer>${icon('folder', 13)}Duyệt cả kho${c.total > c.files.length ? ` (${c.total} tệp)` : ''}</button></div>
    <div class="row small" style="margin-bottom:10px">${['bad', 'ok', 'info'].map((s) => html`<button class="fchip ${c.show[s] ? 'on ' + s : ''}" data-cf="${s}">${icon(SEV[s][0], 12)}${SEV[s][1]} <b>${cnt(s)}</b></button>`)}<button class="fchip ${c.show.hit ? 'on hit' : ''}" data-cf="hit">${icon('zap', 12)}Độ phủ <b>${d.hits.length}</b></button>
      ${tiers.length > 1 ? html`<select id="code-tier" aria-label="Tầng bằng chứng"><option value="">mọi tầng</option>${tiers.map((t) => html`<option ${c.tier === t ? 'selected' : ''}>${t}</option>`)}</select>` : ''}
      ${reqs.length > 1 ? html`<select id="code-req" aria-label="Yêu cầu"><option value="">mọi yêu cầu</option>${reqs.map((r) => html`<option ${c.req === r ? 'selected' : ''}>${r}</option>`)}</select>` : ''}
      <span class="search-mini">${icon('search', 13)}<input type="search" id="code-q" placeholder="Tìm trong tệp…" value="${c.q}" aria-label="Tìm trong mã"></span>${q ? html`<span class="muted">${matches.length} khớp</span><button class="btn sm" data-qnext>${icon('chevron', 12)}</button>` : ''}</div>
    ${outline.length ? html`<div class="outline" role="list" aria-label="Danh mục chú thích">${outline.map((a) => html`<a href="#" role="listitem" class="ol ${a.severity}" data-goto="${a.line_start}">${icon(SEV[a.severity][0], 12)}<span class="mono">${a.line_start === a.line_end ? a.line_start : `${a.line_start}–${a.line_end}`}</span><span class="grow">${a.title}</span><span class="chip">${a.tier}</span></a>`)}</div>` : html`<div class="muted small" style="margin-bottom:8px">Không có chú thích khớp bộ lọc.</div>`}
    <div class="codeview codeframe feed" role="region" aria-label="Mã nguồn có chú thích">${rows}</div>
    <div class="legend-line"><span><b style="color:var(--critical-text)">✗</b> lệch đặc tả</span><span><b style="color:var(--good-text)">✓</b> khớp</span><span>${icon('zap', 12)} thực thi khi kiểm thử kích hoạt</span><span class="muted">Mã là dữ liệu không tin cậy, chỉ hiển thị.</span></div>`;
}

/* Dựng các dòng mã kèm chú thích; dùng chung cho tab Bằng chứng và trình duyệt mã toàn màn hình. */
export function rowsHtml(d, o) {
  const read = new Set(d.read || []); let prev = null;
  return d.lines.map((l) => {
    const gap = prev != null && l.n !== prev + 1 ? html`<div class="gap">⋯ ${l.n - prev - 1} dòng ${o.trace ? 'chưa được đọc' : 'đã ẩn'}</div>` : ''; prev = l.n;
    const sev = o.rangeOf(l.n), hit = o.show.hit && d.hits.includes(l.n), found = o.q && o.matches.has(l.n);
    return html`${gap}<div class="cl ${sev === 'bad' ? 'mismatch' : sev === 'ok' ? 'match' : sev === 'info' ? 'range' : ''} ${found ? 'found' : ''} ${o.show.read && read.has(l.n) ? 'rd' : ''}" id="L${l.n}"><span class="ln">${l.n}</span><span class="mk">${sev === 'bad' ? '✗' : sev === 'ok' ? '✓' : ''}</span><code>${l.text}</code>${hit ? html`<span class="hit" title="Dòng này được thực thi khi kiểm thử kích hoạt (độ phủ)">${icon('zap', 12)}</span>` : ''}</div>
      ${(o.endAt.get(l.n) || []).map((a) => card(a, o.flag))}`;
  });
}
export const SEVERITY = SEV;

export function card(a, flag = null) {
  const [ic] = SEV[a.severity] || SEV.info;
  return html`<div class="ann ${a.severity}"><div class="ann-h">${icon(ic, 14)}<b>${a.title}</b><span class="chip">dòng ${a.line_start === a.line_end ? a.line_start : `${a.line_start}–${a.line_end}`}</span></div>
    ${a.detail ? html`<div class="ann-d">${a.detail}</div>` : ''}
    <div class="ann-f">${flag && a.kind !== 'verdict' ? flag(a) : ''}<span class="chip accent">${a.tier}</span><span class="chip">${a.requirement_id}</span><span class="muted small">${a.produced_by}</span>${a.kind === 'verdict' ? html`<a href="#" data-tab="summary">xem phân tích kết luận</a>` : html`<a href="#" data-ev="${a.evidence_id}" class="mono small">${String(a.evidence_id).slice(7, 19)}…</a>`}</div></div>`;
}
