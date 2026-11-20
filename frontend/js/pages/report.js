/* Báo cáo một lần chạy để in hoặc lưu PDF (đưa vào luận văn, gửi người duyệt): kết luận và căn cứ, hành trình các agent,
   điều rút ra, và bản kê đầu vào. Cùng nguồn dữ liệu với trang theo dõi; bố cục in nằm ở layout.css (@media print). */
import { api, copyBtn, fmt, html, icon, kv, labelOf, modeName, mount, on, verdict } from '../lib.js';
import { findingCard } from '../findings-view.js';
import { buildModel, lessonsView, storyView } from '../story.js';

export default async function (ctx) {
  const id = decodeURIComponent(ctx.args[0]);
  ctx.setCrumbs([{ text: 'Lần chạy', href: '#/runs' }, { text: id, href: `#/runs/${id}` }, { text: 'Báo cáo' }]);
  mount(ctx.el, html`<div class="skeleton-stack"><div class="skeleton"></div><div class="skeleton"></div></div>`);
  const events = []; let after = 0;
  const [detail, findings] = await Promise.all([api(`/api/runs/${encodeURIComponent(id)}`), api(`/api/runs/${encodeURIComponent(id)}/findings`).catch(() => ({ findings: [] }))]);
  for (;;) { const r = await api(`/api/runs/${encodeURIComponent(id)}/events?after=${after}&limit=1000`); events.push(...r.events); if (r.events.length < 1000) break; after = r.events[r.events.length - 1].seq; }
  if (!ctx.alive()) return;
  const model = buildModel(events), sp = detail.spec, m = detail.manifest;
  const labels = (detail.verdicts || []).map((v) => `${v.requirement_id}: ${labelOf(v.label)[0]} (${v.rule})`).join('; ');
  mount(ctx.el, html`
    <div class="report-bar no-print"><div><h2>Báo cáo lần chạy</h2><div class="muted small">Bố cục dành cho in. Chọn "Lưu dưới dạng PDF" trong hộp thoại in của trình duyệt.</div></div>
      <div class="row"><a class="btn" href="#/runs/${id}">Quay lại</a><button class="btn primary" id="print">${icon('download', 14)}In / Lưu PDF</button></div></div>
    <article class="report">
      <header class="rep-head"><div class="small muted">RFC-Audit · Báo cáo kiểm chứng tuân thủ</div><h1 class="mono">${id}</h1>
        <div class="row" style="gap:10px">${(detail.verdicts || []).map((v) => html`<span class="rep-verdict">${v.requirement_id} ${verdict(v.label, v.rule)}</span>`)}</div></header>
      ${kv([['Giao thức', sp.adapter], ['Chế độ', modeName(sp.mode)], ['Mã nguồn', sp.code_root || (sp.mode === 'demo' ? 'mô phỏng (không phải kết quả thực nghiệm)' : '–')], ['Tạo lúc', fmt.time(detail.created_at)], ['Thời lượng', fmt.dur(detail.started_at, detail.ended_at)], ['Kết luận', labels || 'chưa có']])}
      ${sp.mode === 'demo' ? html`<div class="banner warn">${icon('alert', 16)}<div>Lần chạy <b>demo</b>: SUT và mã nguồn là bản mô phỏng. Kết quả cho thấy cơ chế phối hợp giữa các agent, không cho biết độ chính xác trên mã thật.</div></div>` : ''}
      <section class="rep-sec"><h2>1. Kết luận và căn cứ</h2>${findings.findings?.length ? findings.findings.map((f) => findingCard(f)) : html`<div class="muted">Chưa có phân tích kết luận.</div>`}
        <p class="small muted">Nhãn do bộ quy tắc cố định gán từ bằng chứng; agent chỉ đề xuất. Mỗi đề xuất chỉ thành bằng chứng sau khi qua cổng tất định.</p></section>
      <section class="rep-sec"><h2>2. Hành trình các agent</h2>${storyView(model, { hideIntro: true })}</section>
      <section class="rep-sec"><h2>3. Điều rút ra</h2>${lessonsView(model)}</section>
      <section class="rep-sec"><h2>4. Bản kê đầu vào (tái lập được)</h2>${m ? html`<table class="tbl compact"><tbody>${Object.entries(m.digests || {}).map(([k, v]) => html`<tr><td>${k}</td><td class="mono small">${v}</td></tr>`)}</tbody></table>` : html`<div class="muted">chưa có bản kê</div>`}
        <p class="small muted">Tạo lúc ${fmt.time(Date.now() / 1000)} từ <span class="mono">trace.db</span>, <span class="mono">evidence.db</span>, <span class="mono">manifest.json</span> của lần chạy.</p></section>
    </article>`);
  on(ctx.el, 'click', '#print', () => { document.querySelectorAll('details').forEach((d) => { d.open = true; }); window.print(); });
}
