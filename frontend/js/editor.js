/* Bộ soạn thảo có kiểm soát (yêu cầu RBS, lời nhắc, hồ sơ agent, skill, cấu hình mô hình).
   Không lưu gì mà chưa qua đúng cổng kiểm tra của lõi; chống ghi đè khi tệp đã bị người khác đổi; bắt buộc ghi lý do;
   giữ phiên bản cũ để khôi phục; mọi lần lưu vào nhật ký kiểm toán. Xem backend/src/rfcv/api/editing.py. */
import { unified } from './diff.js';
import { $, $$, api, app, closeModal, ensureWho, fmt, html, icon, markdown, mount, on, openModal, toast, who } from './lib.js';

const HELP = {
  rbs: `# Đặc tả hành vi (RBS)
Mỗi yêu cầu là một tệp \`.rbs\`. Oracle được **biên dịch từ đây**, không phải từ lời của agent, nên mọi chỗ sai ở đây đi thẳng vào kết luận.

\`\`\`
requirement TLS13-0042 from RFC8446§5.2#p4s3 modal MUST type B
actor server
state connected
trigger receive(record) where record.length > 16640
expect send_alert(record_overflow) then close within 2000ms
forbid send(application_data)
variants boundary(record.length, 16641), max(record.length), random(record.length, k=6, stratified)
\`\`\`

- Sự kiện, trạng thái, cảnh báo phải có trong **từ vựng của adapter** (tab Giao thức → Từ vựng).
- Mã yêu cầu trong tệp phải trùng tên tệp.
- Sửa yêu cầu đã duyệt là thay đổi đặc tả: lần chạy sau dùng oracle mới (hash oracle ghi trong bằng chứng), lần chạy cũ giữ nguyên.`,
  prompt: `# Lời nhắc agent
Lời nhắc vai trò được nạp làm system prompt. Mỗi thay đổi đổi **digest lời nhắc** trong bản kê lần chạy sau.

- Đừng nới ranh giới an toàn bằng lời: vùng tin cậy và công cụ do mã và \`role.yaml\` quyết định, lời nhắc không thêm được quyền.
- Khối \`<!-- playbook:begin -->\` của Planner được sinh từ dữ liệu của miền (\`sync_prompt\`): sửa tay sẽ làm lệch.
- Trước khi đổi lời nhắc, xem sổ theo dõi cải thiện (docs/05_project/improvement_log.md) và ghi lại phép đo sau khi đổi.`,
  role: `# Hồ sơ agent (role.yaml)
Khai báo công cụ, skill, trường ngữ cảnh, ngân sách mỗi nhiệm vụ. **Vùng tin cậy và schema đầu ra là kiến trúc** do mã khai báo: \`role.yaml\` phải khớp, nếu không PolicyStore từ chối.

- Agent đặc quyền không bao giờ có công cụ đọc dữ liệu không tin cậy.
- Skill khai báo phải tồn tại trong thư viện skill.`,
  skill: `# Skill (SKILL.md)
Chỉ là văn bản hướng dẫn theo chuẩn agentskills.io. Phần đầu (frontmatter) có \`name\` trùng tên thư mục, \`description\`, và \`metadata.rfcv-task-types\`.

- Cấm \`scripts/\` và \`allowed-tools\`. Skill không thêm quyền cho agent.
- Mô tả (description) quyết định mô hình có nạp skill hay không: viết rõ **khi nào dùng**.`,
  models: `# Cấu hình mô hình
Phần \`models\` khai báo mô hình (nhà cung cấp, id, **tên** biến chứa khoá). Phần \`agents\` gán agent → mô hình.

- **Không bao giờ ghi khoá API vào tệp này**: chỉ ghi tên biến môi trường ở \`api_key_env\`.
- Verifier và luồng dịch thứ hai nên dùng họ mô hình khác để lỗi ít tương quan.`,
};
const KIND_NAME = { rbs: 'Yêu cầu RBS', prompt: 'Lời nhắc agent', role: 'Hồ sơ agent', skill: 'Skill', models: 'Cấu hình mô hình' };
let E = null;

export async function openEditor({ kind, name, title = name, create = false, template = '', onSaved = null }) {
  closeEditor();
  if (!app.canEdit) { toast(app.readOnly ? 'Máy chủ đang ở chế độ chỉ đọc' : 'Chỉ admin được sửa cấu hình', 'bad'); return; }
  let data = { text: template, sha: null, history: [], live_runs: 0 };
  if (!create) { try { data = await api(`/api/edit/read?kind=${kind}&name=${encodeURIComponent(name)}`); } catch (e) { toast(e.message, 'bad'); return; } }
  const el = document.createElement('div'); el.className = 'explorer editor'; el.id = 'editor'; document.body.appendChild(el);
  E = { el, kind, name, title, create, orig: create ? '' : data.text, sha: data.sha, text: data.text, hist: data.history || [], res: null, tab: 'check', note: '', busy: false, onSaved, compare: null, conflict: null, vtimer: null, live: data.live_runs };
  draw(); wire(el); validateNow();
  document.addEventListener('keydown', keys);
}
export function closeEditor() { if (!E) return; clearTimeout(E.vtimer); E.el.remove(); document.removeEventListener('keydown', keys); E = null; }
const dirty = () => E && E.text !== E.orig;
function keys(e) {
  if (!E) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
  if (e.key === 'Escape' && !$('#modal:not([hidden])')) tryClose();
}
function tryClose() { if (!dirty() || confirm('Có thay đổi chưa lưu. Đóng và bỏ thay đổi?')) closeEditor(); }

/* ---------- vẽ ---------- */
function draw() {
  mount(E.el, html`<div class="ex-head"><button class="btn sm" data-ed-close>${icon('x', 14)}Đóng</button><b>${E.create ? 'Thêm' : 'Sửa'} · ${KIND_NAME[E.kind]}</b><span class="mono small">${E.title}</span>${dirty() ? html`<span class="badge warn">${icon('alert', 12)}chưa lưu</span>` : html`<span class="badge mute">đã lưu</span>`}
      ${E.live ? html`<span class="badge warn">${E.live} lần chạy đang diễn ra dùng bản cũ</span>` : ''}<span class="grow"></span><span class="muted small">Ctrl+S để lưu · bạn: <b>${who() || 'chưa khai tên'}</b></span></div>
    <div class="ed-body"><section class="ed-main"><div class="ed-wrap"><div class="gutter" id="ed-gut"></div><textarea id="ed-ta" spellcheck="false" wrap="off" aria-label="Nội dung"></textarea></div>
        <div class="ed-foot"><input type="text" id="ed-note" maxlength="500" placeholder="Lý do thay đổi (bắt buộc, ghi vào nhật ký kiểm toán)" value="${E.note}" aria-label="Lý do thay đổi"><button class="btn" data-ed-validate>${icon('shield', 14)}Kiểm tra</button><button class="btn primary" data-ed-save ${canSave() ? '' : 'disabled'}>${icon('check', 14)}Lưu thay đổi</button></div></section>
      <aside class="ed-side" id="ed-side"></aside></div>`);
  const ta = $('#ed-ta', E.el); ta.value = E.text; gutter(); side();
}
function gutter() { const n = E.text.split('\n').length; $('#ed-gut', E.el).textContent = Array.from({ length: n }, (_, i) => i + 1).join('\n'); }
const canSave = () => dirty() && E.res?.ok && E.note.trim().length >= 3 && !E.busy;
function refreshSave() { const b = $('[data-ed-save]', E.el); if (b) b.disabled = !canSave(); }
function side() {
  const side = $('#ed-side', E.el); if (!side) return; const r = E.res;
  const tabs = [['check', 'Kiểm tra'], ['diff', 'So sánh'], ['hist', `Lịch sử (${E.hist.length})`], ['help', 'Trợ giúp']];
  const body = E.tab === 'check' ? checkPane(r) : E.tab === 'diff' ? diffPane() : E.tab === 'hist' ? histPane() : markdown(HELP[E.kind]);
  mount(side, html`<div class="tabs mini">${tabs.map(([k, l]) => html`<button data-ed-tab="${k}" class="${E.tab === k ? 'on' : ''}">${l}</button>`)}</div><div class="ed-pane">${E.conflict ? html`<div class="banner bad">${icon('alert', 16)}<div><b>${E.conflict}</b><div style="margin-top:6px"><button class="btn sm" data-ed-reload>Tải bản mới (giữ nháp để gộp)</button></div></div></div>` : ''}${body}</div>`);
}
function checkPane(r) {
  if (!r) return html`<div class="muted"><span class="spin"></span>đang kiểm tra…</div>`;
  const info = r.info || {};
  return html`<div class="banner ${r.ok ? 'ok' : 'bad'}">${icon(r.ok ? 'check' : 'x', 16)}<div><b>${r.ok ? 'Qua kiểm tra của lõi' : 'Chưa qua kiểm tra'}</b>${r.errors.length ? html`<ul>${r.errors.map((e) => html`<li class="mono small">${e}</li>`)}</ul>` : ''}</div></div>
    ${r.warnings.length ? html`<div class="banner warn">${icon('alert', 16)}<div><b>Lưu ý</b><ul>${r.warnings.map((w) => html`<li>${w}</li>`)}</ul></div></div>` : ''}
    ${r.ok && Object.keys(info).length ? html`<h4 class="sh">Kết quả biên dịch / nạp</h4><dl class="kv">${Object.entries(info).filter(([k]) => k !== 'new').map(([k, v]) => html`<dt>${k}</dt><dd class="mono small">${Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>`)}</dl>` : ''}
    <div class="hint small muted" style="margin-top:10px">Kiểm tra dùng đúng cổng mà lõi dùng khi chạy (parser và Oracle compiler, PolicyStore, SkillRegistry, ModelsConfig), không phải bản sao.</div>`;
}
function diffPane() {
  const base = E.compare ? E.compare.text : E.orig, label = E.compare ? `phiên bản ${E.compare.id}` : 'bản đã lưu';
  const u = unified(base, E.text);
  if (!u.added && !u.removed) return html`<div class="muted">Không có khác biệt so với ${label}.</div>`;
  return html`<div class="row small" style="margin-bottom:8px"><span class="badge ok">+${u.added}</span><span class="badge bad">−${u.removed}</span><span class="muted">so với ${label}</span>${E.compare ? html`<button class="btn sm" data-ed-clearcmp>về bản đã lưu</button>` : ''}</div>
    <div class="udiff">${u.rows.map((r) => (r.k === 'gap' ? html`<div class="ud gap">${r.text}</div>` : html`<div class="ud ${r.k === '+' ? 'add' : r.k === '-' ? 'del' : ''}"><span class="n">${r.n1 ?? ''}</span><span class="n">${r.n2 ?? ''}</span><span class="s">${r.k === ' ' ? '' : r.k}</span><code>${r.text}</code></div>`))}</div>`;
}
function histPane() {
  if (!E.hist.length) return html`<div class="muted">Chưa có phiên bản nào được lưu qua giao diện. Lần lưu đầu tiên sẽ giữ lại bản gốc.</div>`;
  return html`<div class="hist">${E.hist.map((h) => html`<div class="hv"><div class="row"><b class="mono small">${h.id}</b><span class="chip ${h.action === 'restore' ? 'warn' : h.action === 'baseline' ? '' : 'accent'}">${h.action === 'baseline' ? 'bản gốc' : h.action === 'restore' ? 'khôi phục' : 'lưu'}</span></div>
    <div class="small">${h.note || '–'}</div><div class="muted small">${h.actor} · ${fmt.time(h.ts)} · ${fmt.bytes(h.bytes)}</div>
    <div class="row" style="margin-top:6px"><button class="btn sm" data-ed-cmp="${h.id}">So với bản đang sửa</button><button class="btn sm" data-ed-restore="${h.id}">Khôi phục</button></div></div>`)}</div>`;
}

/* ---------- hành động ---------- */
function validateSoon() { clearTimeout(E.vtimer); E.res = null; if (E.tab === 'check') side(); E.vtimer = setTimeout(validateNow, 650); refreshSave(); }
async function validateNow() {
  if (!E) return; const mine = E.text;
  try { const r = await api('/api/edit/validate', { body: { kind: E.kind, name: E.name, text: mine } }); if (E && E.text === mine) E.res = r; }
  catch (e) { if (E) E.res = { ok: false, errors: [e.message], warnings: [], info: {} }; }
  if (E) { if (E.tab === 'check') side(); refreshSave(); }
}
async function save() {
  if (!E || !canSave()) { if (E && dirty() && E.note.trim().length < 3) { toast('Hãy ghi lý do thay đổi', 'bad'); $('#ed-note', E.el).focus(); } return; }
  const actor = await ensureWho(); if (!actor) return;
  E.busy = true; refreshSave();
  try {
    const r = await api('/api/edit/save', { body: { kind: E.kind, name: E.name, text: E.text, base_sha: E.sha, note: E.note, actor } });
    E.orig = E.text; E.sha = r.sha; E.note = ''; E.conflict = null; E.compare = null; E.create = false;
    const d = await api(`/api/edit/history?kind=${E.kind}&name=${encodeURIComponent(E.name)}`); E.hist = d.history;
    toast('Đã lưu. Áp dụng cho các lần chạy sau.', 'ok'); const cb = E.onSaved; draw(); validateNow(); if (cb) cb(r);
  } catch (e) {
    if (e.status === 409) { E.conflict = e.message; E.tab = 'check'; } else E.res = { ok: false, errors: e.data?.errors || [e.message], warnings: [], info: {} };
    E.busy = false; side(); refreshSave(); return;
  }
  if (E) { E.busy = false; refreshSave(); }
}
function wire(el) {
  on(el, 'click', '[data-ed-close]', tryClose);
  on(el, 'click', '[data-ed-validate]', () => { clearTimeout(E.vtimer); E.res = null; side(); validateNow(); });
  on(el, 'click', '[data-ed-save]', save);
  on(el, 'click', '[data-ed-tab]', (b) => { E.tab = b.dataset.edTab; side(); });
  on(el, 'click', '[data-ed-clearcmp]', () => { E.compare = null; side(); });
  on(el, 'click', '[data-ed-cmp]', async (b) => { const v = await api(`/api/edit/version?kind=${E.kind}&name=${encodeURIComponent(E.name)}&id=${encodeURIComponent(b.dataset.edCmp)}`); E.compare = { id: b.dataset.edCmp, text: v.text }; E.tab = 'diff'; side(); });
  on(el, 'click', '[data-ed-restore]', async (b) => {
    const actor = await ensureWho(); if (!actor) return; if (dirty() && !confirm('Bản đang sửa chưa lưu sẽ bị thay bằng phiên bản này. Tiếp tục?')) return;
    try { const r = await api('/api/edit/restore', { body: { kind: E.kind, name: E.name, version: b.dataset.edRestore, actor, note: `khôi phục phiên bản ${b.dataset.edRestore}` } }); const d = await api(`/api/edit/read?kind=${E.kind}&name=${encodeURIComponent(E.name)}`); Object.assign(E, { orig: d.text, text: d.text, sha: d.sha, hist: d.history, compare: null, conflict: null }); draw(); validateNow(); toast('Đã khôi phục', 'ok'); if (E.onSaved) E.onSaved(r); }
    catch (e) { toast(e.message, 'bad'); }
  });
  on(el, 'click', '[data-ed-reload]', async () => { const d = await api(`/api/edit/read?kind=${E.kind}&name=${encodeURIComponent(E.name)}`); E.sha = d.sha; E.orig = d.text; E.hist = d.history; E.conflict = null; E.tab = 'diff'; draw(); validateNow(); toast('Đã tải bản mới; so sánh để gộp thay đổi của bạn', 'info'); });
  on(el, 'input', '#ed-ta', (ta) => { E.text = ta.value; gutter(); validateSoon(); const badge = $('.ex-head .badge', E.el); if (badge) { badge.className = `badge ${dirty() ? 'warn' : 'mute'}`; badge.textContent = dirty() ? 'chưa lưu' : 'đã lưu'; } });
  on(el, 'input', '#ed-note', (i) => { E.note = i.value; refreshSave(); });
  on(el, 'scroll', '#ed-ta', () => {});
  el.addEventListener('scroll', (e) => { if (e.target.id === 'ed-ta') $('#ed-gut', el).scrollTop = e.target.scrollTop; }, true);
  el.addEventListener('keydown', (e) => { if (e.target.id === 'ed-ta' && e.key === 'Tab') { e.preventDefault(); const t = e.target, s = t.selectionStart; t.setRangeText('  ', s, t.selectionEnd, 'end'); t.dispatchEvent(new Event('input', { bubbles: true })); } });
}

/* Hộp thoại "Thêm yêu cầu": nhập mã rồi mở bộ soạn thảo với mẫu. */
export function newRequirementDialog(adapter, template, onSaved) {
  openModal(html`<div class="mh"><h3>Thêm yêu cầu cho ${adapter}</h3><p class="muted small" style="margin:6px 0 0">Mã gồm chữ, số, gạch, ví dụ <code>TLS13-0100</code>. Bạn viết RBS ở bước sau; trước khi lưu, Oracle compiler phải biên dịch được.</p></div>
    <div class="mb" style="padding:10px 18px"><input type="text" id="nr-id" maxlength="60" placeholder="TLS13-0100" style="width:100%" aria-label="Mã yêu cầu"></div>
    <div class="mf"><button class="btn" id="nr-x">Huỷ</button><button class="btn primary" id="nr-ok">Tiếp tục</button></div>`);
  const input = $('#nr-id'); input.focus();
  const go = () => { const id = input.value.trim(); if (!/^[A-Za-z][A-Za-z0-9_-]{2,60}$/.test(id)) { input.style.outline = '2px solid var(--critical)'; return; } closeModal(); openEditor({ kind: 'rbs', name: `${adapter}/${id}`, title: `${adapter}/${id}`, create: true, template: template.replace(/TLS13-0042/g, id), onSaved }); };
  $('#nr-x').onclick = closeModal; $('#nr-ok').onclick = go; input.onkeydown = (e) => { if (e.key === 'Enter') go(); };
}
