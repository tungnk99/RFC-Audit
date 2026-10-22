/* Quản lý người dùng (chỉ admin): tài khoản, vai trò, khoá/mở, đặt lại mật khẩu, nhật ký bảo mật. */
import { $, api, app, closeModal, empty, fmt, html, icon, mount, on, openModal, pageHead, tabs, toast } from '../lib.js';
import { initial, roleBadge } from '../auth.js';

const ACTION = {
  login: ['đăng nhập', 'ok'], login_failed: ['đăng nhập sai', 'warn'], login_locked: ['bị khoá do đoán mật khẩu', 'bad'], password_check_failed: ['đổi mật khẩu: sai mật khẩu cũ', 'warn'],
  setup_failed: ['thiết lập: sai mã', 'warn'], create_user: ['tạo tài khoản', 'info'], set_password: ['đặt/đổi mật khẩu', 'info'], set_role: ['đổi vai trò', 'info'],
  disable_user: ['khoá tài khoản', 'warn'], enable_user: ['mở khoá', 'ok'], delete_user: ['xoá tài khoản', 'bad'],
};
const ROLE_HELP = { admin: 'Làm mọi việc: sửa yêu cầu, lời nhắc, skill, cấu hình mô hình; quản lý người dùng; huỷ lần chạy của người khác.', member: 'Xem mọi thứ, chạy kiểm chứng, huỷ lần chạy của chính mình, duyệt và phản hồi kết luận.' };

function ask(title, body, ok, danger = false) {
  return new Promise((resolve) => {
    openModal(html`<div class="mh"><h3>${title}</h3></div><div class="mb" style="padding:4px 18px 14px"><p class="small" style="margin:0">${body}</p></div>
      <div class="mf"><button class="btn" id="ask-x">Huỷ</button><button class="btn ${danger ? 'danger' : 'primary'}" id="ask-ok">${ok}</button></div>`);
    $('#ask-ok').focus(); $('#ask-x').onclick = () => { closeModal(); resolve(false); }; $('#ask-ok').onclick = () => { closeModal(); resolve(true); };
  });
}

function passwordForm(title, withUser, roles, onDone) {
  openModal(html`<form id="uf" novalidate><div class="mh"><h3>${title}</h3></div>
    <div class="mb" style="padding:10px 18px;display:grid;gap:12px">
      ${withUser ? html`<div class="field"><label for="uf-user">Tên đăng nhập</label><input id="uf-user" type="text" autocomplete="off" autocapitalize="none" spellcheck="false" maxlength="40" placeholder="vd. nguyen.van.a"><span class="hint">Chữ thường, số, dấu chấm, gạch dưới, gạch ngang.</span></div>
        <div class="field"><label for="uf-display">Tên hiển thị (tuỳ chọn)</label><input id="uf-display" type="text" maxlength="60" placeholder="vd. Nguyễn Văn A"></div>
        <div class="field"><label for="uf-role">Vai trò</label><select id="uf-role">${roles.map((r) => html`<option value="${r}" ${r === 'member' ? 'selected' : ''}>${r === 'admin' ? 'Admin' : 'Member'}</option>`)}</select><span class="hint" id="uf-help">${ROLE_HELP.member}</span></div>` : ''}
      <div class="field"><label for="uf-pass">${withUser ? 'Mật khẩu ban đầu' : 'Mật khẩu mới'} (tối thiểu 10 ký tự)</label><input id="uf-pass" type="password" autocomplete="new-password" maxlength="200"><span class="hint">Người dùng nên tự đổi sau lần đăng nhập đầu. Đặt lại mật khẩu sẽ đăng xuất mọi phiên của họ.</span></div>
      <div class="auth-err" id="uf-err" role="alert"></div></div>
    <div class="mf"><button class="btn" type="button" id="uf-x">Huỷ</button><button class="btn primary" type="submit" id="uf-ok">${withUser ? 'Tạo tài khoản' : 'Đặt mật khẩu'}</button></div></form>`);
  $(withUser ? '#uf-user' : '#uf-pass').focus(); $('#uf-x').onclick = closeModal;
  if (withUser) $('#uf-role').onchange = (e) => { $('#uf-help').textContent = ROLE_HELP[e.target.value] || ''; };
  $('#uf').onsubmit = async (e) => {
    e.preventDefault(); $('#uf-err').textContent = ''; $('#uf-ok').disabled = true;
    try { await onDone({ user: $('#uf-user')?.value, display: $('#uf-display')?.value, role: $('#uf-role')?.value, password: $('#uf-pass').value }); closeModal(); }
    catch (x) { $('#uf-err').textContent = x.message; $('#uf-ok').disabled = false; }
  };
}

export default async function (ctx) {
  if (!app.auth) return mount(ctx.el, empty('Máy chủ đang chạy không đăng nhập', 'Khởi động lại không kèm --no-auth để dùng tài khoản và vai trò.'));
  if (!app.isAdmin) return mount(ctx.el, empty('Chỉ admin được vào trang này', 'Member xem, chạy và duyệt được; quản lý người dùng là việc của admin.', html`<a class="btn" href="#/">Về tổng quan</a>`));
  let tab = 'users', data = null, audit = null;
  const me = app.user.username;
  const load = async () => { data = await api('/api/users'); if (tab === 'audit') audit = (await api('/api/users/audit')).entries; if (ctx.alive()) draw(); };
  const act = async (fn, okMsg) => { try { await fn(); if (okMsg) toast(okMsg, 'ok'); await load(); } catch (x) { toast(x.message, 'bad', 7000); load(); } };
  const row = (u) => { const self = u.username === me; return html`<tr class="urow ${u.disabled ? 'off' : ''}"><td><div class="urow-name"><span class="avatar">${initial(u)}</span><div><b>${u.display || u.username}${self ? html` <span class="badge mute">bạn</span>` : ''}</b><small class="mono">${u.username}</small></div></div></td>
    <td>${self ? roleBadge(u.role) : html`<select data-role="${u.username}" aria-label="Vai trò của ${u.username}">${data.roles.map((r) => html`<option value="${r}" ${r === u.role ? 'selected' : ''}>${r === 'admin' ? 'Admin' : 'Member'}</option>`)}</select>`}</td>
    <td>${u.disabled ? html`<span class="badge bad">đã khoá</span>` : html`<span class="badge ok">hoạt động</span>`}</td>
    <td class="muted small" title="${fmt.time(u.last_login)}">${u.last_login ? fmt.ago(u.last_login) : 'chưa đăng nhập'}</td><td class="muted small">${fmt.date(u.created_at)}</td>
    <td><div class="urow-actions"><button class="btn sm" data-pw="${u.username}">${icon('lock', 13)}Đặt lại mật khẩu</button>${self ? '' : html`<button class="btn sm" data-toggle="${u.username}" data-off="${u.disabled ? 0 : 1}">${u.disabled ? 'Mở khoá' : 'Khoá'}</button><button class="btn sm danger" data-del="${u.username}" aria-label="Xoá ${u.username}">${icon('x', 13)}</button>`}</div></td></tr>`; };
  const body = () => tab === 'users'
    ? html`<div class="table-wrap"><table class="tbl"><thead><tr><th>Người dùng</th><th>Vai trò</th><th>Trạng thái</th><th>Đăng nhập gần nhất</th><th>Tạo</th><th></th></tr></thead><tbody>${data.users.map(row)}</tbody></table></div>
      <div class="grid g2" style="margin-top:16px"><div class="banner info">${icon('shield', 18)}<div><b>Admin</b><div class="small">${ROLE_HELP.admin}</div></div></div><div class="banner info">${icon('users', 18)}<div><b>Member</b><div class="small">${ROLE_HELP.member}</div></div></div></div>
      <div class="hint" style="margin-top:6px">Luôn còn ít nhất một admin hoạt động. Mật khẩu băm bằng scrypt; mã phiên chỉ lưu dạng hash. Nhận định, lần sửa và lần chạy được ghi theo tài khoản đăng nhập, không theo tên tự khai.</div>`
    : !audit ? html`<div class="skeleton-stack"><div class="skeleton"></div></div>` : audit.length ? html`<div class="table-wrap"><table class="tbl"><thead><tr><th>Thời điểm</th><th>Sự kiện</th><th>Bởi</th><th>Đối tượng</th><th>Chi tiết</th></tr></thead><tbody>${audit.map((e) => { const [l, k] = ACTION[e.action] || [e.action, 'mute']; return html`<tr><td class="muted small" title="${fmt.time(e.ts)}">${fmt.ago(e.ts)}</td><td><span class="badge ${k}">${l}</span></td><td class="mono">${e.actor || '–'}</td><td class="mono">${e.target || '–'}</td><td class="muted small">${e.detail || ''}</td></tr>`; })}</tbody></table></div><div class="hint" style="margin-top:6px">200 sự kiện gần nhất. Nhật ký chỉ ghi thêm (trigger chặn sửa/xoá) và không bao giờ chứa mật khẩu.</div>` : empty('Chưa có sự kiện');
  const draw = () => mount($('#users', ctx.el), html`${tabs([['users', 'Tài khoản', data.users.length], ['audit', 'Nhật ký bảo mật']], tab)}${body()}`);

  mount(ctx.el, html`${pageHead('Người dùng', 'Tài khoản đăng nhập và vai trò. Admin quản lý ở đây; mọi thao tác ghi đều gắn với tài khoản.', html`<button class="btn primary" id="add-user">${icon('plus', 14)}Thêm người dùng</button>`)}<section class="card" id="users"></section>`);
  on(ctx.el, 'click', '[data-tab]', async (b) => { tab = b.dataset.tab; if (tab === 'audit') { audit = null; draw(); } await load(); });
  on(ctx.el, 'click', '#add-user', () => passwordForm('Thêm người dùng', true, data.roles, async (v) => { await api('/api/users', { body: { username: v.user, display: v.display, role: v.role, password: v.password } }); toast(`Đã tạo ${v.user.trim().toLowerCase()}`, 'ok'); await load(); }));
  on(ctx.el, 'click', '[data-pw]', (b) => { const u = b.dataset.pw; passwordForm(`Đặt lại mật khẩu của ${u}`, false, [], async (v) => { await api(`/api/users/${encodeURIComponent(u)}`, { method: 'PATCH', body: { password: v.password } }); toast('Đã đặt mật khẩu; các phiên của họ bị đăng xuất', 'ok'); await load(); }); });
  on(ctx.el, 'click', '[data-toggle]', async (b) => { const u = b.dataset.toggle, off = b.dataset.off === '1'; if (off && !(await ask(`Khoá ${u}?`, 'Họ bị đăng xuất ngay và không đăng nhập lại được cho đến khi mở khoá.', 'Khoá', true))) return; act(() => api(`/api/users/${encodeURIComponent(u)}`, { method: 'PATCH', body: { disabled: off } }), off ? `Đã khoá ${u}` : `Đã mở khoá ${u}`); });
  on(ctx.el, 'click', '[data-del]', async (b) => { const u = b.dataset.del; if (await ask(`Xoá ${u}?`, 'Tài khoản bị xoá và mọi phiên bị thu hồi. Nhận định và lần sửa họ đã ghi vẫn giữ nguyên tên để truy vết.', 'Xoá', true)) act(() => api(`/api/users/${encodeURIComponent(u)}`, { method: 'DELETE' }), `Đã xoá ${u}`); });
  on(ctx.el, 'change', '[data-role]', (s) => act(() => api(`/api/users/${encodeURIComponent(s.dataset.role)}`, { method: 'PATCH', body: { role: s.value } }), `Đã đổi vai trò của ${s.dataset.role}`));
  await load();
}
