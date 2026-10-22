import { $, api, empty, fmt, html, icon, labelOf, modeName, mount, on, pageHead, sortRows, status, toast, verdict } from '../lib.js';

const FILTERS = [['all', 'Tất cả'], ['active', 'Đang chạy'], ['finished', 'Hoàn tất'], ['bad', 'Lỗi / ngắt'], ['cancelled', 'Đã huỷ']];
const PAGE = 15;
const st = { q: '', f: 'all', verdict: '', adapter: '', mode: '', sort: 'created_at', dir: -1, page: 0 };

export default async function (ctx) {
  let runs = [];
  const matches = (r) => {
    const s = r.status;
    if (st.f === 'active' && !(s === 'queued' || s === 'running')) return false;
    if (st.f === 'finished' && s !== 'finished') return false;
    if (st.f === 'bad' && !(s === 'failed' || s === 'interrupted')) return false;
    if (st.f === 'cancelled' && s !== 'cancelled') return false;
    if (st.adapter && r.spec.adapter !== st.adapter) return false;
    if (st.mode && r.spec.mode !== st.mode) return false;
    if (st.verdict && !(r.verdicts || []).some((v) => (st.verdict === 'other' ? !['COMPLIANT', 'VIOLATION'].includes(v.label) : v.label === st.verdict))) return false;
    return !st.q || (r.run_id + ' ' + (r.spec.adapter || '') + ' ' + (r.batch_id || '')).toLowerCase().includes(st.q.toLowerCase());
  };
  const sortKey = { created_at: (r) => r.started_at || r.created_at, tokens: (r) => r.digest?.tokens || 0, dur: (r) => (r.ended_at && r.started_at ? r.ended_at - r.started_at : 0), status: (r) => r.status, adapter: (r) => r.spec.adapter || '' };

  const draw = () => {
    const rows = sortRows(runs.filter(matches), sortKey[st.sort] || sortKey.created_at, st.dir);
    const pages = Math.max(1, Math.ceil(rows.length / PAGE)); st.page = Math.min(st.page, pages - 1);
    const shown = rows.slice(st.page * PAGE, (st.page + 1) * PAGE);
    const count = (f) => runs.filter((r) => { const s = r.status; return f === 'all' || (f === 'active' && (s === 'queued' || s === 'running')) || (f === 'finished' && s === 'finished') || (f === 'bad' && (s === 'failed' || s === 'interrupted')) || (f === 'cancelled' && s === 'cancelled'); }).length;
    const adapters = [...new Set(runs.map((r) => r.spec.adapter).filter(Boolean))];
    const th = (k, l, cls = '') => html`<th class="sortable ${cls}" data-sort="${k}">${l}${st.sort === k ? (st.dir < 0 ? ' ↓' : ' ↑') : ''}</th>`;
    mount($('#runs-body', ctx.el), html`
      <div class="toolbar"><div class="search">${icon('search', 15)}<input type="search" id="q" placeholder="Tìm theo mã lần chạy, giao thức…" value="${st.q}" aria-label="Tìm lần chạy"></div>
        <div class="seg">${FILTERS.map(([k, l]) => html`<button data-f="${k}" class="${st.f === k ? 'on' : ''}">${l} <span class="muted">${count(k)}</span></button>`)}</div>
        <select id="f-verdict" aria-label="Lọc theo kết luận"><option value="">Mọi kết luận</option><option value="COMPLIANT" ${st.verdict === 'COMPLIANT' ? 'selected' : ''}>Tuân thủ</option><option value="VIOLATION" ${st.verdict === 'VIOLATION' ? 'selected' : ''}>Vi phạm</option><option value="other" ${st.verdict === 'other' ? 'selected' : ''}>Khác</option></select>
        <select id="f-adapter" aria-label="Lọc theo giao thức"><option value="">Mọi giao thức</option>${adapters.map((a) => html`<option ${st.adapter === a ? 'selected' : ''}>${a}</option>`)}</select>
        <select id="f-mode" aria-label="Lọc theo chế độ"><option value="">Mọi chế độ</option>${['demo', 'real', 'cli'].map((m) => html`<option value="${m}" ${st.mode === m ? 'selected' : ''}>${modeName(m)}</option>`)}</select>
        <span class="muted small grow" style="text-align:right">${rows.length} lần chạy</span></div>
      ${rows.length ? html`<div class="table-wrap"><table class="tbl"><thead><tr>${th('created_at', 'Lần chạy')}${th('adapter', 'Giao thức')}<th>Chế độ</th>${th('status', 'Trạng thái')}<th>Kết luận</th>${th('tokens', 'Token', 'num')}${th('dur', 'Thời lượng', 'num')}<th></th></tr></thead><tbody>
        ${shown.map((r) => { const live = r.status === 'queued' || r.status === 'running'; return html`<tr class="click" data-open="${r.run_id}">
          <td><div class="mono">${r.run_id}</div><div class="muted small">${fmt.time(r.started_at || r.created_at)} · ${fmt.ago(r.started_at || r.created_at)}</div></td>
          <td>${r.spec.adapter || '–'}${r.spec.requirements?.length ? html`<div class="muted small">${r.spec.requirements.join(', ')}</div>` : ''}</td><td>${modeName(r.spec.mode)}</td>
          <td>${status(r.status)}${r.error ? html`<div class="small" style="color:var(--critical-text);max-width:260px" title="${r.error}">${r.error.slice(0, 80)}</div>` : ''}${r.leak_scan && !r.leak_scan.clean ? html`<div><span class="badge bad">${icon('alert', 12)}rò rỉ ${r.leak_scan.count}</span></div>` : ''}</td>
          <td>${(r.verdicts || []).map((v) => verdict(v.label, v.rule))}${live ? html`<span class="muted small">đang điều tra…</span>` : ''}</td>
          <td class="num">${r.digest?.tokens != null ? fmt.tok(r.digest.tokens) : '–'}</td><td class="num">${r.started_at ? fmt.dur(r.started_at, r.ended_at) : (r.digest?.seconds ? fmt.sec(r.digest.seconds) : '–')}</td>
          <td class="nowrap" style="text-align:right">${live ? html`<button class="icon-btn" data-cancel="${r.run_id}" title="Huỷ" aria-label="Huỷ">${icon('stop', 15)}</button>` : ''}${r.spec.mode === 'demo' || r.spec.mode === 'real' ? html`<button class="icon-btn" data-rerun="${r.run_id}" title="Chạy lại cùng cấu hình" aria-label="Chạy lại">${icon('refresh', 15)}</button>` : ''}<a class="icon-btn" href="/api/runs/${r.run_id}/export" title="Xuất JSON" aria-label="Xuất JSON" download>${icon('download', 15)}</a></td></tr>`; })}
        </tbody></table></div>
        <div class="toolbar" style="border-top:1px solid var(--border);border-bottom:0;justify-content:space-between"><span class="muted small">Trang ${st.page + 1}/${pages}</span><div class="row"><button class="btn sm" data-page="-1" ${st.page === 0 ? 'disabled' : ''}>Trước</button><button class="btn sm" data-page="1" ${st.page >= pages - 1 ? 'disabled' : ''}>Sau</button></div></div>`
      : (runs.length ? empty('Không có lần chạy khớp bộ lọc', '', html`<button class="btn" data-reset>Xoá bộ lọc</button>`) : empty('Chưa có lần chạy nào', 'Lần chạy sẽ xuất hiện ở đây ngay khi bạn bắt đầu.', html`<a class="btn primary" href="#/new">Chạy kiểm chứng</a>`))}`);
    const q = $('#q', ctx.el); if (document.activeElement?.id === 'q') q.setSelectionRange(q.value.length, q.value.length);
  };
  const load = async () => { runs = (await api('/api/runs?digest=true')).runs; if (ctx.alive()) draw(); };

  mount(ctx.el, html`${pageHead('Lần chạy', 'Mọi lần kiểm chứng, kể cả chạy bằng CLI. Bấm một dòng để xem các agent đã làm gì.', html`<a class="btn primary" href="#/new">${icon('plus', 15)}Chạy mới</a>`)}<section class="card flush" id="runs-body"></section>`);
  on(ctx.el, 'input', '#q', (el) => { st.q = el.value; st.page = 0; draw(); $('#q', ctx.el).focus(); });
  on(ctx.el, 'click', '[data-f]', (el) => { st.f = el.dataset.f; st.page = 0; draw(); });
  on(ctx.el, 'change', '#f-verdict', (el) => { st.verdict = el.value; st.page = 0; draw(); });
  on(ctx.el, 'change', '#f-adapter', (el) => { st.adapter = el.value; st.page = 0; draw(); });
  on(ctx.el, 'change', '#f-mode', (el) => { st.mode = el.value; st.page = 0; draw(); });
  on(ctx.el, 'click', '[data-reset]', () => { Object.assign(st, { q: '', f: 'all', verdict: '', adapter: '', mode: '', page: 0 }); draw(); });
  on(ctx.el, 'click', '[data-sort]', (el) => { const k = el.dataset.sort; st.dir = st.sort === k ? -st.dir : -1; st.sort = k; draw(); });
  on(ctx.el, 'click', '[data-page]', (el) => { st.page += Number(el.dataset.page); draw(); });
  on(ctx.el, 'click', '[data-cancel]', async (el, e) => { e.stopPropagation(); await api(`/api/runs/${el.dataset.cancel}/cancel`, { body: {} }).catch((x) => toast(x.message, 'bad')); load(); });
  on(ctx.el, 'click', '[data-rerun]', async (el, e) => { e.stopPropagation(); try { const r = await api(`/api/runs/${el.dataset.rerun}/rerun`, { body: {} }); toast('Đã xếp hàng lần chạy lại', 'ok'); location.hash = `#/runs/${r.runs[0].run_id}`; } catch (x) { toast(x.message, 'bad'); } });
  on(ctx.el, 'click', '.icon-btn[download]', (_, e) => e.stopPropagation());
  on(ctx.el, 'click', 'tr[data-open]', (tr) => { location.hash = `#/runs/${tr.dataset.open}`; });
  await load();
  const timer = setInterval(() => { if (ctx.alive() && (runs.some((r) => r.status === 'queued' || r.status === 'running') || false)) load(); }, 3000);
  ctx.onLeave(() => clearInterval(timer));
}
