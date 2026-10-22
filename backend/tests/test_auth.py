"""Xác thực và phân quyền của giao diện web: băm mật khẩu, phiên, chống đoán mật khẩu, admin/member, danh tính do máy chủ gắn."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT
from rfcv.api import auth
from rfcv.api.auth import AuthError, AuthStore
from rfcv.api.runs import RunManager
from rfcv.api.server import build_app
from test_api import KEY_ENV, SECRET, call, make_manager, wait_done
from test_assembly import ScriptedRunner

GOOD = "mat-khau-du-dai-1"


# ---- AuthStore ---------------------------------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AuthStore]:
    s = AuthStore(tmp_path / "state" / "auth.db")
    yield s
    s.close()


def test_password_hash_is_salted_and_verifies() -> None:
    a, b = auth.hash_password(GOOD), auth.hash_password(GOOD)
    assert a != b and GOOD not in a
    assert auth.check_password(GOOD, a) and not auth.check_password(GOOD + "x", a)
    assert not auth.check_password(GOOD, "khong-phai-hash")


def test_password_and_username_policy(store: AuthStore) -> None:
    with pytest.raises(AuthError, match="tối thiểu"):
        store.create("an", "ngan", "member")
    with pytest.raises(AuthError, match="tên đăng nhập"):
        store.create("Có Dấu", GOOD, "member")
    with pytest.raises(AuthError, match="chứa tên đăng nhập"):
        store.create("binh", "xx-binh-xx-99", "member")
    with pytest.raises(AuthError, match="vai trò"):
        store.create("binh", GOOD, "root")
    store.create("an", GOOD, "member")
    with pytest.raises(AuthError, match="đã tồn tại"):
        store.create("AN", GOOD, "member")


def test_login_errors_do_not_reveal_whether_the_account_exists(store: AuthStore) -> None:
    store.create("an", GOOD, "member")
    with pytest.raises(AuthError) as wrong_pw:
        store.login("an", "sai-mat-khau-1", "1.1.1.1")
    with pytest.raises(AuthError) as no_user:
        store.login("khong-co", "sai-mat-khau-1", "1.1.1.1")
    assert (
        (wrong_pw.value.status, wrong_pw.value.message)
        == (no_user.value.status, no_user.value.message)
        == (401, "sai tên đăng nhập hoặc mật khẩu")
    )


def test_repeated_failures_lock_the_account_even_for_the_right_password(store: AuthStore) -> None:
    store.create("an", GOOD, "member")
    for _ in range(auth.LOCK_USER_FAILS):
        with pytest.raises(AuthError) as bad:
            store.login("an", "sai-mat-khau-1", "9.9.9.9")
        assert bad.value.status == 401
    with pytest.raises(AuthError) as locked:
        store.login("an", GOOD, "8.8.8.8")
    assert locked.value.status == 429
    assert any(e["action"] == "login_locked" for e in store.audit())


def test_sessions_store_only_a_hash_and_die_on_logout_password_change_disable_and_expiry(store: AuthStore) -> None:
    store.create("an", GOOD, "member")
    _, token = store.login("an", GOOD, "1.1.1.1")
    raw = sqlite3.connect(store._path).execute("SELECT token_hash FROM sessions").fetchall()  # type: ignore[reportPrivateUsage]
    assert raw and token not in raw[0][0]
    assert store.user_for_token(token) is not None
    store.logout(token)
    assert store.user_for_token(token) is None

    _, token = store.login("an", GOOD, "1.1.1.1")
    store.set_password("an", "mat-khau-moi-22", actor="admin")
    assert store.user_for_token(token) is None  # đổi mật khẩu thu hồi mọi phiên

    _, token = store.login("an", "mat-khau-moi-22", "1.1.1.1")
    store.set_disabled("an", True, actor="admin")
    assert store.user_for_token(token) is None
    with pytest.raises(AuthError):
        store.login("an", "mat-khau-moi-22", "1.1.1.1")
    store.set_disabled("an", False, actor="admin")

    _, token = store.login("an", "mat-khau-moi-22", "1.1.1.1")
    store._conn.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))  # type: ignore[reportPrivateUsage]
    assert store.user_for_token(token) is None


def test_the_last_active_admin_can_never_be_removed_demoted_or_disabled(store: AuthStore) -> None:
    store.create("root1", GOOD, "admin")
    for act in (
        lambda: store.set_role("root1", "member", actor="x"),
        lambda: store.set_disabled("root1", True, actor="x"),
        lambda: store.delete("root1", actor="x"),
    ):
        with pytest.raises(AuthError, match="admin cuối cùng"):
            act()
    store.create("root2", GOOD, "admin")
    store.set_role("root1", "member", actor="x")  # còn admin khác thì được


def test_security_log_is_append_only(store: AuthStore) -> None:
    store.create("an", GOOD, "member")
    con = sqlite3.connect(store._path)  # type: ignore[reportPrivateUsage]
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("DELETE FROM security_log")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("UPDATE security_log SET actor='x'")
    assert GOOD not in json.dumps(store.audit())


# ---- HTTP --------------------------------------------------------------------------------------------------------


@pytest.fixture
def secured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[TestClient, RunManager, Path]]:
    monkeypatch.setenv(KEY_ENV, SECRET)
    root = tmp_path / "root"
    for d in ("adapters", "agents", "skills", "config"):
        shutil.copytree(ROOT / d, root / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    runners: list[ScriptedRunner] = []
    manager = make_manager(tmp_path, runners)
    app = build_app(root, frontend=ROOT.parent / "frontend", manager=manager, agents_root=root / "agents", auth=True)
    with TestClient(app) as client:
        yield client, manager, root


def _login(client: TestClient, user: str, password: str = GOOD) -> int:
    return call(client, "POST", "/api/auth/login", {"username": user, "password": password})[0]


def _seed(root: Path) -> None:
    s = AuthStore(root / ".rfcv-ui" / "auth.db")
    s.create("quan", GOOD, "admin", "Quản trị")
    s.create("an", GOOD, "member")
    s.create("binh", GOOD, "member")
    s.close()


def test_first_run_setup_needs_the_one_time_code_and_closes_afterwards(
    secured: tuple[TestClient, RunManager, Path],
) -> None:
    client, _, root = secured
    status = call(client, "GET", "/api/auth/status")[1]
    assert status == {"auth": True, "setup_needed": True, "user": None, "roles": ["admin", "member"]}
    assert call(client, "GET", "/api/catalog")[0] == 401  # chưa có tài khoản cũng không xem được gì

    code = (
        (root / ".rfcv-ui" / "setup-code.txt").read_text(encoding="utf-8").strip()
        if (root / ".rfcv-ui" / "setup-code.txt").exists()
        else None
    )
    if code is None:  # mã sinh khi `serve` khởi động; ở đây gọi như serve làm
        code = AuthStore(root / ".rfcv-ui" / "auth.db").ensure_setup_code()
    body = {"username": "quan", "password": GOOD, "display": "Quản trị"}
    assert call(client, "POST", "/api/auth/setup", {**body, "code": "SAI-MA"})[0] == 403
    status, res = call(client, "POST", "/api/auth/setup", {**body, "code": code})
    assert status == 201 and res["user"]["role"] == "admin"
    assert call(client, "GET", "/api/catalog")[0] == 200  # đã đăng nhập luôn sau khi thiết lập
    assert not (root / ".rfcv-ui" / "setup-code.txt").exists()
    assert call(client, "POST", "/api/auth/setup", {**body, "username": "khac", "code": code})[0] == 409


def test_session_cookie_is_httponly_and_samesite_strict(secured: tuple[TestClient, RunManager, Path]) -> None:
    client, _, root = secured
    _seed(root)
    r = client.post("/api/auth/login", json={"username": "an", "password": GOOD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "rfcv_session=" in cookie
    assert GOOD not in r.text


def test_every_api_route_requires_a_session_except_the_login_flow(secured: tuple[TestClient, RunManager, Path]) -> None:
    client, _, root = secured
    _seed(root)
    for method, path in (
        ("GET", "/api/catalog"),
        ("GET", "/api/runs"),
        ("GET", "/api/users"),
        ("POST", "/api/runs"),
        ("GET", "/api/edit/list"),
        ("GET", "/api/nope"),
    ):
        assert call(client, method, path, {} if method == "POST" else None)[0] == 401, path
    assert call(client, "GET", "/api/health")[0] == 200
    assert client.get("/").status_code == 200  # màn hình đăng nhập phải tải được
    assert _login(client, "an", "sai-mat-khau-1") == 401
    assert _login(client, "an") == 200
    assert call(client, "GET", "/api/catalog")[0] == 200


def test_member_and_admin_permissions(secured: tuple[TestClient, RunManager, Path]) -> None:
    client, manager, root = secured
    _seed(root)
    assert _login(client, "an") == 200
    # member: xem, chạy được; không quản lý người dùng, không sửa cấu hình
    assert call(client, "GET", "/api/users")[0] == 403
    assert call(client, "POST", "/api/users", {"username": "x1", "password": GOOD, "role": "admin"})[0] == 403
    edit = {"kind": "rbs", "name": "tls13/TLS13-0042", "text": "x", "note": "n"}
    assert call(client, "POST", "/api/edit/save", edit)[0] == 403
    assert call(client, "POST", "/api/edit/restore", {"kind": "rbs", "name": "x", "version": "v"})[0] == 403
    assert call(client, "GET", "/api/edit/list")[0] == 200
    status, res = call(client, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13"}]})
    assert status == 201 and res["runs"][0]["created_by"] == "an"
    run_id = res["runs"][0]["run_id"]
    wait_done(manager, run_id)

    # admin sửa được và mọi hành động mang tên admin
    client.cookies.clear()
    assert _login(client, "quan") == 200
    assert call(client, "GET", "/api/users")[0] == 200
    assert call(client, "GET", "/api/users/audit")[0] == 200


def test_reviewer_identity_comes_from_the_session_not_from_the_request(
    secured: tuple[TestClient, RunManager, Path],
) -> None:
    client, manager, root = secured
    _seed(root)
    assert _login(client, "an") == 200
    run_id = call(client, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13"}]})[1]["runs"][0]["run_id"]
    wait_done(manager, run_id)
    status, res = call(
        client,
        "POST",
        f"/api/runs/{run_id}/reviews",
        {"requirement_id": "TLS13-0042", "reviewer": "quan", "decision": "agree"},
    )
    assert status == 201 and res["review"]["reviewer"] == "an"  # không mạo danh được admin
    status, res = call(
        client, "POST", f"/api/runs/{run_id}/reviews", {"requirement_id": "TLS13-0042", "decision": "agree"}
    )
    assert status == 201 and res["review"]["reviewer"] == "an"  # không gửi tên cũng được


def test_member_cancels_only_their_own_runs(secured: tuple[TestClient, RunManager, Path]) -> None:
    client, manager, root = secured
    _seed(root)
    assert _login(client, "an") == 200
    run_id = call(client, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13"}]})[1]["runs"][0]["run_id"]
    wait_done(manager, run_id)
    client.cookies.clear()
    assert _login(client, "binh") == 200
    assert call(client, "POST", f"/api/runs/{run_id}/cancel", {})[0] == 403
    client.cookies.clear()
    assert _login(client, "quan") == 200
    assert call(client, "POST", f"/api/runs/{run_id}/cancel", {})[0] in (
        200,
        409,
    )  # admin được thử huỷ (lần chạy đã xong: 409)


def test_cross_origin_writes_are_rejected(secured: tuple[TestClient, RunManager, Path]) -> None:
    client, _, root = secured
    _seed(root)
    assert _login(client, "an") == 200
    bad = {"Origin": "http://evil.example"}
    assert call(client, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13"}]}, headers=bad)[0] == 403
    assert call(client, "POST", "/api/auth/logout", {}, headers=bad)[0] == 403
    assert call(client, "POST", "/api/auth/logout", {}, headers={"Origin": "http://testserver"})[0] == 200


def test_user_management_rules_over_http(secured: tuple[TestClient, RunManager, Path]) -> None:
    client, _, root = secured
    _seed(root)
    assert _login(client, "quan") == 200
    status, res = call(
        client, "POST", "/api/users", {"username": "chi", "password": GOOD, "role": "member", "display": "Chị Chi"}
    )
    assert status == 201 and "pw_hash" not in json.dumps(res) and res["user"]["role"] == "member"
    assert call(client, "POST", "/api/users", {"username": "chi", "password": GOOD, "role": "member"})[0] == 409
    assert call(client, "POST", "/api/users", {"username": "yeu", "password": "ngan", "role": "member"})[0] == 422
    listed = call(client, "GET", "/api/users")[1]["users"]
    assert {u["username"] for u in listed} == {"quan", "an", "binh", "chi"}
    assert all(set(u) == {"username", "display", "role", "disabled", "created_at", "last_login"} for u in listed)

    # tự khoá / tự hạ quyền / tự xoá đều bị chặn
    assert call(client, "PATCH", "/api/users/quan", {"disabled": True})[0] == 409
    assert call(client, "PATCH", "/api/users/quan", {"role": "member"})[0] == 409
    assert call(client, "DELETE", "/api/users/quan")[0] == 409

    # khoá người khác thì phiên của họ chết ngay
    other = TestClient(client.app)
    assert _login(other, "chi") == 200
    assert call(other, "GET", "/api/catalog")[0] == 200
    assert call(client, "PATCH", "/api/users/chi", {"disabled": True})[0] == 200
    assert call(other, "GET", "/api/catalog")[0] == 401
    assert (
        call(client, "PATCH", "/api/users/chi", {"disabled": False, "role": "admin", "password": "mat-khau-moi-33"})[0]
        == 200
    )
    assert _login(other, "chi", "mat-khau-moi-33") == 200
    assert call(other, "GET", "/api/users")[0] == 200  # đã lên admin
    assert call(client, "DELETE", "/api/users/chi")[0] == 200
    assert call(other, "GET", "/api/catalog")[0] == 401
    actions = [e["action"] for e in call(client, "GET", "/api/users/audit")[1]["entries"]]
    assert {"create_user", "disable_user", "set_role", "set_password", "delete_user", "login"} <= set(actions)


def test_changing_own_password_needs_the_current_one_and_revokes_other_sessions(
    secured: tuple[TestClient, RunManager, Path],
) -> None:
    client, _, root = secured
    _seed(root)
    other = TestClient(client.app)
    assert _login(client, "an") == 200 and _login(other, "an") == 200
    assert call(client, "POST", "/api/auth/password", {"current": "sai-mat-khau-1", "new": "mat-khau-moi-44"})[0] == 403
    assert call(client, "POST", "/api/auth/password", {"current": GOOD, "new": "ngan"})[0] == 422
    assert call(client, "POST", "/api/auth/password", {"current": GOOD, "new": "mat-khau-moi-44"})[0] == 200
    assert call(client, "GET", "/api/catalog")[0] == 200  # phiên hiện tại được cấp mới
    assert call(other, "GET", "/api/catalog")[0] == 401  # phiên khác bị thu hồi
    client.cookies.clear()
    assert _login(client, "an") == 401 and _login(client, "an", "mat-khau-moi-44") == 200


def test_no_auth_mode_keeps_everything_open_as_a_local_admin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, SECRET)
    runners: list[ScriptedRunner] = []
    manager = make_manager(tmp_path, runners)
    with TestClient(build_app(ROOT, frontend=ROOT.parent / "frontend", manager=manager)) as client:
        status = call(client, "GET", "/api/auth/status")[1]
        assert status["auth"] is False and status["user"]["role"] == "admin"
        assert call(client, "GET", "/api/catalog")[0] == 200
        assert call(client, "GET", "/api/users")[0] == 404
        res = call(client, "POST", "/api/runs", {"mode": "demo", "adapters": [{"id": "tls13"}]})[1]
        assert res["runs"][0]["created_by"] == "local"
        wait_done(manager, res["runs"][0]["run_id"])
