import { $, api, app, copyBtn, fmt, html, icon, kv, mount, on, pageHead, tabs } from '../lib.js';
import { openEditor } from '../editor.js';

const INVARIANTS = [
  ['Nhãn chỉ do bộ quy tắc gán', 'Cùng bằng chứng cho cùng nhãn, không phụ thuộc thứ tự; sửa quy tắc luôn đổi phiên bản (hash nội dung).'],
  ['Agent đề xuất, thành phần tất định kiểm chứng', 'Một đề xuất chỉ thành bằng chứng sau khi qua Schema gate / Test driver không dùng LLM.'],
  ['Bằng chứng chỉ ghi thêm', 'SQLite có trigger chặn sửa/xoá và chuỗi hash JCS (RFC 8785); sửa đổi bị phát hiện.'],
  ['Từ chối mặc định mọi lời gọi công cụ', 'Tool gateway chỉ nhận công cụ đã khai báo; công cụ có tác động ngoài đọc bị Registry từ chối.'],
  ['Vùng đặc quyền không đọc dữ liệu không tin cậy', 'Agent đặc quyền không có công cụ đọc mã/đầu ra SUT; chuỗi không tin cậy không vào ngữ cảnh của nó (IFC).'],
  ['Skill chỉ là văn bản', 'Cấm scripts/ và allowed-tools; workspace chỉ đọc.'],
  ['Khoá API chỉ trong LLM gateway', 'Đọc từ biến môi trường; sau lần chạy quét rò rỉ khoá và tệp ngoài phạm vi (leak_scan.json).'],
  ['Lõi không biết miền', 'Domain pack và plugin đi vào qua registry đóng băng; import-linter ép chiều phụ thuộc.'],
];

export default async function (ctx) {
  const s = await api('/api/system'); if (!ctx.alive()) return;
  let tab = ctx.args[0] || 'health';
  const models = Object.entries(s.models.models || {});
  const caps = s.capabilities, reg = s.registry;
  const row = (ok, l, d) => html`<div class="health-row">${icon(ok === true ? 'check' : ok === false ? 'x' : 'alert', 16, ok === true ? 'ok' : ok === false ? 'bad' : 'warn')}<div class="grow"><div>${l}</div><div class="muted small">${d}</div></div></div>`;
  const tbl = (head, rows) => html`<div class="table-wrap"><table class="tbl compact"><thead><tr>${head.map((h) => html`<th>${h}</th>`)}</tr></thead><tbody>${rows.map((r) => html`<tr>${r.map((c) => html`<td>${c}</td>`)}</tr>`)}</tbody></table></div>`;

  const panes = {
    health: () => html`<div class="grid g2"><div>
        <section class="card"><div class="card-head"><h3>Khả năng chạy</h3></div><div class="health">
          ${row(models.every(([, m]) => m.key_set), 'Khoá mô hình', models.map(([n, m]) => `${n}: ${m.key_set ? 'đã đặt' : 'THIẾU ' + m.api_key_env}`).join(' · '))}
          ${caps.code_indexes.map((c) => row(c.available ? true : null, `Chỉ mục mã · ${c.name}`, c.note))}${caps.executors.map((c) => row(c.available ? true : null, `Bộ chạy lệnh · ${c.name}`, c.note))}
          ${row(caps.sut_launchers.length > 0 ? true : null, 'Bộ chạy SUT', caps.sut_launchers.length ? caps.sut_launchers.map((x) => x.name).join(', ') : 'chưa có bộ chạy nào được cài đặt: chỉ chạy được chế độ demo')}
          ${row(s.flags.trace_mirror ? null : true, 'Bản sao trace ra Supabase', s.flags.trace_mirror ? 'ĐANG BẬT: trace được đẩy ra dịch vụ ngoài' : 'tắt (mặc định, an toàn)')}
          ${row(s.flags.unsandboxed_executor ? null : true, 'Bộ chạy lệnh không sandbox', s.flags.unsandboxed_executor ? 'ĐÃ cho phép (RFCV_ALLOW_UNSANDBOXED_EXECUTOR=1): chỉ dùng khi phát triển' : 'không cho phép')}</div></section></div>
      <div><section class="card"><div class="card-head"><h3>Phiên bản</h3></div>${kv(Object.entries(s.versions).map(([k, v]) => [k, v || '–']))}</section>
        <section class="card"><div class="card-head"><h3>Lưu trữ</h3></div>${kv([['Thư mục gốc', html`<span class="mono small">${s.paths.root}</span>`], ['Thư mục lần chạy', html`<span class="mono small">${s.paths.runs}</span>`], ['Số lần chạy', s.storage.runs], ['Dung lượng', `${fmt.bytes(s.storage.bytes)} · ${s.storage.files} tệp`], ['Thư mục mã được chọn', s.paths.code_roots.map((p) => html`<div class="mono small">${p}</div>`)]])}</section></div></div>`,
    models: () => html`<section class="card"><div class="card-head"><div><h3>Mô hình được hỗ trợ</h3><p class="sub">Khai báo một lần, kèm TÊN biến chứa khoá. Giá trị khoá không bao giờ đi qua giao diện.</p></div></div>
        ${tbl(['Tên', 'Nhà cung cấp', 'Mô hình', 'Biến khoá', 'Trạng thái'], models.map(([n, m]) => [html`<b>${n}</b>`, m.provider, html`<code>${m.model}</code>`, html`<code>${m.api_key_env}</code>`, m.key_set ? html`<span class="badge ok">${icon('check', 12)}đã đặt</span>` : html`<span class="badge bad">${icon('x', 12)}chưa đặt</span>`]))}</section>
      <section class="card"><div class="card-head"><div><h3>Agent → mô hình</h3><p class="sub">Verifier và luồng dịch thứ hai nên dùng họ mô hình KHÁC để lỗi ít tương quan. Dùng chung một mô hình thì độc lập đó chưa có.</p></div></div>
        ${tbl(['Agent', 'Mô hình'], Object.entries(s.models.agents || {}).map(([a, m]) => [html`<a href="#/agents/${a.split('.')[0]}">${a}</a>`, m]))}
        ${new Set(Object.values(s.models.agents || {})).size === 1 ? html`<div class="banner warn" style="margin:12px 0 0">${icon('alert', 16)}<div class="small">Mọi agent đang dùng cùng một mô hình: phản biện của Verifier chưa độc lập về họ mô hình.</div></div>` : ''}</section>
      <section class="card"><div class="card-head"><h3>config/models.yaml</h3>${copyBtn(s.models_yaml || '')}</div><pre class="code" style="max-height:420px">${s.models_yaml}</pre><div class="row" style="margin-top:8px"><span class="hint grow">Lần chạy sau dùng cấu hình mới; bản kê lần chạy ghi hash của tệp này. Khoá API không bao giờ được ghi vào đây.</span>${!app.canEdit ? '' : html`<button class="btn" data-edit-models>${icon('edit', 14)}Sửa models.yaml</button>`}</div></section>`,
    audit: () => html`<section class="card flush"><div class="card-head" style="padding:16px 18px 0"><div><h3>Nhật ký thay đổi cấu hình</h3><p class="sub">Mọi lần lưu qua giao diện: ai, khi nào, sửa gì, vì sao. Lịch sử chính thức vẫn là git; đây là bản ghi để khôi phục nhanh và truy vết.</p></div></div>
      ${audit.length ? html`<div class="table-wrap"><table class="tbl"><thead><tr><th>Thời điểm</th><th>Người sửa</th><th>Đối tượng</th><th>Hành động</th><th>Lý do</th><th>Hash sau</th></tr></thead><tbody>${audit.map((a) => html`<tr><td class="nowrap">${fmt.time(a.ts)}</td><td>${a.actor}<div class="muted small">${a.identity}</div></td><td><span class="chip">${a.kind}</span> <span class="mono small">${a.name}</span></td><td>${a.action === 'restore' ? html`<span class="badge warn">khôi phục</span>` : html`<span class="badge info">lưu</span>`}</td><td class="small" style="max-width:360px">${a.note}</td><td class="mono small muted">${String(a.after).slice(7, 19)}…</td></tr>`)}</tbody></table></div>` : html`<div class="empty"><h3>Chưa có thay đổi nào</h3><p>Sửa yêu cầu, lời nhắc, skill hoặc cấu hình mô hình qua giao diện sẽ được ghi ở đây.</p></div>`}</section>`,
    registry: () => html`<div class="grid g2"><section class="card"><div class="card-head"><h3>Miền (domain pack)</h3></div>${tbl(['Tên', 'Phiên bản', 'Agent', 'Nhiệm vụ'], reg.domains.map((d) => [d.name, d.version, d.agents, d.tasks]))}</section>
        <section class="card"><div class="card-head"><h3>Bộ quy tắc kết luận</h3></div>${tbl(['Tên', 'Phiên bản (hash)'], reg.rule_sets.map((r) => [html`<b>${r.name}</b>`, html`<span class="mono small">${r.version.slice(0, 26)}…</span>`]))}</section></div>
      <section class="card"><div class="card-head"><h3>Loại bằng chứng</h3></div>${tbl(['Loại', 'Tầng', 'Phiên bản', 'Chỉ ai được ghi'], reg.evidence_kinds.map((k) => [k.name, html`<span class="chip accent">${k.tier}</span>`, k.version, k.producers.join(', ')]))}</section>
      <section class="card"><div class="card-head"><h3>Nhiệm vụ</h3></div>${tbl(['Nhiệm vụ', 'Agent nhận', 'Loại'], reg.tasks.map((t) => [t.name, t.target_role, t.deterministic ? 'tất định' : 'LLM']))}</section>
      <section class="card"><div class="card-head"><h3>Công cụ (Tool gateway)</h3></div>${tbl(['Công cụ', 'Tác động', 'Dữ liệu'], reg.tools.map((t) => [html`<code>${t.name}</code>`, html`<span class="badge ${t.effect === 'read' ? 'ok' : 'warn'}">${t.effect}</span>`, t.reads_untrusted ? html`<span class="badge warn">không tin cậy</span>` : 'tin cậy']))}</section>
      <section class="card"><div class="card-head"><h3>Nhà cung cấp đã đăng ký</h3></div>${kv([['Backend kiểm thử', reg.backends.join(', ') || '–'], ['Chỉ mục mã', reg.code_indexes.join(', ') || '–'], ['Bộ chạy lệnh', reg.executors.join(', ') || '–'], ['Bộ chạy SUT', reg.sut_launchers.join(', ') || html`<span class="badge warn">chưa có</span>`], ['Nhà cung cấp LLM', reg.llm_providers.join(', ') || '–'], ['Runtime agent', reg.agent_runtimes.join(', ') || '–']])}</section>`,
    safety: () => html`<section class="card"><div class="card-head"><div><h3>Ràng buộc an toàn đang được ép bằng mã</h3><p class="sub">Không nới khi mở rộng. Mỗi ràng buộc có kiểm thử và, với ranh giới kiến trúc, có import-linter trong CI.</p></div></div>
      <div class="checklist">${INVARIANTS.map(([t, d]) => html`<div class="check-row" style="grid-template-columns:22px 280px 1fr">${icon('shield', 16, 'ok')}<b>${t}</b><span class="muted">${d}</span></div>`)}</div></section>`,
  };
  let audit = [];
  const draw = async () => { if (tab === 'audit') audit = (await api('/api/edit/audit')).entries; if (!ctx.alive()) return; mount($('#sys', ctx.el), html`${tabs([['health', 'Tình trạng'], ['models', 'Mô hình', models.length], ['registry', 'Registry & plugin'], ['safety', 'An toàn'], ['audit', 'Nhật ký thay đổi']], tab)}${panes[tab]()}`); };
  mount(ctx.el, html`${pageHead('Hệ thống & mô hình', 'Tình trạng, cấu hình mô hình, thành phần đã đăng ký, các ràng buộc an toàn và nhật ký thay đổi cấu hình.')}<div id="sys"></div>`);
  on(ctx.el, 'click', '[data-tab]', (b) => { tab = b.dataset.tab; history.replaceState(null, '', `#/system/${tab}`); draw(); });
  on(ctx.el, 'click', '[data-edit-models]', () => openEditor({ kind: 'models', name: 'models', title: 'config/models.yaml', onSaved: () => window.dispatchEvent(new HashChangeEvent('hashchange')) }));
  draw();
}
