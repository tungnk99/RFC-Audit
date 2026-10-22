"""Máy chủ HTTP cho giao diện web (FastAPI + uvicorn).

- JSON dưới `/api/…` (OpenAPI tại `/docs`), luồng sự kiện trực tiếp bằng Server-Sent Events, giao diện tĩnh từ `frontend/`.
- Chỉ nghe trên máy cục bộ theo mặc định. Chặn Host lạ (DNS rebinding) và POST không phải JSON (trang web khác không
  gọi chéo được vì không có CORS). Khoá API không bao giờ đi qua đây: chỉ trả tên biến và đã đặt hay chưa.
- Giao diện đọc dữ liệu từ `runs/<run_id>` bằng chính các tệp lõi đã ghi (trace.db, evidence.db), không có nguồn thứ hai.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import time
import urllib.parse
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from rfcv.api import admin, catalog, codebrowse, routes_auth, routes_edit, routes_review, runstore, transcript
from rfcv.api.auth import LOCAL_ADMIN, AuthStore, User
from rfcv.api.findings import analyze
from rfcv.api.runs import ACTIVE, RunManager
from rfcv.core.policy import find_agents_root

POLL_S = 0.4
HEARTBEAT_S = 15.0
LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "::1", "[::1]", "testserver"]


def load_model_keys(env_file: Path, models_path: Path) -> list[str]:
    """Nạp từ tệp .env CHỈ các biến chứa khoá mô hình khai báo trong models.yaml, và chỉ khi môi trường chưa đặt.
    Cố ý khác `source .env`: biến khác trong tệp (ví dụ SUPABASE_*, sẽ bật bản sao trace ra ngoài) không bị nạp."""
    wanted = {str(m["api_key_env"]) for m in catalog.models_status(models_path)["models"].values()}
    loaded: list[str] = []
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = (s.strip() for s in line.split("=", 1))
        value = value.strip('"').strip("'")
        if name in wanted and value and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded


class Api:
    """Logic các điểm cuối, tách khỏi giao thức HTTP để kiểm thử trực tiếp."""

    def __init__(
        self,
        manager: RunManager,
        agents_root: Path | None = None,
        *,
        read_only: bool = False,
        auth: AuthStore | None = None,
    ) -> None:
        self.m = manager
        self.read_only = read_only
        self.auth = auth  # None = không đăng nhập (kiểm thử, nhúng, --no-auth): mọi người là admin cục bộ
        self.agents_root = agents_root or find_agents_root()

    def catalog(self) -> dict[str, Any]:
        return catalog.build_catalog(self.m.root, agents_root=self.agents_root, code_roots=self.m.code_roots)

    def fs(self, raw: str | None) -> tuple[int, Any]:
        if not raw:
            return 200, {"path": None, "parent": None, "dirs": [str(p) for p in self.m.code_roots], "is_repo": False}
        p = Path(raw)
        if not p.is_dir() or not self.m.code_root_allowed(p):
            return 403, {"error": "thư mục không tồn tại hoặc nằm ngoài các thư mục máy chủ cho phép"}
        p = p.resolve()
        try:
            dirs = sorted((d.name for d in p.iterdir() if d.is_dir()), key=str.lower)[:500]
        except OSError as exc:
            return 403, {"error": str(exc)}
        parent = p.parent if self.m.code_root_allowed(p.parent) and p not in self.m.code_roots else None
        return 200, {
            "path": str(p),
            "parent": str(parent) if parent else None,
            "dirs": dirs,
            "is_repo": (p / ".git").exists(),
        }

    def create_runs(self, body: dict[str, Any], user: User = LOCAL_ADMIN) -> tuple[int, Any]:
        specs, errors = self.m.parse_request(body)
        if errors:
            return 422, {"errors": errors}
        records = self.m.submit(specs, created_by=user.username)
        return 201, {"batch_id": records[0]["batch_id"], "runs": records}

    def run_detail(self, run_id: str) -> tuple[int, Any]:
        rec = self.m.record(run_id)
        d = self.m.run_dir(run_id)
        if rec is None or d is None:
            return 404, {"error": "không có lần chạy này"}
        return 200, {**rec, "manifest": runstore.manifest(d), "summary": runstore.summary(d)}

    def events(self, run_id: str, query: dict[str, str]) -> tuple[int, Any]:
        d = self.m.run_dir(run_id)
        rec = self.m.record(run_id)
        if d is None or rec is None:
            return 404, {"error": "không có lần chạy này"}
        after = _int(query.get("after"), 0)
        batch = runstore.events_after(d, after, min(_int(query.get("limit"), 500), 2000))
        return 200, {
            "events": [transcript.slim_event(e) for e in batch],
            "last_seq": batch[-1]["seq"] if batch else after,
            "status": rec["status"],
        }

    def event(self, run_id: str, seq: str) -> tuple[int, Any]:
        d = self.m.run_dir(run_id)
        e = runstore.get_event(d, _int(seq, -1)) if d else None
        return (200, transcript.full_event(e)) if e else (404, {"error": "không có sự kiện này"})

    def evidence(self, run_id: str, item: str | None, query: dict[str, str]) -> tuple[int, Any]:
        d = self.m.run_dir(run_id)
        if d is None:
            return 404, {"error": "không có lần chạy này"}
        if item:
            found = runstore.evidence_item(d, urllib.parse.unquote(item))
            return (200, found) if found else (404, {"error": "không có bằng chứng này"})
        return 200, {"evidence": runstore.evidence(d, query.get("requirement"))}

    def verify(self, run_id: str) -> tuple[int, Any]:
        d = self.m.run_dir(run_id)
        if d is None or not (d / "evidence.db").is_file():
            return 404, {"error": "không có kho bằng chứng"}
        if self.m.is_live(run_id):
            return 409, {"error": "lần chạy đang diễn ra; kiểm tra chuỗi hash sau khi kết thúc"}
        from rfcv.evidence.store import EvidenceStore

        store = EvidenceStore(d / "evidence.db")
        try:
            return 200, store.verify_chain().__dict__
        finally:
            store.close()


def _int(raw: str | None, default: int) -> int:
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


class AdapterPick(BaseModel):
    id: str
    requirements: list[str] = Field(default_factory=list, description="Rỗng = mọi yêu cầu của adapter")


class RunRequest(BaseModel):
    """Một yêu cầu chạy; mỗi giao thức được chọn thành một lần chạy."""

    adapters: list[AdapterPick | str] = []
    mode: str = "demo"
    demo_case: str | None = None
    code_root: str | None = None
    code_index: str | None = None
    executor: str | None = None
    sut_launcher: str | None = None
    budget: dict[str, Any] = Field(default_factory=dict)


async def _require_json(request: Request) -> None:
    """POST phải là JSON: trang web khác không gửi được kiểu này mà không qua CORS preflight (ta không bật CORS)."""
    if "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(415, "cần Content-Type: application/json")


def _reply(result: tuple[int, Any]) -> JSONResponse:
    status, body = result
    return JSONResponse(body, status_code=status)


def create_app(api: Api, frontend: Path | None = None, allowed_hosts: list[str] | None = None) -> FastAPI:
    public = {"/api/auth/status", "/api/auth/login", "/api/auth/setup", "/api/auth/logout", "/api/health"}

    def guard(request: Request) -> None:
        """Mọi `/api/…` (trừ đăng nhập/trạng thái) cần phiên hợp lệ; yêu cầu ghi chỉ nhận từ chính trang này (Origin khớp Host)."""
        path = request.url.path
        if not path.startswith("/api/"):
            return
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urllib.parse.urlsplit(origin).netloc != request.headers.get("host"):
                raise HTTPException(403, "yêu cầu từ nguồn khác bị từ chối")
        if api.auth is None:
            request.state.user = LOCAL_ADMIN
            return
        user = api.auth.user_for_token(request.cookies.get(routes_auth.COOKIE))
        request.state.user = user
        if user is None and path not in public:
            raise HTTPException(401, "cần đăng nhập")

    def current(request: Request) -> User:
        user: User | None = getattr(request.state, "user", None)
        if user is None:
            raise HTTPException(401, "cần đăng nhập")
        return user

    def admin_only(request: Request) -> User:
        user = current(request)
        if user.role != "admin":
            raise HTTPException(403, "việc này chỉ admin được làm")
        return user

    app = FastAPI(
        title="rfcv UI API",
        version="1",
        docs_url="/docs",
        openapi_url="/api/openapi.json",
        dependencies=[Depends(guard)],
    )
    if allowed_hosts is not None:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:  # định dạng lỗi cho giao diện: {"error": …}
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            (f"{'.'.join(str(p) for p in e['loc'][1:])}: " if len(e["loc"]) > 1 else "")
            + str(e["msg"]).removeprefix("Value error, ")
            for e in exc.errors()
        ]
        return JSONResponse({"errors": errors}, status_code=422)

    def writable() -> None:
        """Chế độ chỉ đọc (`rfcv serve --read-only`): mọi thao tác ghi (chạy, huỷ, duyệt, sửa) bị từ chối."""
        if api.read_only:
            raise HTTPException(403, "máy chủ đang ở chế độ chỉ đọc")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "read_only": api.read_only}

    @app.get("/api/catalog")
    def get_catalog() -> dict[str, Any]:
        return api.catalog()

    @app.get("/api/fs")
    def browse(path: str | None = None) -> JSONResponse:
        return _reply(api.fs(path))

    @app.get("/api/runs")
    def list_runs(digest: bool = False) -> dict[str, Any]:
        runs = api.m.list_runs()
        if digest:  # kèm số liệu tóm tắt từng lần chạy (token, bằng chứng, thời lượng); có nhớ đệm nên rẻ sau lần đầu
            for r in runs:
                d = api.m.run_dir(r["run_id"])
                dig = admin.run_digest(d) if d else {}
                r["digest"] = {
                    k: dig.get(k) for k in ("tokens", "evidence", "requirements", "seconds", "tool_calls", "rounds")
                }
        return {"runs": runs}

    @app.get("/api/stats")
    def get_stats(days: int | None = 30) -> dict[str, Any]:
        return admin.stats(api.m, days if days and days > 0 else None)

    @app.get("/api/agents/{name}")
    def get_agent(name: str) -> JSONResponse:
        found = admin.agent_detail(name, api.agents_root, api.m)
        return _reply((200, found) if found else (404, {"error": "không có agent này"}))

    @app.get("/api/skills")
    def get_skills() -> dict[str, Any]:
        return {"skills": admin.skills_list(api.m.root / "skills", api.agents_root)}

    @app.get("/api/skills/{scope}/{name}")
    def get_skill(scope: str, name: str, file: str | None = None) -> JSONResponse:
        found = admin.skill_detail(api.m.root / "skills", scope, name, file)
        return _reply((200, found) if found else (404, {"error": "không có skill này"}))

    @app.get("/api/system")
    def get_system() -> dict[str, Any]:
        return admin.system_info(api.m)

    @app.get("/api/adapters/{adapter_id}")
    def get_adapter(adapter_id: str) -> JSONResponse:
        found = admin.adapter_detail(api.m.root, adapter_id)
        return _reply((200, found) if found else (404, {"error": "không có adapter này"}))

    @app.post("/api/runs/validate", dependencies=[Depends(_require_json)])
    def validate_runs(req: RunRequest) -> dict[str, Any]:
        """Kiểm tra trước khi chạy: trả mọi lỗi cấu hình mà không xếp hàng gì."""
        specs, errors = api.m.parse_request(req.model_dump())
        return {"ok": not errors, "errors": errors, "runs": len(specs)}

    @app.post("/api/runs/{run_id}/rerun", dependencies=[Depends(_require_json), Depends(writable)])
    def rerun(run_id: str, user: User = Depends(current)) -> JSONResponse:
        rec = api.m.record(run_id)
        if rec is None or rec["spec"].get("mode") not in ("demo", "real"):
            return _reply((404, {"error": "lần chạy này không có cấu hình để chạy lại (chạy bằng CLI)"}))
        body = {
            **rec["spec"],
            "adapters": [{"id": rec["spec"]["adapter"], "requirements": rec["spec"].get("requirements", [])}],
        }
        return _reply(api.create_runs(body, user))

    @app.get("/api/runs/{run_id}/export")
    def export(run_id: str, full: bool = False) -> Response:
        status, detail = api.run_detail(run_id)
        d = api.m.run_dir(run_id)
        if status != 200 or d is None:
            return _reply((404, {"error": "không có lần chạy này"}))
        events = runstore.events_after(d, 0, 1_000_000)
        bundle = {
            "run": detail,
            "events": events if full else [transcript.slim_event(e) for e in events],
            "evidence": [runstore.evidence_item(d, x["evidence_id"]) for x in runstore.evidence(d)],
        }
        name = f"{run_id}{'-full' if full else ''}.json"
        return Response(
            json.dumps(bundle, ensure_ascii=False, default=str),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.post("/api/runs", dependencies=[Depends(_require_json), Depends(writable)])
    def create_runs(req: RunRequest, user: User = Depends(current)) -> JSONResponse:
        return _reply(api.create_runs(req.model_dump(), user))

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> JSONResponse:
        return _reply(api.run_detail(run_id))

    @app.get("/api/runs/{run_id}/findings")
    def findings(run_id: str) -> JSONResponse:
        d = api.m.run_dir(run_id)
        if d is None:
            return _reply((404, {"error": "không có lần chạy này"}))
        return _reply((200, {"findings": analyze(d, api.m.root / "adapters")}))

    @app.get("/api/runs/{run_id}/code")
    def code_files(run_id: str) -> JSONResponse:
        d = api.m.run_dir(run_id)
        return _reply(
            (200, codebrowse.tree(d, api.m.root / "adapters")) if d else (404, {"error": "không có lần chạy này"})
        )

    @app.get("/api/runs/{run_id}/code/file")
    def code_one(
        run_id: str, path: str, start: int | None = None, end: int | None = None, around: int | None = None
    ) -> JSONResponse:
        d = api.m.run_dir(run_id)
        found = codebrowse.file(d, path, api.m.root / "adapters", start, end, around) if d else None
        return _reply((200, found) if found else (404, {"error": "tệp này không thuộc phạm vi mã của lần chạy"}))

    @app.get("/api/runs/{run_id}/code/search")
    def code_search(run_id: str, q: str) -> JSONResponse:
        d = api.m.run_dir(run_id)
        return _reply(
            (200, codebrowse.search(d, q, api.m.root / "adapters")) if d else (404, {"error": "không có lần chạy này"})
        )

    @app.get("/api/runs/{run_id}/code/symbol")
    def code_symbol(run_id: str, name: str) -> JSONResponse:
        d = api.m.run_dir(run_id)
        return _reply(
            (200, codebrowse.symbol(d, name, api.m.root / "adapters"))
            if d
            else (404, {"error": "không có lần chạy này"})
        )

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, after: int = 0, limit: int = 500) -> JSONResponse:
        return _reply(api.events(run_id, {"after": str(after), "limit": str(limit)}))

    @app.get("/api/runs/{run_id}/events/{seq}")
    def event(run_id: str, seq: int) -> JSONResponse:
        return _reply(api.event(run_id, str(seq)))

    @app.get("/api/runs/{run_id}/evidence")
    def evidence_list(run_id: str, requirement: str | None = None) -> JSONResponse:
        return _reply(api.evidence(run_id, None, {"requirement": requirement or ""}))

    @app.get("/api/runs/{run_id}/evidence/{evidence_id:path}")
    def evidence_item(run_id: str, evidence_id: str) -> JSONResponse:
        return _reply(api.evidence(run_id, evidence_id, {}))

    @app.get("/api/runs/{run_id}/verify")
    def verify(run_id: str) -> JSONResponse:
        return _reply(api.verify(run_id))

    @app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(_require_json), Depends(writable)])
    def cancel(run_id: str, user: User = Depends(current)) -> JSONResponse:
        rec = api.m.record(run_id)
        if rec and user.role != "admin" and rec.get("created_by") != user.username:
            raise HTTPException(403, "member chỉ huỷ được lần chạy do mình tạo")
        ok = api.m.cancel(run_id)
        return JSONResponse({"cancelled": ok}, status_code=200 if ok else 409)

    @app.get("/api/runs/{run_id}/stream")
    async def stream(request: Request, run_id: str, after: int | None = None) -> StreamingResponse:
        d = api.m.run_dir(run_id)
        if d is None:
            raise HTTPException(404, "không có lần chạy này")
        start = after if after is not None else _int(request.headers.get("last-event-id"), 0)

        def sse(event: str, data: Any, eid: int | None = None) -> str:
            head = f"id: {eid}\n" if eid is not None else ""
            return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

        async def gen() -> AsyncIterator[str]:
            last, status, quiet_since = start, None, time.monotonic()
            while True:
                rec = await asyncio.to_thread(api.m.record, run_id)
                now_status = rec["status"] if rec else "unknown"
                batch = await asyncio.to_thread(runstore.events_after, d, last, 200)
                for e in batch:
                    last = e["seq"]
                    yield sse("trace", transcript.slim_event(e), e["seq"])
                if now_status != status:
                    status = now_status
                    yield sse("status", {"status": status, "error": rec.get("error") if rec else None})
                if batch:
                    quiet_since = time.monotonic()
                    continue  # còn dữ liệu: đọc tiếp ngay
                if now_status not in ACTIVE:
                    yield sse("end", {"status": now_status, "last_seq": last})
                    return
                if time.monotonic() - quiet_since > HEARTBEAT_S:
                    yield ": ping\n\n"
                    quiet_since = time.monotonic()
                await asyncio.sleep(POLL_S)

        headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

    routes_auth.register(app, api, current, admin_only)
    routes_review.register(app, api, writable, current)
    routes_edit.register(app, api, writable, current, admin_only)

    @app.get("/api/{rest:path}")
    def unknown_api(rest: str) -> JSONResponse:
        return JSONResponse({"error": "không có điểm cuối này"}, status_code=404)

    @app.get("/{path:path}", include_in_schema=False)
    def static(path: str) -> Response:
        if frontend is None or not frontend.is_dir():
            return Response("Chưa có thư mục frontend/. Dùng --frontend để chỉ đường.", status_code=404)
        root = frontend.resolve()
        target = (root / (urllib.parse.unquote(path) or "index.html")).resolve()
        if root not in target.parents or not target.is_file():
            target = root / "index.html"  # ứng dụng một trang: đường dẫn lạ về trang chính
        # Bảng tra cố định: trên Windows registry có thể gán .js là text/plain, khiến trình duyệt từ chối module.
        fixed = {
            ".js": "text/javascript",
            ".css": "text/css",
            ".svg": "image/svg+xml",
            ".html": "text/html",
            ".json": "application/json",
        }
        ctype = fixed.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/json":
            ctype += "; charset=utf-8"
        return Response(target.read_bytes(), media_type=ctype, headers={"Cache-Control": "no-store"})

    return app


def build_app(
    root: Path,
    *,
    read_only: bool = False,
    agents_root: Path | None = None,
    frontend: Path | None = None,
    code_roots: list[Path] | None = None,
    runs_dir: Path | None = None,
    manager: RunManager | None = None,
    loopback_only: bool = True,
    auth: bool = False,
) -> FastAPI:
    """Dựng ứng dụng. `code_roots` là các thư mục người dùng được phép chọn làm mã nguồn; `manager` để nhúng hoặc
    kiểm thử với bộ quản lý đã cấu hình sẵn."""
    root = root.resolve()
    manager = manager or RunManager(root, runs_dir=runs_dir, code_roots=code_roots or [root.parent])
    store = AuthStore(root / ".rfcv-ui" / "auth.db") if auth else None
    app = create_app(
        Api(manager, agents_root, read_only=read_only, auth=store), frontend, LOOPBACK_HOSTS if loopback_only else None
    )
    app.state.auth = store
    return app


def serve(
    root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    frontend: Path | None = None,
    code_roots: list[Path] | None = None,
    read_only: bool = False,
    auth: bool = True,
) -> None:
    import uvicorn

    app = build_app(
        root,
        frontend=frontend,
        code_roots=code_roots,
        loopback_only=host in LOOPBACK_HOSTS,
        read_only=read_only,
        auth=auth,
    )
    store: AuthStore | None = app.state.auth
    if store is not None and (code := store.ensure_setup_code()):
        print(f"Chưa có tài khoản nào. Mã thiết lập lần đầu: {code}  (cũng nằm ở {store.setup_file})")
    uvicorn.run(app, host=host, port=port, log_level="warning")
