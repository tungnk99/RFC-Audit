/* Thư viện dùng chung: gọi API, template tự thoát HTML, biểu tượng, định dạng, thành phần giao diện.
   An toàn mặc định: mọi giá trị chèn qua html`…` đều bị thoát, trừ khi là kết quả của một html`…` khác (kiểu Raw).
   Dữ liệu từ backend gồm cả mã nguồn đang được kiểm chứng (không tin cậy), nên không có đường nào chèn chuỗi thô. */

/* ---------- template an toàn ---------- */
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c]);
const part = (v) => (v == null || v === false ? '' : v instanceof Raw ? v.s : Array.isArray(v) ? v.map(part).join('') : esc(v));
export function html(strings, ...vals) { let out = strings[0]; vals.forEach((v, i) => { out += part(v) + strings[i + 1]; }); return new Raw(out); }
export const raw = (s) => new Raw(s);
export const mount = (el, r) => { el.innerHTML = String(r); };
export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

/* sự kiện uỷ quyền: on(root, 'click', '[data-act]', (el, ev) => …) */
export function on(root, type, sel, fn) {
  root.addEventListener(type, (ev) => { const t = ev.target.closest(sel); if (t && root.contains(t)) fn(t, ev); });
}

/* ---------- API ---------- */
export async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.body !== undefined) { init.method = opts.method || 'POST'; init.headers = { 'Content-Type': 'application/json' }; init.body = JSON.stringify(opts.body); }
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && app.auth && !path.startsWith('/api/auth/')) app.onUnauth();  // phiên hết hạn hoặc bị thu hồi: về màn hình đăng nhập
    const e = new Error(data.error || (data.errors || []).join('; ') || res.statusText);
    e.status = res.status; e.data = data; throw e;
  }
  return data;
}

/* ---------- biểu tượng (nét 1.75, lưới 24) ---------- */
const P = {
  home: 'M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10', play: 'M7 4l13 8-13 8z', list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  book: 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5v14zM20 17v4H6.5A2.5 2.5 0 0 1 4 18.5',
  bot: 'M12 8V4M8 4h8M5 8h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2zM9 14h.01M15 14h.01M2 13v2M22 13v2',
  layers: 'M12 2l10 5-10 5L2 7zM2 17l10 5 10-5M2 12l10 5 10-5', sliders: 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35',
  sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42',
  moon: 'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z', check: 'M20 6L9 17l-5-5', x: 'M18 6L6 18M6 6l12 12',
  alert: 'M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z',
  clock: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2', download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
  refresh: 'M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15', stop: 'M6 6h12v12H6z', chevron: 'M9 18l6-6-6-6',
  folder: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z', file: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z', activity: 'M22 12h-4l-3 9L9 3l-3 9H2',
  cpu: 'M4 4h16v16H4zM9 9h6v6H9zM9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3',
  db: 'M12 8c4.97 0 9-1.34 9-3s-4.03-3-9-3-9 1.34-9 3 4.03 3 9 3zM21 12c0 1.66-4 3-9 3s-9-1.34-9-3M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1', external: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3', menu: 'M3 12h18M3 6h18M3 18h18',
  info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01', plus: 'M12 5v14M5 12h14', zap: 'M13 2L3 14h9l-1 8 10-12h-9l1-8z',
  lock: 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4', git: 'M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9',
  tool: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z',
  eye: 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', hash: 'M4 9h16M4 15h16M10 3L8 21M16 3l-2 18',
  star: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z',  minus: 'M5 12h14',
  flag: 'M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7',  edit: 'M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z',  history: 'M3 3v5h5M3.05 13A9 9 0 1 0 6 5.3L3 8M12 7v5l4 2',  users: 'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
};
export const icon = (n, size = 16, cls = '') => raw(`<svg class="ic ${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${P[n] || P.info}"/></svg>`);

/* ---------- định dạng ---------- */
export const fmt = {
  int: (n) => (n == null ? '–' : Number(n).toLocaleString('vi-VN')),
  tok: (n) => (n == null ? '–' : n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e5 ? 0 : 1) + 'k' : String(n)),
  ms: (ms) => (ms == null ? '–' : ms >= 60000 ? Math.floor(ms / 60000) + 'p ' + Math.round((ms % 60000) / 1000) + 's' : ms >= 1000 ? (ms / 1000).toFixed(1) + 's' : Math.round(ms) + 'ms'),
  sec: (s) => fmt.ms(s == null ? null : s * 1000),
  time: (t) => (t ? new Date(t * 1000).toLocaleString('vi-VN', { hour12: false }) : '–'),
  date: (t) => (t ? new Date(t * 1000).toLocaleDateString('vi-VN') : '–'),
  ago: (t) => { if (!t) return '–'; const d = Date.now() / 1000 - t; return d < 5 ? 'vừa xong' : d < 60 ? Math.floor(d) + ' giây trước' : d < 3600 ? Math.floor(d / 60) + ' phút trước' : d < 86400 ? Math.floor(d / 3600) + ' giờ trước' : Math.floor(d / 86400) + ' ngày trước'; },
  dur: (a, b) => (a && b ? fmt.sec(b - a) : '–'),
  bytes: (n) => (n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB'),
  pct: (a, b) => (b ? Math.round((a / b) * 100) + '%' : '–'),
};

/* ---------- thành phần ---------- */
export const STATUS = {
  queued: ['đang chờ', 'warn', 'clock'], running: ['đang chạy', 'info', 'activity'], finished: ['hoàn tất', 'ok', 'check'],
  failed: ['lỗi', 'bad', 'x'], cancelled: ['đã huỷ', 'mute', 'stop'], interrupted: ['bị ngắt', 'bad', 'alert'], unknown: ['không rõ', 'mute', 'info'],
};
export const status = (s) => { const [t, c, i] = STATUS[s] || [s, 'mute', 'info']; return html`<span class="badge ${c}${s === 'running' ? ' pulse' : ''}">${icon(i, 12)}${t}</span>`; };
export const LABEL = { COMPLIANT: ['TUÂN THỦ', 'ok', 'check'], VIOLATION: ['VI PHẠM', 'bad', 'x'] };
export const labelOf = (l) => LABEL[l] || [String(l || '–'), 'warn', 'alert'];
export const verdict = (l, rule) => { const [t, c, i] = labelOf(l); return html`<span class="badge ${c}">${icon(i, 12)}${t}${rule ? html`<em>${rule}</em>` : ''}</span>`; };
export const chip = (text, cls = '') => html`<span class="chip ${cls}">${text}</span>`;
export const modeName = (m) => ({ demo: 'Demo mô phỏng', real: 'Mã thật', cli: 'CLI' }[m] || m || '–');
export const zoneName = (z) => ({ privileged: 'đặc quyền', quarantine: 'cách ly' }[z] || z);

export function empty(titleText, body = '', action = '') {
  return html`<div class="empty">${icon('info', 28)}<h3>${titleText}</h3>${body ? html`<p>${body}</p>` : ''}${action}</div>`;
}
export const skeleton = (n = 3) => html`<div class="skeleton-stack">${Array.from({ length: n }, () => html`<div class="skeleton"></div>`)}</div>`;
export function pageHead(titleText, sub = '', actions = '') {
  return html`<header class="page-head"><div><h1>${titleText}</h1>${sub ? html`<p class="sub">${sub}</p>` : ''}</div><div class="actions">${actions}</div></header>`;
}
export function tabs(items, cur, attr = 'data-tab') {
  return html`<div class="tabs" role="tablist">${items.map(([k, l, n]) => html`<button role="tab" ${raw(attr)}="${k}" class="${k === cur ? 'on' : ''}" aria-selected="${String(k === cur)}">${l}${n != null ? html`<span class="count">${n}</span>` : ''}</button>`)}</div>`;
}
export const kv = (rows) => html`<dl class="kv">${rows.filter((r) => r).map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}</dl>`;
export const copyBtn = (text) => html`<button class="icon-btn" data-copy="${text}" title="Sao chép" aria-label="Sao chép">${icon('copy', 14)}</button>`;

/* ---------- toast, drawer, modal ---------- */
export function toast(msg, kind = 'info', ms = 4500) {
  const host = $('#toasts'); const el = document.createElement('div'); el.className = `toast ${kind}`;
  el.innerHTML = String(html`${icon(kind === 'ok' ? 'check' : kind === 'bad' ? 'alert' : 'info', 16)}<span>${msg}</span>`);
  host.appendChild(el); setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 250); }, ms);
}
export function openDrawer(titleText, body, wide = false) {
  const d = $('#drawer'); d.classList.toggle('wide', wide); mount($('#drawer-title'), html`${titleText}`); mount($('#drawer-body'), body); d.hidden = false; $('#scrim').hidden = false; $('#drawer-body').scrollTop = 0;
}
export function closeDrawer() { $('#drawer').hidden = true; $('#scrim').hidden = true; }
export function openModal(body) { const m = $('#modal'); mount(m, html`<div class="modal-box" role="dialog" aria-modal="true">${body}</div>`); m.hidden = false; m.onclick = (e) => { if (e.target === m) closeModal(); }; return m; }
export function closeModal() { $('#modal').hidden = true; }

/* ---------- markdown nhẹ cho SKILL.md / prompt.md (đã thoát HTML) ---------- */
export function markdown(src) {
  const lines = String(src || '').replace(/\r/g, '').split('\n'); const out = []; let i = 0;
  const inline = (s) => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>');
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith('```')) { const buf = []; i++; while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++]); i++; out.push(`<pre class="code">${esc(buf.join('\n'))}</pre>`); continue; }
    const h = /^(#{1,4})\s+(.*)$/.exec(l); if (h) { out.push(`<h${h[1].length + 1} class="md-h">${inline(h[2])}</h${h[1].length + 1}>`); i++; continue; }
    if (/^\s*\|.*\|\s*$/.test(l) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || '')) {
      const cells = (s) => s.trim().replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim())); const head = cells(l); i += 2; const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(`<div class="table-wrap"><table class="tbl"><thead><tr>${head.map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`); continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) {
      // Danh sách một cấp lồng: mục thụt lề >= 2 thuộc mục cấp trên gần nhất; dòng thụt lề không phải mục là phần tiếp của mục trước.
      const ord = /^\s*\d+\./.test(l); const tops = [];
      while (i < lines.length) {
        const m = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(lines[i]);
        if (m) { if (m[1].length >= 2 && tops.length) tops[tops.length - 1].kids.push(m[3]); else tops.push({ text: m[3], kids: [] }); i++; }
        else if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && tops.length) { const t = tops[tops.length - 1]; if (t.kids.length) t.kids[t.kids.length - 1] += ' ' + lines[i].trim(); else t.text += ' ' + lines[i].trim(); i++; }
        else break;
      }
      const tag = ord ? 'ol' : 'ul';
      out.push(`<${tag}>${tops.map((t) => `<li>${inline(t.text)}${t.kids.length ? `<ul>${t.kids.map((k) => `<li>${inline(k)}</li>`).join('')}</ul>` : ''}</li>`).join('')}</${tag}>`); continue;
    }
    if (!l.trim()) { i++; continue; }
    const para = []; while (i < lines.length && lines[i].trim() && !/^(```|#{1,4}\s|\s*([-*]|\d+\.)\s+|\s*\|)/.test(lines[i])) para.push(lines[i++]);
    out.push(`<p>${inline(para.join(' '))}</p>`);
  }
  return raw(`<div class="md">${out.join('')}</div>`);
}

/* ---------- bảng có sắp xếp ---------- */
export function sortRows(rows, key, dir) { const f = typeof key === 'function' ? key : (r) => r[key]; return [...rows].sort((a, b) => { const x = f(a), y = f(b); return (x > y ? 1 : x < y ? -1 : 0) * dir; }); }

/* ---------- clipboard, tooltip dùng chung ---------- */
document.addEventListener('click', (e) => { const b = e.target.closest('[data-copy]'); if (b) { navigator.clipboard?.writeText(b.dataset.copy); toast('Đã sao chép', 'ok', 1500); } });
let tipEl;
export function tip(el, e) {
  tipEl = tipEl || Object.assign(document.body.appendChild(document.createElement('div')), { className: 'tooltip' });
  const t = el.dataset.tip; if (!t) { tipEl.style.display = 'none'; return; }
  tipEl.innerHTML = t; tipEl.style.display = 'block';
  const r = tipEl.getBoundingClientRect(); let x = e.clientX + 14, y = e.clientY + 14;
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14; if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 14;
  tipEl.style.left = x + 'px'; tipEl.style.top = y + 'px';
}
document.addEventListener('mousemove', (e) => { const t = e.target.closest?.('[data-tip]'); if (t) tip(t, e); else if (tipEl) tipEl.style.display = 'none'; });

/* ---------- trạng thái ứng dụng và danh tính người duyệt/người sửa ---------- */
export const app = {
  readOnly: false, auth: false, user: null, onUnauth: () => {},
  get isAdmin() { return this.user?.role === 'admin'; },
  get canEdit() { return !this.readOnly && this.isAdmin; },  // sửa tài nguyên: chỉ admin, và máy chủ không ở chế độ chỉ đọc
};
const WHO = 'rfcv-who';
/* Có đăng nhập: danh tính là tài khoản của phiên (máy chủ tự gắn, không tin tên máy khách gửi). Chạy --no-auth: tên tự khai, chưa xác thực. */
export const who = () => (app.auth ? app.user?.username || '' : localStorage.getItem(WHO) || '');
export function ensureWho() {
  return new Promise((resolve) => {
    if (app.auth || who()) return resolve(who());
    openModal(html`<div class="mh"><h3>Bạn là ai?</h3><p class="muted small" style="margin:6px 0 0">Tên này được ghi kèm mọi nhận định và lần sửa để truy vết. Giao diện chưa có đăng nhập nên đây là tên tự khai, chưa phải danh tính đã xác thực.</p></div>
      <div class="mb" style="padding:10px 18px"><input type="text" id="who-in" maxlength="60" placeholder="vd. Nguyễn Văn A" style="width:100%" aria-label="Tên của bạn"></div>
      <div class="mf"><button class="btn" id="who-x">Huỷ</button><button class="btn primary" id="who-ok">Lưu tên</button></div>`);
    const input = $('#who-in'); input.focus();
    const done = (v) => { closeModal(); resolve(v); };
    $('#who-x').onclick = () => done('');
    $('#who-ok').onclick = () => { const v = input.value.trim(); if (v) { localStorage.setItem(WHO, v); done(v); } };
    input.onkeydown = (e) => { if (e.key === 'Enter') $('#who-ok').click(); };
  });
}
export function changeWho() { localStorage.removeItem(WHO); return ensureWho(); }