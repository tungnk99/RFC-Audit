import { $, api, empty, fmt, html, icon, labelOf, modeName, mount, on, pageHead, status, verdict } from '../lib.js';
import { chartCard, columns, hbars, segmented, wireChartCards } from '../charts.js';

const RANGES = [[7, '7 ngày'], [30, '30 ngày'], [90, '90 ngày'], [0, 'Tất cả']];
const LABEL_COLOR = { COMPLIANT: 'var(--good)', VIOLATION: 'var(--critical)' };

export default async function (ctx) {
  let days = Number(sessionStorage.getItem('rfcv-range') ?? 30), hasActive = false, sysCache = null, lastRuns = null;
  const draw = async () => {
    const sysP = (sysCache ||= api('/api/system').catch(() => null));
    const [s, runs, rv] = await Promise.all([api(`/api/stats?days=${days}`), api('/api/runs'), api('/api/reviews/summary')]);
    if (!ctx.alive()) return;
    const t = s.totals; lastRuns = t.runs; const daily = s.daily; hasActive = t.active > 0;
    const verdicts = Object.entries(s.verdicts).sort((a, b) => b[1] - a[1]);
    const nV = verdicts.reduce((a, [, n]) => a + n, 0);
    const comp = s.verdicts.COMPLIANT || 0, viol = s.verdicts.VIOLATION || 0;
    mount(ctx.el, html`
      ${pageHead('Tổng quan', 'Tình hình kiểm chứng tuân thủ RFC trên toàn bộ các lần chạy: kết luận, chi phí và sức khoẻ hệ thống.', html`
        <div class="seg" role="group" aria-label="Khoảng thời gian">${RANGES.map(([d, l]) => html`<button data-range="${d}" class="${d === days ? 'on' : ''}">${l}</button>`)}</div>
        <a class="btn primary" href="#/new">${icon('play', 15)}Chạy kiểm chứng</a>`)}
      <div id="onboard"></div>
      <div id="statusline" class="statusline"><span class="muted small">Đang kiểm tra hệ thống…</span></div>
      <div class="kpi-strip">
        ${kpi('Lần chạy', fmt.int(t.runs), html`${t.active ? html`<span class="badge info pulse">${icon('activity', 12)}${t.active} đang chạy</span>` : html`<span>${s.by_status.finished || 0} hoàn tất</span>`}${(s.by_status.failed || 0) + (s.by_status.interrupted || 0) ? html` · <span style="color:var(--critical-text)">${(s.by_status.failed || 0) + (s.by_status.interrupted || 0)} lỗi</span>` : ''}`)}
        ${kpi('Yêu cầu đã kết luận', fmt.int(nV), html`<span style="color:var(--good-text)">${icon('check', 12)} ${comp} tuân thủ</span> · <span style="color:var(--critical-text)">${icon('x', 12)} ${viol} vi phạm</span>`, '', 'shield')}
        ${kpi('Token tiêu thụ', fmt.tok(t.tokens), html`TB ${fmt.tok(t.tokens_per_requirement)} / yêu cầu`)}
        ${kpi('Thời gian / yêu cầu', fmt.sec(t.seconds_per_requirement), html`${fmt.int(t.evidence)} bằng chứng · ${fmt.int(t.tool_calls)} lời gọi công cụ`, '', 'clock')}
      </div>
      <div class="grid g-2-1" style="margin-bottom:16px">
        ${chartCard({ id: 'c-daily', title: 'Lần chạy theo ngày', sub: days ? `${days} ngày gần nhất` : '30 ngày gần nhất', body: columns(daily.map((d) => ({ label: d.date.slice(5).replace('-', '/'), value: d.runs, tip: `<b>${d.date}</b><br>${d.runs} lần chạy · ${d.finished} hoàn tất · ${d.failed} lỗi<br>${fmt.tok(d.tokens)} token` })), { name: 'Lần chạy' }), table: { head: ['Ngày', 'Lần chạy', 'Hoàn tất', 'Lỗi', 'Token'], rows: daily.map((d) => [d.date, d.runs, d.finished, d.failed, fmt.tok(d.tokens)]) } })}
        ${chartCard({ id: 'c-verdict', title: 'Kết luận', sub: 'Nhãn do Verdict engine gán theo bộ quy tắc cố định', body: html`${segmented(verdicts.length ? verdicts.map(([l, n]) => { const [text, , ic] = labelOf(l); return { label: text, value: n, color: LABEL_COLOR[l] || 'var(--warning)', icon: ic }; }) : [])}
          ${Object.keys(s.rules).length ? html`<div class="section" style="margin-top:18px"><h4>Theo quy tắc</h4>${hbars(Object.entries(s.rules).sort((a, b) => b[1] - a[1]).map(([r, n]) => ({ label: r, value: n })), { color: 'var(--series-7)' })}</div>` : ''}`, table: { head: ['Nhãn', 'Số yêu cầu'], rows: verdicts.map(([l, n]) => [labelOf(l)[0], n]) } })}
      </div>
      <div class="grid g3" style="margin-bottom:16px">
        ${chartCard({ id: 'c-roles', title: 'Token theo agent', sub: 'Tổng token vào + ra', body: hbars(s.roles.map((r) => ({ label: r.role, value: r.tokens, sub: `${r.runs}×`, tip: `<b>${r.role}</b><br>${fmt.tok(r.input_tokens)} vào · ${fmt.tok(r.output_tokens)} ra<br>${r.runs} lượt · ${fmt.ms(r.duration_ms / Math.max(1, r.runs))} TB/lượt${r.failures ? `<br>${r.failures} lỗi` : ''}` })), { valueFmt: fmt.tok }), table: { head: ['Agent', 'Lượt', 'Token', 'Lỗi'], rows: s.roles.map((r) => [r.role, r.runs, fmt.tok(r.tokens), r.failures]) } })}
        ${chartCard({ id: 'c-tools', title: 'Công cụ được gọi nhiều nhất', sub: 'Qua Tool gateway', body: hbars(s.tools.slice(0, 8).map((x) => ({ label: x.tool, value: x.count })), { color: 'var(--series-2)' }), table: { head: ['Công cụ', 'Lượt gọi'], rows: s.tools.map((x) => [x.tool, x.count]) } })}
        ${chartCard({ id: 'c-evid', title: 'Bằng chứng', sub: 'Theo tầng (T1 mã · T2 đặc tả · T3 kiểm thử)', body: html`${hbars(s.evidence_by_tier.map((x) => ({ label: x.tier, value: x.count })), { color: 'var(--series-3)' })}<div class="section" style="margin-top:14px"><h4>Theo loại</h4>${hbars(s.evidence_by_kind.slice(0, 5).map((x) => ({ label: x.kind, value: x.count })), { color: 'var(--series-5)' })}</div>`, table: { head: ['Loại', 'Số lượng'], rows: s.evidence_by_kind.map((x) => [x.kind, x.count]) } })}
      </div>
      <div class="grid g-2-1">
        <section class="card flush"><div class="card-head" style="padding:16px 18px 0"><div><h3>Lần chạy gần đây</h3></div><a class="btn sm ghost" href="#/runs">Xem tất cả ${icon('chevron', 13)}</a></div>
          ${runs.runs.length ? html`<div class="table-wrap"><table class="tbl"><thead><tr><th>Yêu cầu</th><th>Kết luận</th><th>Giao thức</th><th>Trạng thái</th><th>Khi nào</th></tr></thead><tbody>
            ${runs.runs.slice(0, 7).map((r) => html`<tr class="click" tabindex="0" data-href="#/runs/${r.run_id}"><td><div class="mono req-id">${(r.verdicts || []).map((v) => v.requirement_id).join(', ') || '–'}</div><div class="muted small mono">${r.run_id}</div></td><td>${(r.verdicts || []).map((v) => verdict(v.label, v.rule))}</td><td>${r.spec.adapter || '–'} <span class="muted small">${modeName(r.spec.mode)}</span></td><td>${status(r.status)}</td><td class="muted nowrap">${fmt.ago(r.started_at || r.created_at)}</td></tr>`)}
          </tbody></table></div>` : empty('Chưa có lần chạy nào', 'Bắt đầu bằng một lần chạy demo để xem các agent phối hợp.', html`<a class="btn primary" href="#/new">Chạy kiểm chứng</a>`)}
        </section>
        <div>${reviewCard(rv)}${attention(s)}</div>
      </div>
      `);
    fillSys();  // dải trạng thái hệ thống: điền khi /api/system có (máy chủ đã làm nóng), và sau mỗi lần vẽ lại
  };
  const fillSys = async () => { const sys = await sysCache; if (!ctx.alive() || !sys) return; const sl = $('#statusline', ctx.el); if (sl) mount(sl, statusline(sys)); const ob = $('#onboard', ctx.el); if (ob && lastRuns === 0) mount(ob, onboarding(sys)); };
  on(ctx.el, 'click', '[data-range]', (b) => { days = Number(b.dataset.range); sessionStorage.setItem('rfcv-range', days); draw(); });
  on(ctx.el, 'click', 'tr[data-href]', (tr) => { location.hash = tr.dataset.href; });
  wireChartCards(ctx.el);
  await draw();
  const timer = setInterval(() => { if (ctx.alive() && hasActive) draw(); }, 5000); ctx.onLeave(() => clearInterval(timer));
}

function kpi(label, value, foot) {
  return html`<div class="kpi"><div class="k-label">${label}</div><div class="k-val">${value}</div><div class="k-foot">${foot}</div></div>`;
}

function onboarding(sys) {
  const keyOk = Object.values(sys.models.models || {}).every((m) => m.key_set);
  return html`<div class="banner info">${icon('zap', 18)}<div><b>Chào mừng. Hệ thống chưa có lần chạy nào.</b>
    <div>${keyOk ? 'Khoá mô hình đã sẵn sàng. ' : html`<b style="color:var(--warning-text)">Chưa có khoá API trong môi trường.</b> `}Chọn một giao thức, chọn <b>Demo mô phỏng</b> để xem các agent phối hợp trong vài chục giây, rồi mở màn hình theo dõi để xem từng thông điệp.</div></div></div>`;
}

function reviewCard(rv) {
  const rate = rv.agreement_rate == null ? '–' : Math.round(rv.agreement_rate * 100) + '%';
  return html`<section class="card"><div class="card-head"><h3>Duyệt & phản hồi</h3><a class="btn sm ghost" href="#/review">Mở ${icon('chevron', 13)}</a></div>
    <div class="grid g3" style="gap:10px;margin-bottom:6px"><div class="stat"><div class="l">Chờ duyệt</div><div class="v" style="${rv.pending ? 'color:var(--warning-text)' : ''}">${rv.pending}</div></div><div class="stat"><div class="l">Đồng thuận người–AI</div><div class="v">${rate}</div></div><div class="stat"><div class="l">Bất đồng</div><div class="v" style="${rv.disagree ? 'color:var(--critical-text)' : ''}">${rv.disagree}</div></div></div>
    <div class="muted small">${rv.decided ? `${rv.decided} nhận định có quyết định.` : 'Chưa có nhận định nào. Người duyệt xác nhận hoặc phản bác kết luận của AI để đo độ tin cậy.'}</div></section>`;
}

function statusline(sys) {
  const models = Object.values(sys.models.models || {}), keysOk = models.every((m) => m.key_set), caps = sys.capabilities;
  const items = [
    [keysOk ? 'ok' : 'bad', 'Khoá mô hình', keysOk ? `${models.length} sẵn sàng` : `thiếu ${models.filter((m) => !m.key_set).map((m) => m.api_key_env).join(', ')}`],
    [caps.executors.some((e) => e.available) ? 'ok' : 'warn', 'Sandbox', caps.executors.filter((e) => e.available).map((e) => e.name).join(', ') || 'chưa có'],
    [caps.code_indexes.some((e) => e.available) ? 'ok' : 'warn', 'Chỉ mục mã', caps.code_indexes.some((e) => e.available) ? 'khả dụng' : 'chưa có'],
    [caps.sut_launchers.length ? 'ok' : 'warn', 'Bộ chạy SUT', caps.sut_launchers.map((x) => x.name).join(', ') || 'chỉ demo'],
    [sys.flags.trace_mirror ? 'warn' : 'ok', 'Bản sao trace', sys.flags.trace_mirror ? 'ĐANG BẬT' : 'tắt'],
  ];
  return html`${items.map(([k, l, d]) => html`<span class="sl-item"><i class="dot ${k}"></i><b>${l}</b><span class="muted">${d}</span></span>`)}<a class="sl-more" href="#/system">Chi tiết ${icon('chevron', 12)}</a>`;
}

function attention(s) {
  if (!s.attention.length) return '';
  return html`<section class="card"><div class="card-head"><h3>Cần chú ý</h3></div>${s.attention.map((a) => html`<a class="health-row" href="#/runs/${a.run_id}" style="color:inherit;text-decoration:none">${icon('alert', 16, 'bad')}<div class="grow"><div class="mono">${a.run_id}</div><div class="muted small">${a.leak && !a.leak.clean ? `Rò rỉ: ${a.leak.count} dấu vết` : (a.error || a.status).slice(0, 110)}</div></div></a>`)}</section>`;
}
