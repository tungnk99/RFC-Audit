"""Điểm cuối soạn thảo có kiểm soát (xem `editing`): liệt kê, đọc, kiểm tra nháp, lưu, lịch sử, khôi phục, nhật ký kiểm toán."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from rfcv.api import editing
from rfcv.api.auth import User
from rfcv.api.editing import Ctx, EditError

if TYPE_CHECKING:
    from rfcv.api.server import Api


class DraftIn(BaseModel):
    kind: str = Field(max_length=20)
    name: str = Field(max_length=200)
    text: str = Field(max_length=editing.MAX_BYTES * 2)


class SaveIn(DraftIn):
    base_sha: str | None = None
    note: str = Field(default="", max_length=500)
    actor: str = Field(default="", max_length=60)


class RestoreIn(BaseModel):
    kind: str = Field(max_length=20)
    name: str = Field(max_length=200)
    version: str = Field(max_length=80)
    note: str = Field(default="", max_length=500)
    actor: str = Field(default="", max_length=60)


async def _json(request: Request) -> None:
    from rfcv.api.server import _require_json  # type: ignore[reportPrivateUsage]

    await _require_json(request)


def _err(exc: EditError) -> JSONResponse:
    return JSONResponse({"error": exc.message, **exc.extra}, status_code=exc.status)


def register(
    app: FastAPI,
    api: Api,
    writable: Callable[[], None],
    current: Callable[[Request], User],
    admin: Callable[[Request], User],
) -> None:
    ctx = Ctx(api.m.root, api.agents_root, api.m)

    @app.get("/api/edit/list")
    def list_resources() -> dict[str, Any]:
        return {"kinds": editing.KINDS, "resources": editing.listing(ctx), "read_only": api.read_only}

    @app.get("/api/edit/read")
    def read(kind: str, name: str) -> JSONResponse:
        try:
            return JSONResponse(editing.read(ctx, kind, name))
        except EditError as exc:
            return _err(exc)

    @app.get("/api/edit/history")
    def hist(kind: str, name: str) -> JSONResponse:
        return JSONResponse({"history": editing.history(ctx, kind, name)})

    @app.get("/api/edit/version")
    def version(kind: str, name: str, id: str) -> JSONResponse:
        try:
            return JSONResponse({"text": editing.version_text(ctx, kind, name, id)})
        except EditError as exc:
            return _err(exc)

    @app.get("/api/edit/audit")
    def audit_log() -> dict[str, Any]:
        return {"entries": editing.audit(ctx)}

    @app.post("/api/edit/validate", dependencies=[Depends(_json)])
    def check(body: DraftIn) -> dict[str, Any]:
        return editing.validate(ctx, body.kind, body.name, body.text)

    def who(body_actor: str, user: User) -> str:
        return user.username if api.auth is not None else body_actor  # đã đăng nhập: không tin tên máy khách gửi

    @app.post("/api/edit/save", dependencies=[Depends(_json), Depends(writable)])
    def save(body: SaveIn, user: User = Depends(admin)) -> JSONResponse:
        try:
            return JSONResponse(
                editing.save(
                    ctx,
                    body.kind,
                    body.name,
                    body.text,
                    base_sha=body.base_sha,
                    note=body.note,
                    actor=who(body.actor, user),
                ),
                status_code=201,
            )
        except EditError as exc:
            return _err(exc)

    @app.post("/api/edit/restore", dependencies=[Depends(_json), Depends(writable)])
    def restore(body: RestoreIn, user: User = Depends(admin)) -> JSONResponse:
        try:
            return JSONResponse(
                editing.restore(ctx, body.kind, body.name, body.version, actor=who(body.actor, user), note=body.note)
            )
        except EditError as exc:
            return _err(exc)
