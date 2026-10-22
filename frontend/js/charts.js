/* Biểu đồ SVG/HTML viết tay (không thư viện, chạy offline). Theo quy tắc trực quan hoá: một trục, nét mảnh, đầu cột bo 4px
   neo ở đường nền, khoảng hở 2px giữa các mảng, nhãn trực tiếp chọn lọc, lưới mờ, tooltip khi rê chuột, và luôn có bảng thay thế.
   Màu lấy từ biến CSS (--series-1…, --good/--critical/--warning) nên đổi sáng/tối không phải vẽ lại. */
import { html, raw, esc, icon, fmt } from './lib.js';

const tipAttr = (h) => String(h); // chuỗi thường: html`` sẽ thoát khi đặt vào thuộc tính; tooltip đọc lại bằng dataset

/* Thẻ biểu đồ có nút chuyển Biểu đồ/Bảng. `table` = {head:[…], rows:[[…]]} cho cùng dữ liệu. */
export function chartCard({ id, title, sub = '', body, table, legend = '' }) {
  return html`<section class="card chart" id="${id}">
    <div class="card-head"><div><h3>${title}</h3>${sub ? html`<p class="sub">${sub}</p>` : ''}</div>
      ${table ? html`<div class="seg" role="group" aria-label="Kiểu xem"><button class="on" data-view="chart" data-for="${id}">Biểu đồ</button><button data-view="table" data-for="${id}">Bảng</button></div>` : ''}</div>
    ${legend}<div class="chart-body" data-pane="chart">${body}</div>
    ${table ? html`<div class="chart-body" data-pane="table" hidden><div class="table-wrap"><table class="tbl compact"><thead><tr>${table.head.map((h) => html`<th>${h}</th>`)}</tr></thead><tbody>${table.rows.map((r) => html`<tr>${r.map((c) => html`<td>${c}</td>`)}</tr>`)}</tbody></table></div></div>` : ''}
  </section>`;
}
export function wireChartCards(root) {
  root.addEventListener('click', (e) => {
    const b = e.target.closest('[data-view]'); if (!b) return;
    const card = root.querySelector('#' + CSS.escape(b.dataset.for)); if (!card) return;
    card.querySelectorAll('[data-view]').forEach((x) => x.classList.toggle('on', x === b));
    card.querySelector('[data-pane=chart]').hidden = b.dataset.view !== 'chart'; card.querySelector('[data-pane=table]').hidden = b.dataset.view !== 'table';
  });
}

/* Cột theo ngày (một chuỗi). data: [{label, value, tip}] */
export function columns(data, { height = 180, color = 'var(--series-1)', yFmt = fmt.int, name = '' } = {}) {
  const W = 640, padL = 36, padB = 24, padT = 10, H = height; const max = Math.max(1, ...data.map((d) => d.value));
  const { top, ticks } = niceTicks(max); const bw = (W - padL) / data.length; const barW = Math.max(3, Math.min(22, bw - 4));
  const y = (v) => padT + (H - padT - padB) * (1 - v / top);
  const grid = ticks.map((t) => `<line x1="${padL}" x2="${W}" y1="${y(t)}" y2="${y(t)}" class="grid"/><text x="${padL - 6}" y="${y(t) + 4}" class="axis" text-anchor="end">${esc(yFmt(Math.round(t)))}</text>`).join('');
  const step = Math.ceil(data.length / 7);
  const bars = data.map((d, i) => {
    const x = padL + i * bw + (bw - barW) / 2; const h = (H - padT - padB) * (d.value / top); const by = H - padB - h;
    const label = i % step === 0 || i === data.length - 1 ? `<text x="${x + barW / 2}" y="${H - 6}" class="axis" text-anchor="middle">${esc(d.label)}</text>` : '';
    const mark = d.value > 0 ? `<path d="M${x},${H - padB} V${by + 4} a4,4 0 0 1 4,-4 h${barW - 8} a4,4 0 0 1 4,4 V${H - padB} z" fill="${color}"/>` : `<rect x="${x}" y="${H - padB - 1}" width="${barW}" height="1" fill="var(--axis)"/>`;
    return `<g class="hit" data-tip="${esc(tipAttr(d.tip || `<b>${esc(d.label)}</b><br>${esc(name)} ${esc(yFmt(d.value))}`))}"><rect x="${padL + i * bw}" y="${padT}" width="${bw}" height="${H - padT - padB}" fill="transparent"/>${mark}${label}</g>`;
  }).join('');
  return raw(`<svg class="viz" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(name)}">${grid}<line x1="${padL}" x2="${W}" y1="${H - padB}" y2="${H - padB}" class="base"/>${bars}</svg>`);
}

/* Danh sách thanh ngang có nhãn trực tiếp. rows: [{label, value, tip, sub, href}] */
export function hbars(rows, { color = 'var(--series-1)', valueFmt = fmt.int, empty = 'Chưa có dữ liệu' } = {}) {
  if (!rows.length) return html`<div class="chart-empty">${empty}</div>`;
  const max = Math.max(1, ...rows.map((r) => r.value));
  return html`<div class="hbars">${rows.map((r) => html`<div class="hbar" data-tip="${tipAttr(r.tip || `<b>${esc(r.label)}</b><br>${esc(valueFmt(r.value))}`)}">
      <div class="hb-label" title="${r.label}">${r.label}${r.sub ? html`<small>${r.sub}</small>` : ''}</div>
      <div class="hb-track"><div class="hb-fill" style="width:${Math.max(1.5, (r.value / max) * 100)}%;background:${r.color || color}"></div></div>
      <div class="hb-val">${valueFmt(r.value)}</div></div>`)}</div>`;
}

/* Một thanh phân đoạn (tỷ lệ nhãn kết luận). segs: [{label, value, color, icon, tip}] */
export function segmented(segs) {
  const total = segs.reduce((a, s) => a + s.value, 0);
  if (!total) return html`<div class="chart-empty">Chưa có kết luận nào</div>`;
  return html`<div class="segbar" role="img" aria-label="Phân bố kết luận">${segs.filter((s) => s.value).map((s) => html`<div class="seg-part" style="flex:${s.value};background:${s.color}" data-tip="${tipAttr(`<b>${esc(s.label)}</b><br>${s.value} (${Math.round((s.value / total) * 100)}%)`)}"></div>`)}</div>
    <div class="seg-legend">${segs.map((s) => html`<div class="seg-key"><span class="sw" style="background:${s.color}"></span>${icon(s.icon, 13)}<span>${s.label}</span><b>${s.value}</b><small>${total ? Math.round((s.value / total) * 100) : 0}%</small></div>`)}</div>`;
}

/* Đường nhỏ cho thẻ chỉ số. */
export function sparkline(values, { color = 'var(--series-1)', w = 96, h = 28 } = {}) {
  if (values.length < 2 || Math.max(...values) === 0) return raw(`<svg class="spark" width="${w}" height="${h}"></svg>`);
  const max = Math.max(...values), pts = values.map((v, i) => [(i / (values.length - 1)) * (w - 6) + 3, h - 4 - (v / max) * (h - 8)]);
  const last = pts[pts.length - 1];
  return raw(`<svg class="spark" width="${w}" height="${h}" aria-hidden="true"><polyline fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="${pts.map((p) => p.join(',')).join(' ')}"/><circle cx="${last[0]}" cy="${last[1]}" r="3" fill="${color}" stroke="var(--surface)" stroke-width="2"/></svg>`);
}

function niceTicks(max) { const base = [1, 2, 5]; let step = 1; for (let m = 1; ; m *= 10) { const s = base.find((b) => max / (b * m) <= 4); if (s) { step = s * m; break; } } const top = Math.max(step, Math.ceil(max / step) * step); const ticks = []; for (let v = 0; v <= top; v += step) ticks.push(v); return { top, ticks }; }
function niceMax(v) { const p = 10 ** Math.floor(Math.log10(v)); const n = v / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p; }
