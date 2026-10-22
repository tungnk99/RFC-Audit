"""Điểm cuối xác thực và quản lý người dùng (xem `auth`). Khi chạy `--no-auth`, trạng thái báo `auth: false` và mọi người là admin cục bộ."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from rfcv.api.auth import LOCAL_ADMIN, ROLES, AuthError, AuthStore, User

if TYPE_CHECKING:
    from rfcv.api.server import Api

COOKIE = "rfcv_session"


class LoginIn(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=200)


class SetupIn(LoginIn):
    code: str = Field(max_length=40)
    display: str = Field(default="", max_length=60)


class PasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class UserIn(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=200)
    role: str = "member"
    display: str = Field(default="", max_length=60)


class UserPatch(BaseModel):
    role: str | None = None
    disabled: bool | None = None
    password: str | None = Field(default=None, max_length=200)


async def _json(request: Request) -> None:
    from rfcv.api.server import _require_json  # type: ignore[reportPrivateUsage]

    await _require_json(request)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _fail(exc: AuthError) -> JSONResponse:
    return JSONResponse({"error": exc.message}, status_code=exc.status)


def _set_cookie(resp: JSONResponse, request: Request, token: str) -> None:
    resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/")


def register(app: FastAPI, api: Api, current: Callable[[Request], User], admin: Callable[[Request], User]) -> None:
    store: AuthStore | None = api.auth

    def need_store() -> AuthStore:
        if store is None:
            raise HTTPException(404, "máy chủ đang chạy không đăng nhập (--no-auth)")
        return store

    @app.get("/api/auth/status")
    def status(request: Request) -> dict[str, Any]:
        if store is None:
            return {"auth": False, "setup_needed": False, "user": LOCAL_ADMIN.public(), "roles": list(ROLES)}
        user = store.user_for_token(request.cookies.get(COOKIE))
        return {
            "auth": True,
            "setup_needed": store.count() == 0,
            "user": user.public() if user else None,
            "roles": list(ROLES),
        }

    @app.post("/api/auth/login", dependencies=[Depends(_json)])
    def login(body: LoginIn, request: Request) -> JSONResponse:
        try:
            user, token = need_store().login(body.username, body.password, _ip(request))
        except AuthError as exc:
            return _fail(exc)
        resp = JSONResponse({"user": user.public()})
        _set_cookie(resp, request, token)
        return resp

    @app.post("/api/auth/setup", dependencies=[Depends(_json)])
    def setup(body: SetupIn, request: Request) -> JSONResponse:
        try:
            user, token = need_store().setup_admin(body.code, body.username, body.password, body.display, _ip(request))
        except AuthError as exc:
            return _fail(exc)
        resp = JSONResponse({"user": user.public()}, status_code=201)
        _set_cookie(resp, request, token)
        return resp

    @app.post("/api/auth/logout", dependencies=[Depends(_json)])
    def logout(request: Request) -> JSONResponse:
        if store is not None:
            store.logout(request.cookies.get(COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.post("/api/auth/password", dependencies=[Depends(_json)])
    def change_password(body: PasswordIn, request: Request, user: User = Depends(current)) -> JSONResponse:
        try:
            token = need_store().change_own_password(user.username, body.current, body.new, _ip(request))
        except AuthError as exc:
            return _fail(exc)
        resp = JSONResponse({"ok": True})
        _set_cookie(resp, request, token)
        return resp

    # ---- quản trị người dùng (admin) --------------------------------------------------------------------------

    @app.get("/api/users")
    def users(_: User = Depends(admin)) -> dict[str, Any]:
        return {"users": [u.public() for u in need_store().users()], "roles": list(ROLES)}

    @app.get("/api/users/audit")
    def audit(_: User = Depends(admin)) -> dict[str, Any]:
        return {"entries": need_store().audit()}

    @app.post("/api/users", dependencies=[Depends(_json)])
    def add_user(body: UserIn, me: User = Depends(admin)) -> JSONResponse:
        try:
            u = need_store().create(body.username, body.password, body.role, body.display, actor=me.username)
        except AuthError as exc:
            return _fail(exc)
        return JSONResponse({"user": u.public()}, status_code=201)

    @app.patch("/api/users/{username}", dependencies=[Depends(_json)])
    def patch_user(username: str, body: UserPatch, me: User = Depends(admin)) -> JSONResponse:
        s = need_store()
        try:
            target = s.get(username)
            if target is None:
                raise AuthError(404, "không có tài khoản này")
            if target.username == me.username and (body.disabled or (body.role and body.role != me.role)):
                raise AuthError(409, "không tự khoá hay hạ quyền chính mình; nhờ admin khác làm")
            if body.role is not None and body.role != target.role:
                s.set_role(username, body.role, actor=me.username)
            if body.disabled is not None and body.disabled != target.disabled:
                s.set_disabled(username, body.disabled, actor=me.username)
            if body.password:
                s.set_password(username, body.password, actor=me.username)
        except AuthError as exc:
            return _fail(exc)
        fresh = s.get(username)
        return JSONResponse({"user": fresh.public() if fresh else None})

    @app.delete("/api/users/{username}")
    def remove_user(username: str, me: User = Depends(admin)) -> JSONResponse:
        if username.strip().lower() == me.username:
            return JSONResponse({"error": "không tự xoá chính mình"}, status_code=409)
        try:
            need_store().delete(username, actor=me.username)
        except AuthError as exc:
            return _fail(exc)
        return JSONResponse({"ok": True})
