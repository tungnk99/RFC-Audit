/* Khung ứng dụng: thanh bên, định tuyến theo hash, giao diện sáng/tối, lệnh nhanh (Ctrl+K), theo dõi lần chạy đang diễn ra. */
import { $, $$, api, app, closeDrawer, closeModal, esc, fmt, html, icon, mount, on, raw, status, toast, STATUS } from './lib.js';
import { wireReview } from './review.js';
import { authScreen, userChip, wireUserChip } from './auth.js';

const NAV_ADMIN = ['Quản trị', [['#/users', 'Người dùng', 'users', 'users']]];
const NAV = [
  ['Vận hành', [
    ['#/', 'Tổng quan', 'home', 'dashboard'], ['#/new', 'Chạy kiểm chứng', 'play', 'new'], ['#/runs', 'Lần chạy', 'list', 'runs'], ['#/review', 'Duyệt & phản hồi', 'users', 'review'],
  ]],
  ['Tri thức', [
    ['#/protocols', 'Giao thức & yêu cầu', 'book', 'protocols'], ['#/agents', 'Agents', 'bot', 'agents'], ['#/skills', 'Skills', 'layers', 'skills'],
  ]],
  ['Quản trị', [['#/system', 'Hệ thống & mô hình', 'sliders', 'system']]],
];
const ROUTES = [
  [/^#?\/?$/, 'dashboard'], [/^#\/new$/, 'new'], [/^#\/runs$/, 'runs'], [/^#\/runs\/([^/]+)(?:\/event\/(\d+)|\/tab\/(\w+)(?:\/([^/]+))?)?$/, 'run'], [/^#\/review(?:\/(\w+))?$/, 'review'],
  [/^#\/protocols(?:\/([^/]+))?$/, 'protocols'], [/^#\/agents(?:\/([^/]+))?$/, 'agents'], [/^#\/skills(?:\/([^/]+)\/([^/]+))?$/, 'skills'], [/^#\/system(?:\/([^/]+))?$/, 'system'], [/^#\/users$/, 'users'],
];
const TITLES = { dashboard: 'Tổng quan', new: 'Chạy kiểm chứng', runs: 'Lần chạy', run: 'Chi tiết lần chạy', review: 'Duyệt & phản hồi', protocols: 'Giao thức & yêu cầu', agents: 'Agents', skills: 'Skills', system: 'Hệ thống & mô hình', users: 'Người dùng' };
const NAV_OF = { dashboard: 'dashboard', new: 'new', runs: 'runs', run: 'runs', review: 'review', protocols: 'protocols', agents: 'agents', skills: 'skills', system: 'system', users: 'users' };
/* Menu hiện theo vai trò: mục quản lý người dùng chỉ có với admin khi máy chủ bật đăng nhập. */
const navItems = () => (app.auth && app.isAdmin ? NAV.map(([g, items]) => (g === 'Quản trị' ? [g, [...items, ...NAV_ADMIN[1]]] : [g, items])) : NAV);

let view = $('#view');
let leave = () => {};
let seq = 0;
const state = { active: [], pending: 0 };

/* ---------- thanh bên ---------- */
function drawSidebar() {
  const cur = NAV_OF[currentRoute()?.[0]];
  mount($('#sidebar'), html`
    <a class="brand" href="#/"><span class="mark">${icon('shield', 16)}</span><span>RFC-Audit<small>Kiểm chứng tuân thủ RFC</small></span></a>
    <nav class="nav">${navItems().map(([g, items]) => html`<div class="nav-group">${g}</div>${items.map(([href, label, ic, key]) => html`<a href="${href}" class="${key === cur ? 'on' : ''}">${icon(ic, 17)}${label}${key === 'runs' && state.active.length ? html`<span class="pill">${state.active.length}</span>` : ''}${key === 'review' && state.pending ? html`<span class="pill warnpill">${state.pending}</span>` : ''}</a>`)}`)}</nav>
    <div class="side-foot">
      <div class="conn" id="conn" hidden><i></i><span>đang kết nối…</span></div>
      ${app.readOnly ? html`<div class="badge warn" title="rfcv serve --read-only">${icon('lock', 12)}Chế độ chỉ đọc</div>` : ''}
      ${userChip()}
      <div class="row"><button class="btn sm ghost" id="theme-btn">${icon(document.documentElement.dataset.theme === 'dark' ? 'sun' : 'moon', 15)}<span>${document.documentElement.dataset.theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'}</span></button></div>
    </div>`);
  wireUserChip();
  $('#theme-btn').onclick = () => {
    const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = t; localStorage.setItem('rfcv-theme', t); drawSidebar(); pingHealth();
  };
}
async function pingHealth() {
  const el = $('#conn'); if (!el) return;
  try { const h = await api('/api/health'); const ro = !!h.read_only; if (ro !== app.readOnly) { app.readOnly = ro; drawSidebar(); } el.hidden = true; }
  catch { el.hidden = false; el.className = 'conn bad'; el.querySelector('span').textContent = 'Mất kết nối backend'; }
}

/* ---------- định tuyến ---------- */
function currentRoute() {
  const h = location.hash || '#/';
  for (const [re, name] of ROUTES) { const m = re.exec(h); if (m) return [name, m.slice(1)]; }
  return null;
}
export function setCrumbs(parts) {
  mount($('#crumbs'), html`${parts.map((p, i) => html`${i ? icon('chevron', 13) : ''}${p.href ? html`<a href="${p.href}">${p.text}</a>` : html`<b>${p.text}</b>`}`)}`);
}
async function route() {
  leave(); leave = () => {}; closeDrawer(); closeModal(); $('#shell').classList.remove('nav-open');
  const fresh = view.cloneNode(false); view.replaceWith(fresh); view = fresh;  // bỏ mọi trình xử lý sự kiện của trang trước (không gắn chồng)
  const r = currentRoute(); const my = ++seq;
  drawSidebar(); pingHealth();
  if (!r) { setCrumbs([{ text: 'Không tìm thấy' }]); mount(view, html`<div class="empty"><h3>Không có trang này</h3><a class="btn primary" href="#/">Về tổng quan</a></div>`); return; }
  const [name, args] = r; setCrumbs([{ text: TITLES[name] }]);
  mount(view, html`<div class="skeleton-stack"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>`);
  try {
    const mod = await import(`./pages/${name}.js?v=1`);
    if (my !== seq) return;
    view.innerHTML = '';
    const ctx = { el: view, args, setCrumbs, onLeave: (fn) => { const p = leave; leave = () => { p(); fn(); }; }, alive: () => my === seq };
    await mod.default(ctx);
  } catch (e) {
    if (my !== seq) return;
    console.error(e);
    mount(view, html`<div class="banner bad">${icon('alert', 18)}<div><b>Không tải được trang.</b><div>${e.message}</div></div></div>`);
  }
  view.focus({ preventScroll: true }); window.scrollTo(0, 0);
}
window.addEventListener('hashchange', route);

/* ---------- theo dõi lần chạy đang diễn ra ---------- */
let known = new Map();
async function pollRuns() {
  try {
    const { runs } = await api('/api/runs');
    const act = runs.filter((r) => r.status === 'queued' || r.status === 'running'); state.active = act;
    for (const r of runs) {
      const prev = known.get(r.run_id);
      if (prev && (prev === 'queued' || prev === 'running') && !(r.status === 'queued' || r.status === 'running')) {
        const v = (r.verdicts || []).map((x) => x.label).join(', ');
        toast(`Lần chạy ${r.run_id.slice(4, 12)} ${STATUS[r.status]?.[0] || r.status}${v ? ': ' + v : ''}`, r.status === 'finished' ? 'ok' : 'bad', 7000);
      }
      known.set(r.run_id, r.status);
    }
    mount($('#live-slot'), act.length ? html`<button class="live-pill" id="live-pill"><i></i>${act.length} lần chạy đang diễn ra</button>` : '');
    const lp = $('#live-pill'); if (lp) lp.onclick = () => { location.hash = `#/runs/${act[0].run_id}`; };
    const pill = $('.nav a[href="#/runs"] .pill'); if (pill && act.length) pill.textContent = act.length;
    else if (!!pill !== !!act.length) drawSidebar();
  } catch { /* backend tạm mất: thanh bên đã báo */ }
}

/* ---------- lệnh nhanh ---------- */
async function openCmdk() {
  const box = $('#cmdk'); box.hidden = false;
  mount(box, html`<div class="cmdk-box" role="dialog" aria-label="Lệnh nhanh"><input id="cmdk-in" placeholder="Gõ để tìm trang, lần chạy, agent, skill…" autocomplete="off" aria-label="Tìm"><div class="cmdk-list" id="cmdk-list"></div></div>`);
  const input = $('#cmdk-in'); input.focus();
  const [runs, cat, sk] = await Promise.all([api('/api/runs').catch(() => ({ runs: [] })), api('/api/catalog').catch(() => ({ adapters: [], agents: [] })), api('/api/skills').catch(() => ({ skills: [] }))]);
  const items = [
    ...navItems().flatMap(([, i]) => i).map(([href, label, ic]) => ({ sec: 'Trang', label, ic, href })),
    { sec: 'Hành động', label: 'Chạy kiểm chứng mới', ic: 'play', href: '#/new' },
    { sec: 'Hành động', label: 'Duyệt kết luận đang chờ', ic: 'users', href: '#/review' },
    { sec: 'Hành động', label: 'Thống kê đồng thuận người–AI', ic: 'activity', href: '#/review/insights' },
    ...runs.runs.slice(0, 30).map((r) => ({ sec: 'Lần chạy', label: r.run_id, ic: 'activity', href: `#/runs/${r.run_id}`, hint: `${r.spec.adapter || ''} · ${STATUS[r.status]?.[0] || r.status}` })),
    ...cat.adapters.filter((a) => !a.error).map((a) => ({ sec: 'Giao thức', label: a.id, ic: 'book', href: `#/protocols/${a.dir}`, hint: a.specs.map((s) => s.doc).join(', ') })),
    ...cat.agents.map((a) => ({ sec: 'Agents', label: a.name, ic: 'bot', href: `#/agents/${a.name}`, hint: a.stage })),
    ...sk.skills.map((s) => ({ sec: 'Skills', label: s.name, ic: 'layers', href: `#/skills/${s.scope}/${s.name}`, hint: s.scope })),
  ];
  let sel = 0, shown = items;
  const draw = () => {
    let last = '';
    mount($('#cmdk-list'), html`${shown.slice(0, 40).map((it, i) => { const head = it.sec !== last ? html`<div class="cmdk-sec">${it.sec}</div>` : ''; last = it.sec; return html`${head}<div class="cmdk-item ${i === sel ? 'sel' : ''}" data-i="${i}">${icon(it.ic, 16)}<span>${it.label}</span>${it.hint ? html`<small>${it.hint}</small>` : ''}</div>`; })}${shown.length ? '' : html`<div class="empty">Không có kết quả</div>`}`);
    $('.cmdk-item.sel')?.scrollIntoView({ block: 'nearest' });
  };
  const go = (i) => { const it = shown[i]; if (it) { closeCmdk(); location.hash = it.href; } };
  input.oninput = () => { const q = input.value.toLowerCase().trim(); shown = q ? items.filter((x) => (x.label + ' ' + (x.hint || '') + ' ' + x.sec).toLowerCase().includes(q)) : items; sel = 0; draw(); };
  input.onkeydown = (e) => { if (e.key === 'ArrowDown') { sel = Math.min(shown.length - 1, sel + 1); draw(); e.preventDefault(); } else if (e.key === 'ArrowUp') { sel = Math.max(0, sel - 1); draw(); e.preventDefault(); } else if (e.key === 'Enter') go(sel); };
  on($('#cmdk-list'), 'click', '.cmdk-item', (el) => go(Number(el.dataset.i)));
  box.onclick = (e) => { if (e.target === box) closeCmdk(); };
  draw();
}
const closeCmdk = () => { $('#cmdk').hidden = true; };

/* ---------- khởi động ---------- */
mount($('#search-ic'), icon('search', 15)); mount($('#menu-btn'), icon('menu', 18)); mount($('#drawer-close'), icon('x', 16));
$('#search-btn').onclick = openCmdk; $('#menu-btn').onclick = () => $('#shell').classList.toggle('nav-open');
$('#drawer-close').onclick = closeDrawer; $('#scrim').onclick = closeDrawer;
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#cmdk').hidden ? openCmdk() : closeCmdk(); }
  else if (e.key === 'Escape') { closeDrawer(); closeModal(); closeCmdk(); }
});
/* Số yêu cầu đang chờ người duyệt (hiện trên thanh bên) */
async function pollPending() {
  try { const s = await api('/api/reviews/summary'); if (s.pending !== state.pending) { state.pending = s.pending; drawSidebar(); pingHealth(); } } catch { /* bỏ qua */ }
}
wireReview(document.body, () => window.dispatchEvent(new Event('rfcv:rv')));  // cờ bằng chứng và đánh giá agent: một chỗ gắn cho mọi màn hình
window.addEventListener('rfcv:review-submitted', pollPending);
(async () => {
  try { app.readOnly = !!(await api('/api/health')).read_only; } catch { /* sẽ báo mất kết nối */ }
  let st = { auth: false, user: null };
  try { st = await api('/api/auth/status'); } catch { /* sẽ báo mất kết nối */ }
  app.auth = !!st.auth;
  app.onUnauth = () => { if (app.out) return; app.out = true; toast('Phiên đăng nhập đã hết hạn', 'bad'); setTimeout(() => location.reload(), 800); };
  app.user = st.user || (st.auth ? await authScreen(st) : null);
  if (app.user && !st.user) app.out = false;
  route(); pollRuns(); pollPending(); setInterval(pollRuns, 3000); setInterval(pingHealth, 15000); setInterval(pollPending, 20000);
})();
