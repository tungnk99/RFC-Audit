"""Xác thực và phân quyền cho giao diện web: tài khoản, vai trò admin/member, phiên đăng nhập phía máy chủ.

- Mật khẩu băm bằng scrypt (thư viện chuẩn, có muối riêng mỗi tài khoản), so sánh thời gian không đổi; không bao giờ lưu hay ghi log mật khẩu.
- Phiên: mã ngẫu nhiên 256 bit gửi qua cookie HttpOnly + SameSite=Strict; máy chủ chỉ giữ hash của mã (rò rỉ tệp cơ sở dữ liệu không cho mượn phiên).
  Hết hạn khi nhàn rỗi và có hạn tuyệt đối; đổi/đặt lại mật khẩu, khoá hay xoá tài khoản thì thu hồi mọi phiên của tài khoản đó.
- Chống đoán mật khẩu: quá số lần sai trong một khoảng thì tạm khoá theo tài khoản và theo địa chỉ; thông báo lỗi chung (không lộ tài khoản có tồn tại).
- Luôn còn ít nhất một admin đang hoạt động (không cho hạ quyền/khoá/xoá admin cuối cùng).
- Nhật ký an ninh chỉ ghi thêm: đăng nhập, đăng nhập sai, tạo/đổi/khoá/xoá tài khoản.

Vai trò: `admin` làm mọi việc (sửa cấu hình, quản lý người dùng, huỷ lần chạy của người khác); `member` xem, chạy kiểm chứng, huỷ lần chạy của chính mình,
duyệt và phản hồi. Lưu ở `<root>/.rfcv-ui/auth.db` (đã .gitignore).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROLES = ("admin", "member")
MIN_PASSWORD = 10
SESSION_IDLE_S = 12 * 3600
SESSION_MAX_S = 7 * 24 * 3600
LOCK_WINDOW_S = 600
LOCK_USER_FAILS = 5
LOCK_IP_FAILS = 25
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")
_SCRYPT = (2**14, 8, 1)


class AuthError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display: str
    role: str
    disabled: bool = False
    created_at: float = 0.0
    last_login: float | None = None

    def public(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "display": self.display or self.username,
            "role": self.role,
            "disabled": self.disabled,
            "created_at": self.created_at,
            "last_login": self.last_login,
        }


LOCAL_ADMIN = User(0, "local", "Chế độ cục bộ (không đăng nhập)", "admin")


def hash_password(password: str) -> str:
    n, r, p = _SCRYPT
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password(
    secrets.token_urlsafe(12)
)  # để đường "không có tài khoản" tốn thời gian như đường "sai mật khẩu"


def validate_username(name: str) -> str:
    name = name.strip().lower()
    if not _NAME.match(name):
        raise AuthError(
            422, "tên đăng nhập 2–40 ký tự: chữ thường, số, dấu chấm, gạch dưới, gạch ngang; bắt đầu bằng chữ hoặc số"
        )
    return name


def validate_password(password: str, username: str = "") -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(422, f"mật khẩu tối thiểu {MIN_PASSWORD} ký tự")
    if (
        len(username) >= 4 and username.lower() in password.lower()
    ):  # tên ngắn (vd. "an") trùng ngẫu nhiên với từ thường gặp
        raise AuthError(422, "mật khẩu không được chứa tên đăng nhập")
    if len(set(password)) < 4:
        raise AuthError(422, "mật khẩu quá đơn giản")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._lock = threading.RLock()
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, display TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL, pw_hash TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, last_login REAL);
            CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, last_seen REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts (key TEXT NOT NULL, ts REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS attempts_key ON attempts(key, ts);
            CREATE TABLE IF NOT EXISTS security_log (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT, action TEXT NOT NULL, target TEXT, detail TEXT);
            CREATE TRIGGER IF NOT EXISTS security_log_no_update BEFORE UPDATE ON security_log BEGIN SELECT RAISE(ABORT, 'security_log is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS security_log_no_delete BEFORE DELETE ON security_log BEGIN SELECT RAISE(ABORT, 'security_log is append-only'); END;
            """
        )

    # ---- tài khoản --------------------------------------------------------------------------------------------

    @staticmethod
    def _user(row: tuple[Any, ...]) -> User:
        return User(
            int(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            bool(row[4]),
            float(row[5]),
            float(row[6]) if row[6] is not None else None,
        )

    _COLS = "id, username, display, role, disabled, created_at, last_login"

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def active_admins(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0").fetchone()[0])

    def get(self, username: str) -> User | None:
        row = self._conn.execute(
            f"SELECT {self._COLS} FROM users WHERE username=?", (username.strip().lower(),)
        ).fetchone()
        return self._user(row) if row else None

    def users(self) -> list[User]:
        return [self._user(r) for r in self._conn.execute(f"SELECT {self._COLS} FROM users ORDER BY role, username")]

    def create(self, username: str, password: str, role: str, display: str = "", *, actor: str = "hệ thống") -> User:
        name = validate_username(username)
        if role not in ROLES:
            raise AuthError(422, f"vai trò phải là một trong: {', '.join(ROLES)}")
        validate_password(password, name)
        with self._lock:
            if self.get(name):
                raise AuthError(409, "tên đăng nhập đã tồn tại")
            self._conn.execute(
                "INSERT INTO users(username, display, role, pw_hash, created_at) VALUES (?,?,?,?,?)",
                (name, display.strip()[:60], role, hash_password(password), time.time()),
            )
            self.log(actor, "create_user", name, role)
            return self.get(name)  # type: ignore[return-value]

    def _guard_last_admin(self, user: User, *, losing: bool) -> None:
        if losing and user.role == "admin" and not user.disabled and self.active_admins() <= 1:
            raise AuthError(
                409, "không thể làm việc này với admin cuối cùng: hệ thống phải còn ít nhất một admin đang hoạt động"
            )

    def set_password(self, username: str, password: str, *, actor: str) -> None:
        user = self._need(username)
        validate_password(password, user.username)
        with self._lock:
            self._conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(password), user.id))
            self.revoke_user(user.id)
            self.log(actor, "set_password", user.username)

    def change_own_password(self, username: str, current: str, new: str, ip: str) -> str:
        """Đổi mật khẩu của chính mình (phải biết mật khẩu cũ, cùng giới hạn đoán sai); trả phiên mới vì mọi phiên cũ bị thu hồi."""
        key = f"pw:{username}"
        with self._lock:
            if self._fails(key) >= LOCK_USER_FAILS:
                raise AuthError(429, f"nhập sai quá nhiều lần; thử lại sau {LOCK_WINDOW_S // 60} phút")
            row = self._conn.execute("SELECT id, pw_hash FROM users WHERE username=?", (username,)).fetchone()
        if not row or not check_password(current, row[1]):
            with self._lock:
                self._record_fail(key)
                self.log(username, "password_check_failed", None, ip)
            raise AuthError(403, "mật khẩu hiện tại không đúng")
        self.set_password(username, new, actor=username)
        return self.new_session(int(row[0]))

    def set_role(self, username: str, role: str, *, actor: str) -> None:
        user = self._need(username)
        if role not in ROLES:
            raise AuthError(422, f"vai trò phải là một trong: {', '.join(ROLES)}")
        with self._lock:
            self._guard_last_admin(user, losing=role != "admin")
            self._conn.execute("UPDATE users SET role=? WHERE id=?", (role, user.id))
            self.revoke_user(user.id)
            self.log(actor, "set_role", user.username, f"{user.role} → {role}")

    def set_disabled(self, username: str, disabled: bool, *, actor: str) -> None:
        user = self._need(username)
        with self._lock:
            self._guard_last_admin(user, losing=disabled)
            self._conn.execute("UPDATE users SET disabled=? WHERE id=?", (int(disabled), user.id))
            if disabled:
                self.revoke_user(user.id)
            self.log(actor, "disable_user" if disabled else "enable_user", user.username)

    def delete(self, username: str, *, actor: str) -> None:
        user = self._need(username)
        with self._lock:
            self._guard_last_admin(user, losing=True)
            self.revoke_user(user.id)
            self._conn.execute("DELETE FROM users WHERE id=?", (user.id,))
            self.log(actor, "delete_user", user.username)

    def _need(self, username: str) -> User:
        u = self.get(username)
        if u is None:
            raise AuthError(404, "không có tài khoản này")
        return u

    # ---- đăng nhập và phiên -----------------------------------------------------------------------------------

    def _fails(self, key: str) -> int:
        return int(
            self._conn.execute(
                "SELECT COUNT(*) FROM attempts WHERE key=? AND ts>?", (key, time.time() - LOCK_WINDOW_S)
            ).fetchone()[0]
        )

    def _record_fail(self, *keys: str) -> None:
        now = time.time()
        self._conn.executemany("INSERT INTO attempts(key, ts) VALUES (?,?)", [(k, now) for k in keys])
        self._conn.execute("DELETE FROM attempts WHERE ts<?", (now - 2 * LOCK_WINDOW_S,))

    def login(self, username: str, password: str, ip: str) -> tuple[User, str]:
        name = username.strip().lower()
        ukey, ikey = f"u:{name}", f"ip:{ip}"
        with self._lock:
            if self._fails(ukey) >= LOCK_USER_FAILS or self._fails(ikey) >= LOCK_IP_FAILS:
                self.log(name, "login_locked", None, ip)
                raise AuthError(429, f"đăng nhập sai quá nhiều lần; thử lại sau {LOCK_WINDOW_S // 60} phút")
            row = self._conn.execute(f"SELECT {self._COLS}, pw_hash FROM users WHERE username=?", (name,)).fetchone()
        ok = check_password(password, row[7] if row else _DUMMY)  # tính hash ngoài khoá: không nghẽn các đăng nhập khác
        with self._lock:
            if not (row and ok) or row[4]:
                self._record_fail(ukey, ikey)
                self.log(name, "login_failed", None, ip)
                raise AuthError(401, "sai tên đăng nhập hoặc mật khẩu")
            user = self._user(row[:7])
            self._conn.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), user.id))
            self._conn.execute("DELETE FROM attempts WHERE key=?", (ukey,))
            self.log(user.username, "login", None, ip)
            return user, self.new_session(user.id)

    # ---- thiết lập lần đầu --------------------------------------------------------------------------------------

    @property
    def setup_file(self) -> Path:
        return self._path.parent / "setup-code.txt"

    def ensure_setup_code(self) -> str | None:
        """Chưa có tài khoản nào: sinh mã một lần (in ra console và ghi vào tệp) để chỉ người có quyền trên máy chủ mới tạo được admin đầu tiên.
        Đã có tài khoản thì xoá tệp mã nếu còn."""
        with self._lock:
            if self.count() > 0:
                self.setup_file.unlink(missing_ok=True)
                return None
            if self.setup_file.is_file():
                code = self.setup_file.read_text(encoding="utf-8").strip()
                if code:
                    return code
            code = secrets.token_hex(4).upper()
            self.setup_file.write_text(code + "\n", encoding="utf-8")
            return code

    def setup_admin(self, code: str, username: str, password: str, display: str, ip: str) -> tuple[User, str]:
        key = f"setup:{ip}"
        with self._lock:
            if self._fails(key) >= LOCK_USER_FAILS:
                raise AuthError(429, f"nhập sai mã quá nhiều lần; thử lại sau {LOCK_WINDOW_S // 60} phút")
            expected = self.ensure_setup_code()
            if expected is None:
                raise AuthError(409, "hệ thống đã được thiết lập; hãy đăng nhập")
            if not hmac.compare_digest(code.strip().upper().encode(), expected.encode()):
                self._record_fail(key)
                self.log(None, "setup_failed", None, ip)
                raise AuthError(403, "mã thiết lập không đúng")
            user = self.create(username, password, "admin", display, actor="thiết lập lần đầu")
            self.setup_file.unlink(missing_ok=True)
            self._conn.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), user.id))
            return user, self.new_session(user.id)

    def new_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        self._conn.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen) VALUES (?,?,?,?,?)",
            (_hash_token(token), user_id, now, now + SESSION_IDLE_S, now),
        )
        self._conn.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
        return token

    def user_for_token(self, token: str | None) -> User | None:
        if not token:
            return None
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT s.created_at, s.expires_at, u.id, u.username, u.display, u.role, u.disabled, u.created_at, u.last_login FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",
                (_hash_token(token),),
            ).fetchone()
            if not row or row[1] < now or now - row[0] > SESSION_MAX_S or row[6]:
                return None
            self._conn.execute(
                "UPDATE sessions SET expires_at=?, last_seen=? WHERE token_hash=?",
                (min(now + SESSION_IDLE_S, row[0] + SESSION_MAX_S), now, _hash_token(token)),
            )
            return self._user(row[2:])

    def logout(self, token: str | None) -> None:
        if token:
            self._conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))

    def revoke_user(self, user_id: int) -> None:
        self._conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    # ---- nhật ký an ninh --------------------------------------------------------------------------------------

    def log(self, actor: str | None, action: str, target: str | None = None, detail: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO security_log(ts, actor, action, target, detail) VALUES (?,?,?,?,?)",
            (time.time(), actor, action, target, detail),
        )

    def audit(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT ts, actor, action, target, detail FROM security_log ORDER BY seq DESC LIMIT ?", (limit,)
        ).fetchall()
        return [{"ts": t, "actor": a, "action": ac, "target": tg, "detail": d} for t, a, ac, tg, d in rows]

    def close(self) -> None:
        self._conn.close()
