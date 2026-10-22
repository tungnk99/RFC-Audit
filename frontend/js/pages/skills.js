import { $, api, app, copyBtn, empty, html, icon, kv, markdown, mount, on, pageHead, tabs } from '../lib.js';
import { openEditor } from '../editor.js';

export default async function (ctx) {
  const { skills } = await api('/api/skills'); if (!ctx.alive()) return;
  let [scope, name] = ctx.args;
  if (!name && skills.length) { scope = skills[0].scope; name = skills[0].name; }
  ctx.setCrumbs([{ text: 'Skills', href: '#/skills' }, ...(name ? [{ text: name }] : [])]);
  let q = '', file = null, doc = null;
  const scopes = [...new Set(skills.map((s) => s.scope))];
  const side = () => {
    const rows = skills.filter((s) => !q || (s.name + s.description).toLowerCase().includes(q.toLowerCase()));
    return html`<section class="card flush"><div class="toolbar"><div class="search">${icon('search', 15)}<input type="search" id="sq" placeholder="Lọc skill…" value="${q}" aria-label="Lọc skill" style="min-width:0;width:100%"></div></div>
      ${scopes.map((sc) => html`${rows.some((s) => s.scope === sc) ? html`<div class="cmdk-sec">${sc === 'core' ? 'Dùng chung (core)' : 'Riêng giao thức · ' + sc}</div>` : ''}${rows.filter((s) => s.scope === sc).map((s) => html`<a class="list-item ${s.name === name && s.scope === scope ? 'on' : ''}" href="#/skills/${s.scope}/${s.name}"><b class="mono" style="font-size:13px">${s.name}</b><small>${s.used_by.length ? 'dùng bởi ' + s.used_by.join(', ') : 'chưa agent nào khai báo'}</small></a>`)}`)}</section>`;
  };
  const main = () => {
    const s = skills.find((x) => x.name === name && x.scope === scope);
    if (!s || !doc) return empty('Chọn một skill');
    return html`<section class="card"><div class="card-head"><div><h2 style="font-size:20px" class="mono">${s.name}</h2><p class="sub">${s.description}</p></div>${!app.canEdit || file ? '' : html`<button class="btn sm" data-edit-skill="${s.scope}/${s.name}">${icon('edit', 13)}Sửa skill</button>`}</div>
      <div class="row" style="margin-bottom:14px"><span class="chip accent">${s.scope}</span>${s.task_types.map((t) => html`<span class="chip">${t}</span>`)}${s.version ? html`<span class="chip">v${s.version}</span>` : ''}<span class="chip">${s.lines} dòng</span>${s.used_by.map((a) => html`<a class="chip" href="#/agents/${a}">${icon('bot', 12)} ${a}</a>`)}</div>
      ${s.references.length ? tabs([[null, 'SKILL.md'], ...s.references.map((r) => [r, r])].map(([k, l]) => [k ?? '', l]), file || '', 'data-file') : ''}
      <div class="banner info">${icon('info', 16)}<div class="small">Skill chỉ là văn bản hướng dẫn theo chuẩn agentskills.io: cấm <code>scripts/</code> và <code>allowed-tools</code>, không thêm quyền cho agent. Lọc tất định theo kiểu nhiệm vụ trước khi đưa cho mô hình.</div></div>
      ${markdown(doc.text)}</section>`;
  };
  const load = async () => { doc = scope ? await api(file ? `/api/skills/${scope}/${name}?file=${encodeURIComponent(file)}` : `/api/skills/${scope}/${name}`).catch(() => null) : null; };
  const draw = () => { mount($('#sk-side', ctx.el), side()); mount($('#sk-main', ctx.el), main()); const sq = $('#sq', ctx.el); if (sq && q) { sq.focus(); sq.setSelectionRange(q.length, q.length); } };
  mount(ctx.el, html`${pageHead('Skills', 'Thư viện hướng dẫn nghiệp vụ nạp theo nhu cầu (chuẩn agentskills.io). Skill chỉ là văn bản, không chạy mã.')}<div class="split"><div id="sk-side"></div><div id="sk-main"></div></div>`);
  on(ctx.el, 'input', '#sq', (el) => { q = el.value; draw(); });
  on(ctx.el, 'click', '[data-edit-skill]', (b) => openEditor({ kind: 'skill', name: b.dataset.editSkill, title: b.dataset.editSkill, onSaved: async () => { const fresh = await api('/api/skills'); skills.splice(0, skills.length, ...fresh.skills); await load(); if (ctx.alive()) draw(); } }));
  on(ctx.el, 'click', '[data-file]', async (b) => { file = b.dataset.file || null; await load(); draw(); });
  if (!skills.length) return mount(ctx.el, html`${pageHead('Skills')}${empty('Chưa có skill nào', 'Thêm thư mục skills/<phạm vi>/<tên>/SKILL.md.')}`);
  await load(); draw();
}
