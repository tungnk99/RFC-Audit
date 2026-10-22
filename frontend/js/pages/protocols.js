import { $, api, app, copyBtn, empty, fmt, html, icon, kv, mount, on, pageHead, tabs } from '../lib.js';
import { newRequirementDialog, openEditor } from '../editor.js';

export default async function (ctx) {
  const cat = await api('/api/catalog'); if (!ctx.alive()) return;
  const list = cat.adapters.filter((a) => !a.error);
  const cur = ctx.args[0] || list[0]?.dir;
  ctx.setCrumbs([{ text: 'Giao thức & yêu cầu', href: '#/protocols' }, ...(cur ? [{ text: cur }] : [])]);
  if (!list.length) return mount(ctx.el, html`${pageHead('Giao thức & yêu cầu')}${empty('Chưa có adapter nào', 'Thêm thư mục vào adapters/ (adapter.yaml + examples/*.rbs).')}`);
  let tab = 'overview', detail = null;

  const side = () => html`<section class="card flush">${list.map((a) => html`<a class="list-item ${a.dir === cur ? 'on' : ''}" href="#/protocols/${a.dir}"><b>${a.id}</b><small>${a.specs.map((s) => s.doc).join(' · ')}</small><div style="margin-top:4px"><span class="chip">${a.requirements.length} yêu cầu</span><span class="chip">${a.backend}</span></div></a>`)}</section>`;
  const body = () => {
    const a = detail, m = a.manifest;
    const head = html`<div class="card-head"><div><h2 style="font-size:20px">${a.id} <span class="muted small" style="font-weight:400">v${a.version}</span></h2><p class="sub">Tri thức riêng của đối tượng kiểm chứng, dạng dữ liệu khai báo, không có mã tuỳ ý. Lõi không biết giao thức này.</p></div><a class="btn primary" href="#/new">${icon('play', 14)}Chạy kiểm chứng</a></div>`;
    const t = { overview: overview(a, m), reqs: reqs(a), vocab: vocab(m), checks: checks(a), yaml: html`<div class="row" style="justify-content:flex-end;margin-bottom:6px">${copyBtn(a.yaml)}</div><pre class="code" style="max-height:640px">${a.yaml}</pre>` }[tab];
    const nFail = a.checks.filter((c) => c.status === 'FAIL').length;
    return html`<section class="card">${head}${tabs([['overview', 'Tổng quan'], ['reqs', 'Yêu cầu', a.requirements.length], ['vocab', 'Từ vựng & miền giá trị'], ['checks', 'Kiểm định', nFail ? nFail + ' lỗi' : a.checks.length], ['yaml', 'adapter.yaml']], tab)}${t}</section>`;
  };
  const overview = (a, m) => html`<div class="grid g2"><div>
      <div class="section"><h4>Đặc tả trong phạm vi</h4><div class="table-wrap"><table class="tbl compact"><thead><tr><th>Văn bản</th><th>Vai trò</th><th>Mục xét</th><th>XML</th></tr></thead><tbody>${a.specs.map((s) => html`<tr><td><b>${s.doc}</b></td><td>${s.role === 'primary' ? 'chính' : 'tham chiếu'}</td><td>${s.sections.map((x) => html`<span class="chip mono">§${x}</span>`)}</td><td>${s.xml_available ? html`<span class="badge ok">${icon('check', 12)}có</span>` : html`<span class="badge warn">${icon('alert', 12)}chưa có</span>`}</td></tr>`)}</tbody></table></div>
        <div class="hint" style="margin-top:6px">Agent chỉ thấy câu RFC gốc khi có tệp rfc&lt;số&gt;.xml (RFCXML v3) trong inputs/rfc/.</div></div>
      <div class="section"><h4>Thành phần (component taxonomy)</h4>${a.components.map((c) => html`<span class="chip accent">${c}</span>`)}</div>
      <div class="section"><h4>Gợi ý định vị mã (locator hints)</h4>${Object.entries(m.locator_hints).map(([c, h]) => html`<div style="margin-bottom:8px"><b>${c}</b><div class="muted small">từ khoá: ${(h.keywords || []).join(', ') || '–'}<br>điểm vào: ${(h.entry_points || []).join(', ') || '–'}<br>đường dẫn: ${(h.paths || []).join(', ') || '–'}</div></div>`)}</div></div>
    <div><div class="section"><h4>Đối tượng kiểm chứng (SUT)</h4>${kv([['Kho mã', m.sut.repo], ['Commit cố định', m.sut.commit || html`<span class="badge warn">chưa ghim</span> <span class="muted small">Code gate không ép đúng commit</span>`], ['Công thức build', m.sut.recipe], ['Khởi động', JSON.stringify(m.sut.start)], ['Cờ build', html`${m.build_flags.map((f) => html`<span class="chip mono">${f}</span>`)}`], ['Bản tham chiếu', m.references.join(', ') || '–']])}</div>
      <div class="section"><h4>Phạm vi mã agent được đọc</h4>${kv([['Gồm', m.code_scope.include.map((x) => html`<span class="chip mono">${x}</span>`)], ['Loại trừ', m.code_scope.exclude.map((x) => html`<span class="chip mono">${x}</span>`)]])}</div>
      <div class="section"><h4>Kết luận và backend</h4>${kv([['Miền', m.domain], ['Backend kiểm thử', m.backend], ['Bộ quy tắc kết luận', m.verdict_profile], ['Hash adapter', html`<span class="mono small">${a.digest.slice(0, 26)}…</span> ${copyBtn(a.digest)}`]])}</div></div></div>`;
  const addBtn = (a) => (!app.canEdit ? '' : html`<div class="row" style="justify-content:flex-end;margin-bottom:10px"><button class="btn sm" data-add-req="${a.dir}">${icon('plus', 13)}Thêm yêu cầu</button></div>`);
  const reqs = (a) => a.requirements.length ? html`${addBtn(a)}${a.requirements.map((r) => html`<details class="card" style="padding:0" open><summary style="padding:14px 18px;cursor:pointer;list-style:none"><div class="row"><b class="mono" style="font-size:15px">${r.id}</b><span class="chip accent">${r.modal}</span><span class="chip">loại ${r.rtype}</span><span class="muted small grow">${r.source}</span>${!app.canEdit ? '' : html`<button class="btn sm" data-edit-req="${a.dir}/${r.id}" title="Sửa có kiểm tra bằng Oracle compiler">${icon('edit', 13)}Sửa</button>`}</div></summary><div style="padding:0 18px 16px"><pre class="code">${r.text}</pre></div></details>`)}
    <div class="hint" style="margin-top:10px">RBS (Requirement Behaviour Spec) là đặc tả hành vi đã duyệt: tiền điều kiện, kích hoạt, kỳ vọng, hành vi bị cấm và các biến thể kiểm thử. Oracle được biên dịch từ đây, không phải từ lời của agent.</div>` : html`${addBtn(a)}${empty('Chưa có yêu cầu đã duyệt', 'Thêm yêu cầu bằng nút ở trên, hoặc đặt tệp .rbs vào examples/ của adapter.')}`;
  /* Từ vựng do từng miền/adapter khai báo nên hình dạng không cố định: danh sách, ánh xạ lồng (enums), hoặc giá trị đơn. Vẽ được mọi dạng. */
  const vocabItem = (v) => (Array.isArray(v) ? html`${v.map((x) => html`<span class="chip mono">${typeof x === 'object' ? JSON.stringify(x) : String(x)}</span>`)}`
    : v && typeof v === 'object' ? html`${Object.entries(v).map(([k, x]) => html`<div style="margin:4px 0"><span class="muted small">${k}:</span> ${vocabItem(x)}</div>`)}` : html`<span class="chip mono">${String(v ?? '–')}</span>`);
  const vocab = (m) => { const v = m.vocabulary || {}; return html`<div class="grid g2"><div>${Object.entries(v).map(([k, items]) => html`<div class="section"><h4>${k}</h4>${vocabItem(items)}</div>`)}${Object.keys(v).length ? '' : html`<div class="muted">Adapter không khai báo từ vựng.</div>`}</div>
    <div><div class="section"><h4>Miền giá trị trường (field domains)</h4><table class="tbl compact"><thead><tr><th>Trường</th><th>Khoảng</th><th>Giá trị hay dùng</th></tr></thead><tbody>${Object.entries(m.field_domains || {}).map(([k, d]) => html`<tr><td class="mono">${k}</td><td>${d && d.min != null ? `${d.min} … ${d.max ?? '?'}` : html`<span class="mono small">${JSON.stringify(d)}</span>`}</td><td>${Array.isArray(d?.canonical) ? d.canonical.join(', ') : '–'}</td></tr>`)}</tbody></table></div>
      <div class="section"><h4>Quy tắc nhất quán</h4>${(m.consistency_rules || []).map((r) => html`<pre class="code" style="margin-bottom:6px">${JSON.stringify(r)}</pre>`)}</div></div></div>`; };
  const checks = (a) => { const c = { PASS: 0, FAIL: 0, SKIPPED: 0 }; a.checks.forEach((x) => c[x.status]++);
    return html`<div class="row" style="margin-bottom:12px"><span class="badge ok">${icon('check', 12)}${c.PASS} đạt</span><span class="badge ${c.FAIL ? 'bad' : 'mute'}">${icon('x', 12)}${c.FAIL} lỗi</span><span class="badge mute">${icon('clock', 12)}${c.SKIPPED} bỏ qua</span><span class="muted small">Tương đương <code>rfcv adapter check adapters/${a.dir}</code></span></div>
      <div class="checklist">${a.checks.map((x) => html`<div class="check-row">${icon(x.status === 'PASS' ? 'check' : x.status === 'FAIL' ? 'x' : 'clock', 16, x.status === 'PASS' ? 'ok' : x.status === 'FAIL' ? 'bad' : 'warn')}<span class="mono small">${x.check}</span><span class="muted small">${x.detail}</span></div>`)}</div>`; };

  const draw = () => mount($('#detail', ctx.el), body());
  mount(ctx.el, html`${pageHead('Giao thức & yêu cầu', 'Các đối tượng kiểm chứng đã khai báo: RFC trong phạm vi, SUT, yêu cầu đã duyệt, từ vựng và kết quả kiểm định adapter.')}<div class="split"><div>${side()}</div><div id="detail">${html`<div class="skeleton-stack"><div class="skeleton"></div><div class="skeleton"></div></div>`}</div></div>`);
  on(ctx.el, 'click', '[data-tab]', (b) => { tab = b.dataset.tab; draw(); });
  const reload = async () => { detail = await api(`/api/adapters/${cur}`).catch(() => detail); if (ctx.alive()) draw(); };
  on(ctx.el, 'click', '[data-edit-req]', (b, e) => { e.preventDefault(); openEditor({ kind: 'rbs', name: b.dataset.editReq, title: b.dataset.editReq, onSaved: reload }); });
  on(ctx.el, 'click', '[data-add-req]', (b) => newRequirementDialog(b.dataset.addReq, detail.requirements[0]?.text || 'requirement TLS13-0042 from RFC8446§5.2#p4s3 modal MUST type B\nactor server\ntrigger receive(record) where record.length > 16640\nexpect send_alert(record_overflow) then close within 2000ms\n', reload));
  detail = await api(`/api/adapters/${cur}`).catch(() => null);
  if (!ctx.alive()) return;
  detail ? draw() : mount($('#detail', ctx.el), empty('Không đọc được adapter này'));
}
