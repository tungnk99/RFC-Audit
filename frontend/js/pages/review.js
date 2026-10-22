/* Duyệt & phản hồi: hàng đợi các kết luận cần người xem, thống kê đồng thuận người–AI, và cách phản hồi được dùng để cải thiện hệ thống.
   Theo thiết kế: nhận định của người là bản ghi riêng, không ghi đè nhãn (BR3). */
import { $, api, app, empty, fmt, html, icon, mount, on, pageHead, tabs, toast, verdict } from '../lib.js';
import { chartCard, hbars, segmented, wireChartCards } from '../charts.js';
import { decBadge } from '../review.js';

const WHY = { needs_review: ['Cần xem xét', 'Hệ thống không kết luận được (V0/V1/V4/V7): bắt buộc có người quyết'], violation_confirm: ['Xác nhận vi phạm', 'Báo vi phạm: người cần xác nhận không phải dương tính giả'], sample: ['Mẫu kiểm tra 10%', 'Chọn tất định theo hash để đo độ tin cậy của kết luận tuân thủ'], optional: ['Tuỳ chọn', 'Không bắt buộc'] };
const STATE = { pending: ['chưa duyệt', 'mute', 'clock'], agreed: ['đã đồng ý', 'ok', 'check'], disputed: ['bất đồng', 'bad', 'x'], unsure: ['chưa chắc', 'warn', 'info'] };
const stateBadge = (s, n) => { const [t, c, i] = STATE[s] || STATE.pending; return html`<span class="badge ${c}">${icon(i, 12)}${t}${n > 1 ? html`<em>${n} người</em>` : ''}</span>`; };
const st = { f: 'todo', why: '', q: '' };

export default async function (ctx) {
  let tab = ctx.args[0] || 'queue';
  const draw = async () => {
    const [qr, sum] = await Promise.all([api('/api/reviews/queue'), api('/api/reviews/summary')]); if (!ctx.alive()) return;
    mount(ctx.el, html`${pageHead('Duyệt & phản hồi', 'Con người xem lại kết luận của AI, đồng ý hoặc phản bác kèm lý do. Nhận định lưu riêng, không bao giờ đổi nhãn của hệ thống (BR3), và trở thành dữ liệu để đo độ tin cậy và cải thiện agent.', html`<a class="btn" href="/api/reviews/export" download>${icon('download', 15)}Xuất tập phản hồi</a>`)}
      ${tabs([['queue', 'Hàng đợi', sum.pending || null], ['insights', 'Thống kê & chất lượng AI'], ['guide', 'Cách hoạt động']], tab)}<div id="rv-body"></div>`);
    mount($('#rv-body', ctx.el), tab === 'queue' ? queueView(qr.items) : tab === 'insights' ? insights(sum) : guide());
  };
  const queueView = (items) => {
    const pass = (i) => (st.f === 'todo' ? i.state === 'pending' && i.why !== 'optional' : st.f === 'done' ? i.state === 'agreed' : st.f === 'disputed' ? i.state === 'disputed' || i.state === 'unsure' : true) && (!st.why || i.why === st.why) && (!st.q || `${i.run_id} ${i.requirement_id} ${i.adapter}`.toLowerCase().includes(st.q.toLowerCase()));
    const rows = items.filter(pass), count = (f) => items.filter((i) => (f === 'todo' ? i.state === 'pending' && i.why !== 'optional' : f === 'done' ? i.state === 'agreed' : f === 'disputed' ? i.state === 'disputed' || i.state === 'unsure' : true)).length;
    return html`<section class="card flush"><div class="toolbar"><div class="search">${icon('search', 15)}<input type="search" id="rq" placeholder="Tìm yêu cầu, lần chạy…" value="${st.q}" aria-label="Tìm"></div>
        <div class="seg">${[['todo', 'Cần duyệt'], ['done', 'Đã đồng ý'], ['disputed', 'Bất đồng / chưa chắc'], ['all', 'Tất cả']].map(([k, l]) => html`<button data-f="${k}" class="${st.f === k ? 'on' : ''}">${l} <span class="muted">${count(k)}</span></button>`)}</div>
        <select id="rwhy" aria-label="Lý do vào hàng đợi"><option value="">mọi mức ưu tiên</option>${Object.entries(WHY).map(([k, [t]]) => html`<option value="${k}" ${st.why === k ? 'selected' : ''}>${t}</option>`)}</select></div>
      ${rows.length ? html`<div class="table-wrap"><table class="tbl"><thead><tr><th>Ưu tiên</th><th>Yêu cầu</th><th>Kết luận của hệ thống</th><th>Duyệt</th><th>Nhận định gần nhất</th><th></th></tr></thead><tbody>
        ${rows.map((i) => html`<tr class="click" data-open="${i.run_id}|${i.requirement_id}"><td><span class="prio ${i.why}" title="${WHY[i.why][1]}"><i></i>${WHY[i.why][0]}</span></td>
          <td><b class="mono">${i.requirement_id}</b><div class="muted small mono">${i.run_id} · ${i.adapter || '–'}</div></td><td>${verdict(i.label, i.rule)}</td><td>${stateBadge(i.state, i.reviews)}</td>
          <td class="small">${i.last ? html`${i.last.reviewer} ${decBadge(i.last.decision)} <span class="muted">${fmt.ago(i.last.ts)}</span>` : html`<span class="muted">–</span>`}</td>
          <td style="text-align:right"><a class="btn sm ${i.state === 'pending' ? 'primary' : ''}" href="#/runs/${i.run_id}/tab/review/${i.requirement_id}">${app.readOnly ? 'Xem' : 'Duyệt'}${icon('chevron', 13)}</a></td></tr>`)}</tbody></table></div>`
        : empty(items.length ? 'Không có mục nào khớp bộ lọc' : 'Chưa có kết luận nào để duyệt', 'Kết luận xuất hiện ở đây ngay khi một lần chạy kết thúc.', html`<a class="btn primary" href="#/new">Chạy kiểm chứng</a>`)}</section>`;
  };
  const insights = (s) => {
    const rate = s.agreement_rate, labels = ['COMPLIANT', 'VIOLATION', 'NEEDS_REVIEW'], LV = { COMPLIANT: 'TUÂN THỦ', VIOLATION: 'VI PHẠM', NEEDS_REVIEW: 'CẦN XEM XÉT' };
    const cell = (a, b) => s.matrix.find((m) => m.system === a && m.human === b)?.n || 0, max = Math.max(1, ...s.matrix.map((m) => m.n));
    const tile = (l, v, sub, ic) => html`<div class="card kpi"><div class="k-label">${icon(ic, 14)}${l}</div><div class="k-val">${v}</div><div class="k-foot"><span>${sub}</span></div></div>`;
    if (!s.reviews) return html`<div class="banner info">${icon('info', 18)}<div><b>Chưa có nhận định nào.</b> Hãy mở một kết luận ở tab Hàng đợi và gửi nhận định đầu tiên; thống kê sẽ hiện ở đây.</div></div>`;
    return html`<div class="grid g4" style="margin-bottom:16px">${tile('Nhận định (mới nhất mỗi người)', fmt.int(s.reviews), `${s.decided} có quyết định · ${s.unsure} chưa chắc`, 'users')}${tile('Đồng thuận người–AI', rate == null ? '–' : Math.round(rate * 100) + '%', `${s.agree} đồng ý · ${s.disagree} bất đồng`, 'activity')}${tile('Chờ duyệt', fmt.int(s.pending), 'cần xem xét + vi phạm + mẫu 10%', 'clock')}${tile('Bất đồng', fmt.int(s.disagree), 'người cho rằng nhãn sai', 'alert')}</div>
      <div class="grid g2" style="margin-bottom:16px">
        ${chartCard({ id: 'c-cov', title: 'Độ phủ duyệt', sub: 'Đã có người duyệt trên tổng số cần duyệt', body: hbars(Object.entries(s.coverage).map(([k, v]) => ({ label: WHY[k][0], value: v.total ? Math.round((v.done / v.total) * 100) : 0, sub: `${v.done}/${v.total}`, color: k === 'needs_review' ? 'var(--critical)' : k === 'violation_confirm' ? 'var(--warning)' : 'var(--series-1)' })), { valueFmt: (v) => v + '%' }), table: { head: ['Nhóm', 'Đã duyệt', 'Tổng'], rows: Object.entries(s.coverage).map(([k, v]) => [WHY[k][0], v.done, v.total]) } })}
        <section class="card"><div class="card-head"><div><h3>Ma trận nhầm lẫn</h3><p class="sub">Hàng: nhãn của hệ thống. Cột: nhãn người cho là đúng. Đường chéo là đồng ý.</p></div></div>
          <table class="matrix"><thead><tr><th></th>${labels.map((l) => html`<th>${LV[l]}</th>`)}</tr></thead><tbody>${labels.map((a) => html`<tr><th>${LV[a]}</th>${labels.map((b) => { const n = cell(a, b); const col = a === b ? 'var(--series-1)' : 'var(--critical)'; return html`<td style="background:${n ? `color-mix(in srgb, ${col} ${20 + Math.round((n / max) * 55)}%, transparent)` : 'var(--surface-2)'}" data-tip="${a} → ${b}: ${n}">${n || ''}</td>`; })}</tr>`)}</tbody></table>
          <div class="hint" style="margin-top:8px">Ô đỏ ngoài đường chéo là sai số của AI theo đánh giá của người: dương tính giả (hệ thống VI PHẠM, người TUÂN THỦ) và bỏ sót.</div></section></div>
      <div class="grid g3" style="margin-bottom:16px">
        ${chartCard({ id: 'c-rule', title: 'Đồng thuận theo quy tắc', sub: 'Quy tắc nào hay bị người phản bác', body: hbars(s.by_rule.map((r) => ({ label: r.rule, value: Math.round((r.agree / r.n) * 100), sub: `${r.agree}/${r.n}` })), { valueFmt: (v) => v + '%', color: 'var(--series-3)' }), table: { head: ['Quy tắc', 'Đồng ý', 'Tổng'], rows: s.by_rule.map((r) => [r.rule, r.agree, r.n]) } })}
        ${chartCard({ id: 'c-cause', title: 'Nguyên nhân bất đồng', sub: 'Chỗ cần cải thiện', body: hbars(s.causes.map((c) => ({ label: c.label, value: c.n })), { color: 'var(--series-2)', empty: 'Chưa có bất đồng' }), table: { head: ['Nguyên nhân', 'Số lần'], rows: s.causes.map((c) => [c.label, c.n]) } })}
        ${chartCard({ id: 'c-agent', title: 'Đánh giá agent', sub: 'Tốt / Kém theo từng lượt trả lời', body: s.agent_ratings.length ? html`<div class="hbars">${s.agent_ratings.map((a) => html`<div class="hbar" style="grid-template-columns:minmax(90px,30%) 1fr auto"><div class="hb-label">${a.role}</div>${segmented([{ label: 'Tốt', value: a.good, color: 'var(--good)', icon: 'check' }, { label: 'Kém', value: a.bad, color: 'var(--critical)', icon: 'x' }])}<div class="hb-val">${a.good}/${a.bad}</div></div>`)}</div>` : html`<div class="chart-empty">Chưa có đánh giá agent</div>`, table: { head: ['Agent', 'Tốt', 'Kém'], rows: s.agent_ratings.map((a) => [a.role, a.good, a.bad]) } })}</div>
      <section class="card flush"><div class="card-head" style="padding:16px 18px 0"><div><h3>Các ca bất đồng gần đây</h3><p class="sub">Nguồn tốt nhất để cải thiện prompt, skill và quy tắc</p></div><button class="btn sm" id="copy-digest">${icon('copy', 13)}Sao chép tóm tắt cho sổ theo dõi cải thiện</button></div>
        ${s.disputes.length ? html`<div class="table-wrap"><table class="tbl"><thead><tr><th>Yêu cầu</th><th>Hệ thống → Người</th><th>Quy tắc</th><th>Nguyên nhân</th><th>Lý do</th><th>Người duyệt</th></tr></thead><tbody>${s.disputes.map((d) => html`<tr class="click" data-open="${d.run_id}|${d.requirement_id}"><td class="mono">${d.requirement_id}<div class="muted small">${d.run_id}</div></td><td>${verdict(d.system)} → ${verdict(d.human)}</td><td>${d.rule}</td><td>${(d.causes || []).map((c) => html`<span class="chip warn">${c}</span>`)}</td><td class="small" style="max-width:340px">${(d.reason || '').slice(0, 160)}</td><td>${d.reviewer}<div class="muted small">${fmt.ago(d.ts)}</div></td></tr>`)}</tbody></table></div>` : empty('Chưa có bất đồng', 'Khi người phản bác một kết luận, ca đó hiện ở đây.')}</section>`;
  };
  const guide = () => html`<div class="grid g2"><section class="card"><h3 style="margin-bottom:10px">Vòng phản hồi</h3><ol class="steps">
      <li><b>AI kết luận.</b> Verdict engine gán nhãn bằng bộ quy tắc cố định; agent chỉ đề xuất bằng chứng.</li>
      <li><b>Hệ thống chọn ca cần người.</b> Mọi kết luận <i>Cần xem xét</i>, mọi <i>Vi phạm</i> (để loại dương tính giả), và <b>mẫu ${10}% kết luận Tuân thủ</b> chọn tất định theo hash (cùng lần chạy luôn cùng mẫu, không ai chọn tay).</li>
      <li><b>Người duyệt xem đủ bối cảnh.</b> Yêu cầu của đặc tả, kỳ vọng so với thực tế, đoạn mã có bằng chứng gắn vào từng dòng, nhân chứng độc lập, lý do của quy tắc.</li>
      <li><b>Người ghi nhận định.</b> Đồng ý, không đồng ý (kèm nhãn đúng, nguyên nhân từ bảng cố định, lý do bắt buộc), hoặc chưa chắc. Có thể gắn cờ từng bằng chứng (then chốt / sai / không liên quan) và chấm từng lượt agent.</li>
      <li><b>Nhận định được lưu riêng.</b> Bảng <code>reviews</code> của Evidence store, chỉ ghi thêm, có trigger chặn sửa/xoá; nhãn của hệ thống không bị đổi (BR3).</li>
      <li><b>Phản hồi quay lại cải thiện.</b> Thống kê đo độ tin cậy của AI; ca bất đồng chỉ ra chỗ sửa (prompt, skill, RBS, quy tắc); xuất JSONL làm tập hồi quy.</li></ol></section>
    <section class="card"><h3 style="margin-bottom:10px">Lưu ý để số liệu đáng tin</h3><ul class="steps plain">
      <li><b>Tên người duyệt là tự khai.</b> Giao diện chưa có đăng nhập, nên bản ghi mang tên khai báo, chưa phải danh tính đã xác thực.</li>
      <li><b>Mỗi người một nhận định hiệu lực mỗi yêu cầu.</b> Nhận định mới của cùng người thay thế bản cũ trong thống kê; bản cũ vẫn nằm trong kho để truy vết.</li>
      <li><b>Duyệt độc lập.</b> Để đo đồng thuận người–AI, hãy xem bằng chứng trước khi xem kết luận. Số người duyệt ít thì tỷ lệ đồng thuận dao động mạnh.</li>
      <li><b>Mẫu 10% chỉ có ý nghĩa thống kê khi đủ lớn.</b> Với vài chục yêu cầu, coi đó là kiểm tra chất lượng, không phải ước lượng chính xác.</li>
      <li><b>Dùng phản hồi để đổi prompt/skill thì ghi lại phép đo</b> trong sổ theo dõi cải thiện; xuất JSONL kèm digest của bản kê để biết nhận định ứng với cấu hình nào.</li></ul></section></div>`;

  on(ctx.el, 'click', '[data-tab]', (b) => { tab = b.dataset.tab; history.replaceState(null, '', `#/review/${tab}`); draw(); });
  on(ctx.el, 'click', '[data-f]', (b) => { st.f = b.dataset.f; draw(); });
  on(ctx.el, 'change', '#rwhy', (s) => { st.why = s.value; draw(); });
  on(ctx.el, 'change', '#rq', (i) => { st.q = i.value; draw(); });
  on(ctx.el, 'click', 'tr[data-open]', (tr, e) => { if (e.target.closest('a')) return; const [run, req] = tr.dataset.open.split('|'); location.hash = `#/runs/${run}/tab/review/${req}`; });
  on(ctx.el, 'click', '#copy-digest', async () => { const t = await (await fetch('/api/reviews/digest')).text(); await navigator.clipboard?.writeText(t); toast('Đã sao chép tóm tắt markdown', 'ok'); });
  wireChartCards(ctx.el);
  await draw();
  const timer = setInterval(() => { if (ctx.alive() && tab === 'queue') draw(); }, 15000); ctx.onLeave(() => clearInterval(timer));
}
