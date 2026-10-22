import { $, api, app, empty, fmt, html, icon, kv, markdown, mount, on, pageHead, tabs, zoneName } from '../lib.js';
import { openEditor } from '../editor.js';

const STAGE = { planning: 'Lập kế hoạch', investigation: 'Điều tra', pre: 'Trước điều tra', post: 'Sau kết luận', deterministic: 'Tất định' };
const zone = (z) => html`<span class="zone ${z === 'privileged' ? 'privileged' : z === 'quarantine' ? 'quarantine' : 'det'}">${icon(z === 'privileged' ? 'lock' : z === 'quarantine' ? 'shield' : 'cpu', 12)}${z === 'tất định' ? 'tất định' : zoneName(z)}</span>`;

export default async function (ctx) {
  const name = ctx.args[0];
  if (name) return detailPage(ctx, name);
  const [cat, stats] = await Promise.all([api('/api/catalog'), api('/api/stats?days=0')]); if (!ctx.alive()) return;
  const usage = Object.fromEntries(stats.roles.map((r) => [r.role, r]));
  const groups = Object.entries(STAGE).map(([k, l]) => [l, cat.agents.filter((a) => a.stage === k)]).filter(([, a]) => a.length);
  mount(ctx.el, html`${pageHead('Agents', 'Các agent của miền và vùng tin cậy của chúng. Agent chỉ đề xuất; thành phần tất định kiểm chứng và Verdict engine gán nhãn.')}
    <div class="grid g2" style="margin-bottom:20px">
      <div class="banner info">${icon('lock', 18)}<div><b>Vùng đặc quyền</b><div class="small">Quyết định điều phối, không bao giờ có công cụ đọc dữ liệu không tin cậy (mã nguồn, đầu ra SUT).</div></div></div>
      <div class="banner warn">${icon('shield', 18)}<div><b>Vùng cách ly</b><div class="small">Đọc mã nguồn không tin cậy. Chuỗi tự do của nó không đi vào ngữ cảnh agent đặc quyền (kiểm soát luồng thông tin IFC).</div></div></div></div>
    ${groups.map(([l, agents]) => html`<div class="section"><h4>${l}</h4><div class="cards">${agents.map((a) => { const u = usage[a.name];
      return html`<a class="card acard" href="#/agents/${a.name}" style="color:inherit;text-decoration:none"><div class="row" style="justify-content:space-between"><h3>${a.name}</h3>${zone(a.zone)}</div>
        <p>${a.summary || '—'}</p><div>${a.tasks.map((t) => html`<span class="chip accent">${t}</span>`)}</div>
        <div class="row small muted" style="margin-top:10px;justify-content:space-between"><span>${a.wired ? html`<span class="badge ok">${icon('check', 12)}đã nối</span>` : html`<span class="badge warn">${icon('clock', 12)}chưa nối vào luồng chạy</span>`}</span><span>${a.model ? a.model : a.deterministic ? 'không dùng LLM' : html`<span style="color:var(--critical-text)">chưa gán mô hình</span>`}</span></div>
        ${u ? html`<div class="row small" style="margin-top:8px;gap:14px"><span>${u.runs} lượt</span><span>${fmt.tok(u.tokens)} token</span><span>TB ${fmt.ms(u.duration_ms / Math.max(1, u.runs))}</span>${u.failures ? html`<span style="color:var(--critical-text)">${u.failures} lỗi</span>` : ''}</div>` : ''}</a>`; })}</div></div>`)}`);
}

async function detailPage(ctx, name) {
  const [a0, sk] = await Promise.all([api(`/api/agents/${name}`).catch(() => null), api('/api/skills').catch(() => ({ skills: [] }))]); if (!ctx.alive()) return;
  let a = a0;
  const scopeOf = Object.fromEntries(sk.skills.map((s) => [s.name, s.scope]));
  ctx.setCrumbs([{ text: 'Agents', href: '#/agents' }, { text: name }]);
  if (!a) return mount(ctx.el, empty('Không có agent này', '', html`<a class="btn" href="#/agents">Về danh sách</a>`));
  let tab = 'overview';
  const body = () => { const r = a.role, u = a.usage; return ({
    overview: html`<div class="grid g2"><div>${kv([['Vùng tin cậy', zone(a.zone)], ['Giai đoạn', STAGE[a.stage] || a.stage], ['Đã nối vào luồng chạy', a.wired ? 'có' : html`<span class="badge warn">chưa</span>`], ['Schema đầu ra', r.output_schema ? html`<code>${r.output_schema}</code>` : '–'], ['Ngân sách mỗi nhiệm vụ', r.budget_per_task ? html`${r.budget_per_task.llm_calls ? `${r.budget_per_task.llm_calls} lượt LLM · ` : ''}${r.budget_per_task.tool_calls} công cụ · ${fmt.tok(r.budget_per_task.tokens)} token · ${r.budget_per_task.seconds}s` : '–'], ['Tệp mã', a.files.map((f) => html`<span class="chip mono">${f}</span>`)]])}</div>
      <div><div class="section"><h4>Nhiệm vụ nhận</h4>${a.tasks.length ? a.tasks.map((t) => html`<span class="chip accent">${t.name}${t.deterministic ? ' · tất định' : ''}</span>`) : html`<span class="muted">không nhận nhiệm vụ do Hub giao</span>`}</div>
        <div class="section"><h4>Trường ngữ cảnh được nhận</h4>${(r.context_fields || []).map((f) => html`<span class="chip mono">${f}</span>`)}${(r.context_fields || []).length ? '' : html`<span class="muted">–</span>`}</div></div></div>`,
    prompt: a.prompt ? html`<div class="banner info">${icon('info', 16)}<div class="small">Đây là lời nhắc vai trò được nạp làm system prompt. Khối sổ tay điều tra (nếu có) được sinh từ dữ liệu của miền.</div></div>${markdown(a.prompt)}` : empty('Agent này không có lời nhắc', 'Thành phần tất định không gọi LLM.'),
    tools: a.tools.length ? html`<div class="table-wrap"><table class="tbl"><thead><tr><th>Công cụ</th><th>Tác động</th><th>Dữ liệu</th></tr></thead><tbody>${a.tools.map((t) => html`<tr><td class="mono">${t.name}</td><td><span class="badge ${t.effect === 'read' ? 'ok' : 'warn'}">${t.effect || '–'}</span></td><td>${t.reads_untrusted ? html`<span class="badge warn">${icon('alert', 12)}đọc dữ liệu không tin cậy</span>` : html`<span class="muted">tin cậy</span>`}</td></tr>`)}</tbody></table></div><div class="hint" style="margin-top:8px">Mọi lời gọi đi qua Tool gateway: từ chối mặc định, công cụ phải có khai báo trong registry, tác động ngoài đọc bị chặn.</div>` : empty('Không có công cụ', 'Agent này chỉ đọc ngữ cảnh do Hub dựng.'),
    skills: (r.skills || []).length ? html`<div class="cards">${r.skills.map((s) => html`<a class="card acard" href="#/skills/${scopeOf[s] || 'core'}/${s}" style="color:inherit;text-decoration:none"><b class="mono">${s}</b><div class="muted small">${scopeOf[s] || ''}</div></a>`)}</div><div class="hint" style="margin-top:8px">Skill chỉ là văn bản hướng dẫn (không có script). Agent tự quyết nạp skill nào trong số được đưa.</div>` : empty('Không khai báo skill'),
    stats: u.runs ? html`<div class="grid g4">${[['Lượt chạy', u.runs], ['Token', fmt.tok(u.tokens)], ['Công cụ', u.tool_calls], ['Lỗi', u.failures]].map(([l, v]) => html`<div class="stat"><div class="l">${l}</div><div class="v">${v}</div></div>`)}</div>
      ${kv([['Token vào / ra', `${fmt.tok(u.input_tokens)} / ${fmt.tok(u.output_tokens)}`], ['Thời gian TB mỗi lượt', fmt.ms(u.duration_ms / u.runs)], ['Token TB mỗi lượt', fmt.tok(Math.round(u.tokens / u.runs))]])}` : empty('Chưa có số liệu', 'Agent này chưa chạy trong lần nào.'),
  }[tab]); };
  const editable = () => app.canEdit && !a.deterministicOnly && a.role && Object.keys(a.role).length;
  const draw = () => mount($('#agent', ctx.el), html`<div class="card-head"><div><div class="row"><h2 style="font-size:22px">${a.name}</h2>${zone(a.zone)}</div><p class="sub">${a.summary}</p></div>
    ${editable() ? html`<div class="row"><button class="btn sm" data-edit="prompt">${icon('edit', 13)}Sửa lời nhắc</button><button class="btn sm" data-edit="role">${icon('edit', 13)}Sửa hồ sơ (role.yaml)</button></div>` : ''}</div>${tabs([['overview', 'Tổng quan'], ['prompt', 'Lời nhắc'], ['tools', 'Công cụ', a.tools.length], ['skills', 'Skill', (a.role.skills || []).length], ['stats', 'Thống kê']], tab)}${body()}`);
  const reload = async () => { a = (await api(`/api/agents/${name}`).catch(() => null)) || a; if (ctx.alive()) draw(); };
  on(ctx.el, 'click', '[data-edit]', (b) => openEditor({ kind: b.dataset.edit, name, title: `${name} · ${b.dataset.edit === 'prompt' ? 'prompt.md' : 'role.yaml'}`, onSaved: reload }));
  mount(ctx.el, html`<a class="backlink" href="#/agents">${icon('chevron', 14)}Tất cả agents</a><section class="card" id="agent"></section>`);
  on(ctx.el, 'click', '[data-tab]', (b) => { tab = b.dataset.tab; draw(); });
  draw();
}
