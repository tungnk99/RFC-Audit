/* Đăng nhập, thiết lập lần đầu, menu tài khoản và đổi mật khẩu. Phiên nằm trong cookie HttpOnly nên mã trang không đọc được mã phiên. */
import { $, api, app, closeModal, html, icon, mount, openModal, raw, toast } from './lib.js';

export const ROLE_LABEL = { admin: 'Admin', member: 'Member' };
export const roleBadge = (r) => html`<span class="badge ${r === 'admin' ? 'info' : 'mute'}">${ROLE_LABEL[r] || r}</span>`;
export const initial = (u) => ((u.display || u.username || '?').trim()[0] || '?').toUpperCase();

/* `attrs` là hằng của chính file này (không bao giờ là dữ liệu người dùng) nên đưa thẳng vào thẻ. */
const field = (id, label, type, attrs = '') => html`<div class="field"><label for="${id}">${label}</label><input id="${id}" name="${id}" type="${type}" ${raw(attrs)}></div>`;

/* Hiện màn hình đăng nhập (hoặc thiết lập admin đầu tiên); trả về tài khoản khi thành công. */
export function authScreen(st) {
  return new Promise((resolve) => {
    const root = $('#auth'); $('#shell').hidden = true; root.hidden = false;
    const setup = st.setup_needed;
    mount(root, html`<div class="auth-wrap"><form class="auth-card" id="auth-form" novalidate>
      <div class="auth-brand"><span class="mark">${icon('shield', 20)}</span><div><b>RFC-Audit</b><small>Kiểm chứng tuân thủ RFC</small></div></div>
      <h1>${setup ? 'Thiết lập lần đầu' : 'Đăng nhập'}</h1>
      <p class="muted small">${setup ? 'Chưa có tài khoản nào. Nhập mã thiết lập mà máy chủ in ra khi khởi động (cũng nằm trong tệp .rfcv-ui/setup-code.txt cạnh máy chủ) để tạo admin đầu tiên.' : 'Đăng nhập để chạy kiểm chứng, duyệt kết luận và phản hồi.'}</p>
      ${setup ? field('auth-code', 'Mã thiết lập', 'text', 'autocomplete="off" spellcheck="false" maxlength="40"') : ''}
      ${field('auth-user', 'Tên đăng nhập', 'text', 'autocomplete="username" autocapitalize="none" spellcheck="false" maxlength="80"')}
      ${setup ? field('auth-display', 'Tên hiển thị (tuỳ chọn)', 'text', 'maxlength="60"') : ''}
      ${field('auth-pass', setup ? 'Mật khẩu (tối thiểu 10 ký tự)' : 'Mật khẩu', 'password', setup ? 'autocomplete="new-password" maxlength="200"' : 'autocomplete="current-password" maxlength="200"')}
      <div class="auth-err" id="auth-err" role="alert"></div>
      <button class="btn primary lg" type="submit" id="auth-go">${setup ? 'Tạo admin và vào' : 'Đăng nhập'}</button>
    </form></div>`);
    (setup ? $('#auth-code') : $('#auth-user')).focus();
    $('#auth-form').onsubmit = async (e) => {
      e.preventDefault();
      const err = $('#auth-err'), go = $('#auth-go'); err.textContent = '';
      const v = (id) => $(id)?.value ?? '';
      if (!v('#auth-user').trim() || !v('#auth-pass') || (setup && !v('#auth-code').trim())) { err.textContent = 'Nhập đủ các ô bắt buộc.'; return; }
      go.disabled = true;
      try {
        const body = { username: v('#auth-user'), password: v('#auth-pass') };
        const res = setup ? await api('/api/auth/setup', { body: { ...body, code: v('#auth-code'), display: v('#auth-display') } }) : await api('/api/auth/login', { body });
        root.hidden = true; $('#shell').hidden = false; resolve(res.user);
      } catch (x) { err.textContent = x.message; $('#auth-pass').value = ''; $('#auth-pass').focus(); go.disabled = false; }
    };
  });
}

export function changePasswordModal() {
  openModal(html`<form id="pw-form" novalidate><div class="mh"><h3>Đổi mật khẩu</h3><p class="muted small" style="margin:6px 0 0">Đổi xong, các phiên đăng nhập khác của bạn bị đăng xuất.</p></div>
    <div class="mb" style="padding:10px 18px;display:grid;gap:12px">
      ${field('pw-cur', 'Mật khẩu hiện tại', 'password', 'autocomplete="current-password" maxlength="200"')}
      ${field('pw-new', 'Mật khẩu mới (tối thiểu 10 ký tự)', 'password', 'autocomplete="new-password" maxlength="200"')}
      ${field('pw-new2', 'Nhập lại mật khẩu mới', 'password', 'autocomplete="new-password" maxlength="200"')}
      <div class="auth-err" id="pw-err" role="alert"></div></div>
    <div class="mf"><button class="btn" type="button" id="pw-x">Huỷ</button><button class="btn primary" type="submit" id="pw-ok">Đổi mật khẩu</button></div></form>`);
  $('#pw-cur').focus(); $('#pw-x').onclick = closeModal;
  $('#pw-form').onsubmit = async (e) => {
    e.preventDefault(); const err = $('#pw-err'); err.textContent = '';
    if ($('#pw-new').value !== $('#pw-new2').value) { err.textContent = 'Hai lần nhập mật khẩu mới không khớp.'; return; }
    $('#pw-ok').disabled = true;
    try { await api('/api/auth/password', { body: { current: $('#pw-cur').value, new: $('#pw-new').value } }); closeModal(); toast('Đã đổi mật khẩu', 'ok'); }
    catch (x) { err.textContent = x.message; $('#pw-ok').disabled = false; }
  };
}

export async function logout() {
  app.out = true;  // chặn thông báo "hết hạn phiên" của các lời gọi còn bay
  await api('/api/auth/logout', { body: {} }).catch(() => {});
  location.reload();  // giữ nguyên địa chỉ: đăng nhập lại là về đúng trang đang xem
}

/* Khối tài khoản ở chân thanh bên. Không đăng nhập (--no-auth): chỉ báo chế độ cục bộ. */
export function userChip() {
  if (!app.auth) return html`<div class="uchip local" title="Máy chủ chạy với --no-auth: không có đăng nhập, mọi người là admin cục bộ">${icon('lock', 14)}<span>Không đăng nhập · cục bộ</span></div>`;
  const u = app.user;
  return html`<div class="uwrap"><button class="uchip" id="u-btn" aria-haspopup="menu" aria-expanded="false"><span class="avatar">${initial(u)}</span><span class="uname"><b>${u.display || u.username}</b><small>${ROLE_LABEL[u.role] || u.role}${u.display ? ' · ' + u.username : ''}</small></span>${icon('chevron', 14, 'uc')}</button>
    <div class="umenu" id="u-menu" hidden role="menu">
      <button role="menuitem" id="u-pw">${icon('lock', 14)}Đổi mật khẩu</button>
      <button role="menuitem" id="u-out">${icon('x', 14)}Đăng xuất</button></div></div>`;
}

export function wireUserChip() {
  const btn = $('#u-btn'), menu = $('#u-menu'); if (!btn) return;
  const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
  btn.onclick = (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; btn.setAttribute('aria-expanded', String(!menu.hidden)); };
  $('#u-pw').onclick = () => { close(); changePasswordModal(); };
  $('#u-out').onclick = logout;
  document.addEventListener('click', close, { once: true });
}
