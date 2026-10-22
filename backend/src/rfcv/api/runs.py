"""Chạy kiểm chứng nền cho giao diện web: kiểm tra yêu cầu, xếp hàng, chạy `build_runtime` + `run_all`, lưu trạng thái.

Đây chỉ là lớp mỏng trên `rfcv.assembly`: mọi quy tắc an toàn (cổng công cụ, IFC, Evidence store) vẫn do lõi giữ.
Mỗi lần chạy một adapter (một giao thức) và ghi `ui_run.json` cạnh `trace.db`, nên lịch sử còn sau khi khởi động lại.
Các lần chạy xếp hàng và chạy lần lượt: một LLM gateway dùng chung giới hạn tốc độ, và kết quả dễ so sánh hơn.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import queue
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, cast

from rfcv.api import catalog, runstore
from rfcv.assembly import Providers, Runtime, RuntimeConfig, build_runtime
from rfcv.core.budget import RequirementBudget
from rfcv.plugins import current_registry

ACTIVE = ("queued", "running")
_KEYLIKE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$", re.IGNORECASE)

Customize = Callable[["RunSpec", RuntimeConfig], Providers | None]


@dataclass(frozen=True)
class RunSpec:
    adapter: str
    requirements: tuple[str, ...] = ()  # rỗng = mọi yêu cầu của adapter
    mode: str = "demo"  # demo (SUT/mã giả, LLM thật) | real (mã và SUT thật)
    demo_case: str = "faulty"
    code_root: str | None = None
    code_index: str | None = None
    executor: str | None = None
    sut_launcher: str | None = None
    budget: dict[str, float] = field(default_factory=dict[str, float])

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> RunSpec:
        kw = {k: v for k, v in d.items() if k in {f.name for f in fields(cls)}}
        kw["requirements"] = tuple(kw.get("requirements") or ())
        return cls(**kw)


def scrub(text: str) -> str:
    """Xoá giá trị khoá API khỏi chuỗi lỗi trước khi lưu hoặc gửi về trình duyệt."""
    for name, value in os.environ.items():
        if _KEYLIKE.search(name) and len(value) >= 8:
            text = text.replace(value, "***")
    return text


def _now() -> float:
    return time.time()


class RunManager:
    def __init__(
        self,
        root: Path,
        *,
        runs_dir: Path | None = None,
        code_roots: list[Path] | None = None,
        customize: Customize | None = None,
        on_built: Callable[[Runtime], None] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.runs_dir = (runs_dir or self.root / "runs").resolve()
        self.code_roots = [p.resolve() for p in (code_roots or [])]
        self._customize = customize
        self._on_built = on_built
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._active: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task[Any]]] = {}
        self._cancelled: set[str] = set()
        # Lần chạy do tiến trình này giữ và chưa kết thúc; trạng thái "đang chạy/chờ" còn sót từ lần trước là "bị ngắt".
        self._owned: set[str] = set()
        self._worker = threading.Thread(target=self._work, name="rfcv-runs", daemon=True)
        self._worker.start()

    # ---- kiểm tra yêu cầu ---------------------------------------------------------------------------------------

    def code_root_allowed(self, path: Path) -> bool:
        p = path.resolve()
        return any(p == r or r in p.parents for r in self.code_roots)

    def parse_request(self, body: dict[str, Any]) -> tuple[list[RunSpec], list[str]]:
        """Một yêu cầu có thể chọn nhiều giao thức; mỗi giao thức thành một lần chạy. Trả (spec, lỗi): còn lỗi thì không chạy."""
        errors: list[str] = []
        adapters = {a["id"]: a for a in catalog.list_adapters(self.root, None) if "error" not in a}
        mode = str(body.get("mode", "demo"))
        if mode not in ("demo", "real"):
            errors.append(f"mode '{mode}' không hợp lệ (demo | real)")
        raw_chosen = body.get("adapters")
        chosen: list[Any] = cast("list[Any]", raw_chosen) if isinstance(raw_chosen, list) else []
        if not chosen:
            errors.append("chưa chọn giao thức RFC nào")
        budget = self._budget(body.get("budget"), errors)
        common: dict[str, Any] = {
            "mode": mode,
            "demo_case": str(body.get("demo_case") or "faulty"),
            "code_root": body.get("code_root") or None,
            "code_index": body.get("code_index") or None,
            "executor": body.get("executor") or None,
            "sut_launcher": body.get("sut_launcher") or None,
            "budget": budget,
        }
        specs: list[RunSpec] = []
        for item in chosen:
            entry: dict[str, Any] = cast("dict[str, Any]", item) if isinstance(item, dict) else {"id": item}
            aid = str(entry.get("id"))
            adapter = adapters.get(aid)
            if adapter is None:
                errors.append(f"adapter '{aid}' không có")
                continue
            known = {r["id"] for r in adapter["requirements"]}
            picked = tuple(str(r) for r in cast("list[Any]", entry.get("requirements") or []))
            if unknown := [r for r in picked if r not in known]:
                errors.append(f"{aid}: yêu cầu không có: {', '.join(unknown)}")
            if not known:
                errors.append(f"{aid}: adapter chưa có yêu cầu đã duyệt (examples/*.rbs)")
            if mode == "demo" and not adapter["demo_supported"]:
                errors.append(f"{aid}: chế độ demo chỉ mô phỏng giao thức TLS 1.3; hãy dùng chế độ real")
            specs.append(RunSpec(adapter=aid, requirements=picked, **common))
        errors += self._check_common(specs[0] if specs else None, mode)
        return (specs, errors) if not errors else ([], errors)

    @staticmethod
    def _budget(raw: Any, errors: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        limits = {"rounds": (1, 30), "tool_calls": (1, 2000), "tokens": (1000, 20_000_000), "seconds": (10, 86_400)}
        given: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        for key, value in given.items():
            if key not in limits:
                errors.append(f"ngân sách: không có '{key}'")
                continue
            lo, hi = limits[key]
            if not isinstance(value, int | float) or isinstance(value, bool) or not lo <= value <= hi:
                errors.append(f"ngân sách {key} phải trong [{lo}, {hi}]")
            else:
                out[key] = value
        return out

    def _check_common(self, spec: RunSpec | None, mode: str) -> list[str]:
        errors: list[str] = []
        reg = current_registry()
        models = catalog.models_status(self.root / "config" / "models.yaml")
        if "error" in models:
            errors.append(models["error"])
        else:
            used = {models["agents"][a] for a in models["agents"]}
            missing = sorted({models["models"][m]["api_key_env"] for m in used if not models["models"][m]["key_set"]})
            if missing:
                errors.append(f"chưa đặt khoá API trong môi trường của máy chủ: {', '.join(missing)}")
        if spec is None or mode != "real":
            return errors
        if not spec.code_root:
            errors.append("chế độ real cần chọn thư mục mã nguồn (code_root)")
        elif not Path(spec.code_root).is_dir():
            errors.append(f"code_root không phải thư mục: {spec.code_root}")
        elif not self.code_root_allowed(Path(spec.code_root)):
            errors.append("code_root nằm ngoài các thư mục máy chủ cho phép (--code-root)")
        caps = catalog.capabilities(reg)
        for label, name, table, key in (
            ("chỉ mục mã", spec.code_index, reg.code_indexes, "code_indexes"),
            ("bộ chạy lệnh", spec.executor, reg.executors, "executors"),
            ("bộ chạy SUT", spec.sut_launcher, reg.sut_launchers, "sut_launchers"),
        ):
            if not name:
                errors.append(f"chưa chọn {label}")
            elif name not in table:
                errors.append(
                    f"{label} '{name}' chưa được đăng ký"
                    + (" (chưa có bộ chạy SUT nào cài đặt)" if key == "sut_launchers" else "")
                )
            elif not next((c["available"] for c in caps[key] if c["name"] == name), False):
                note = next(c["note"] for c in caps[key] if c["name"] == name)
                errors.append(f"{label} '{name}' chưa dùng được trên máy này: {note}")
        return errors

    # ---- xếp hàng và chạy -------------------------------------------------------------------------------------

    def submit(self, specs: list[RunSpec], created_by: str | None = None) -> list[dict[str, Any]]:
        batch = f"batch-{uuid.uuid4().hex[:8]}"
        records: list[dict[str, Any]] = []
        for spec in specs:
            run_id = f"run-{uuid.uuid4().hex[:12]}"
            rec: dict[str, Any] = {
                "run_id": run_id,
                "batch_id": batch,
                "created_by": created_by,
                "spec": asdict(spec),
                "status": "queued",
                "created_at": _now(),
                "started_at": None,
                "ended_at": None,
                "error": None,
                "verdicts": [],
                "leak_scan": None,
            }
            self._save(run_id, rec)
            self._owned.add(run_id)
            self._queue.put(run_id)
            records.append(rec)
        return records

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            active = self._active.get(run_id)
            rec = self.record(run_id)
            if rec is None or rec["status"] not in ACTIVE:
                return False
            self._cancelled.add(run_id)
        if active is not None:
            loop, task = active
            loop.call_soon_threadsafe(task.cancel)
        else:
            self._update(run_id, status="cancelled", ended_at=_now())
        return True

    def _work(self) -> None:
        while True:
            run_id = self._queue.get()
            rec = self.record(run_id)
            if rec is None or run_id in self._cancelled or rec["status"] != "queued":
                continue
            try:
                asyncio.run(self._execute(run_id, RunSpec.from_json(rec["spec"])))
            except Exception as exc:  # lỗi ngoài dự kiến không được giết luồng làm việc
                self._update(run_id, status="failed", ended_at=_now(), error=scrub(f"{type(exc).__name__}: {exc}"))

    async def _execute(self, run_id: str, spec: RunSpec) -> None:
        self._update(run_id, status="running", started_at=_now())
        rt: Runtime | None = None
        try:
            self._active[run_id] = (asyncio.get_running_loop(), asyncio.current_task())  # type: ignore[assignment]
            if run_id in self._cancelled:
                raise asyncio.CancelledError
            adapter_dir = self.root / "adapters" / spec.adapter
            req_dir = self._stage_requirements(run_id, spec, adapter_dir)
            cfg = self._config(run_id, spec, adapter_dir)
            rt = build_runtime(cfg, self._providers(spec, cfg))  # đồng bộ: kết nối SQLite gắn với luồng này
            if self._on_built is not None:
                self._on_built(rt)
            verdicts = await rt.run_all(req_dir)
            rt.close()
            scan = rt.scan_leaks()
            rt = None
            self._update(
                run_id,
                status="finished",
                ended_at=_now(),
                verdicts=[v.to_json() for v in verdicts],
                leak_scan={"clean": scan.clean, "count": len(scan.leaks)},
            )
        except asyncio.CancelledError:
            self._update(run_id, status="cancelled", ended_at=_now())
        except (
            Exception
        ) as exc:  # MissingProviderError, WorkspaceError, PolicyError, lỗi mô hình… đều hiện ra cho người dùng
            self._update(run_id, status="failed", ended_at=_now(), error=scrub(f"{type(exc).__name__}: {exc}"))
        finally:
            self._active.pop(run_id, None)
            if rt is not None:
                rt.close()

    def _stage_requirements(self, run_id: str, spec: RunSpec, adapter_dir: Path) -> Path:
        """Chép đúng các yêu cầu đã chọn vào thư mục lần chạy: vừa lọc, vừa lưu lại đã chạy bản đặc tả nào."""
        files = catalog.requirement_files(adapter_dir)
        picked = spec.requirements or tuple(files)
        dest = self.runs_dir / run_id / "requirements"
        dest.mkdir(parents=True, exist_ok=True)
        for rid in picked:
            shutil.copy2(files[rid], dest / files[rid].name)
        return dest

    def _config(self, run_id: str, spec: RunSpec, adapter_dir: Path) -> RuntimeConfig:
        rfc_dir = self.root / "inputs" / "rfc"
        models = self.root / "config" / "models.yaml"
        return RuntimeConfig(
            adapter_dir=adapter_dir,
            run_dir=self.runs_dir,
            skills_root=self.root / "skills",
            models_path=models if models.is_file() else None,
            rfc_dir=rfc_dir if rfc_dir.is_dir() else None,
            run_id=run_id,
            code_root=Path(spec.code_root) if spec.mode == "real" and spec.code_root else None,
            code_index=spec.code_index if spec.mode == "real" else None,
            executor=spec.executor if spec.mode == "real" else None,
            sut_launcher=spec.sut_launcher if spec.mode == "real" else None,
            budget=RequirementBudget(**spec.budget) if spec.budget else None,  # type: ignore[arg-type]
        )

    def _providers(self, spec: RunSpec, cfg: RuntimeConfig) -> Providers | None:
        if self._customize is not None and (custom := self._customize(spec, cfg)) is not None:
            return custom
        if spec.mode == "demo":
            # Nhập muộn và theo tên: bộ mô phỏng thuộc eval/, chỉ nạp khi người dùng chủ động chọn chế độ demo.
            demo = importlib.import_module("rfcv.eval.demo_providers")
            return demo.demo_providers(spec.demo_case)
        return None

    # ---- trạng thái -------------------------------------------------------------------------------------------

    def _path(self, run_id: str) -> Path:
        return self.runs_dir / run_id / "ui_run.json"

    def _save(self, run_id: str, rec: dict[str, Any]) -> None:
        path = self._path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    def _update(self, run_id: str, **changes: Any) -> None:
        with self._lock:
            f = self._path(run_id)
            rec: dict[str, Any] = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {"run_id": run_id}
            rec.update(changes)
            self._save(run_id, rec)  # ghi trạng thái thật, không phải trạng thái "bị ngắt" suy ra khi đọc
            if rec.get("status") not in ACTIVE:
                self._owned.discard(run_id)

    def run_dir(self, run_id: str) -> Path | None:
        if not runstore.RUN_ID.match(run_id):
            return None
        d = self.runs_dir / run_id
        return d if d.is_dir() else None

    def record(self, run_id: str) -> dict[str, Any] | None:
        """Bản ghi một lần chạy. Lần chạy bằng CLI (không có ui_run.json) được dựng từ trace."""
        d = self.run_dir(run_id)
        if d is None:
            return None
        f = d / "ui_run.json"
        if f.is_file():
            rec: dict[str, Any] = json.loads(f.read_text(encoding="utf-8"))
            if rec["status"] in ACTIVE and run_id not in self._owned:
                rec["status"] = "interrupted"  # máy chủ đã khởi động lại giữa chừng
            return rec
        if not runstore.has_trace(d):
            return None
        done = [e for e in runstore.events_after(d, 0, 100000) if e["kind"] == "verdict"]
        manifest = runstore.manifest(d) or {}
        return {
            "run_id": run_id,
            "batch_id": None,
            "spec": {"adapter": (manifest.get("adapter") or {}).get("name"), "mode": "cli", "requirements": []},
            "status": "finished" if done else "unknown",
            "created_at": first[0]["ts_ns"] / 1e9 if (first := runstore.events_after(d, 0, 1)) else 0.0,
            "started_at": None,
            "ended_at": (d / "trace.db").stat().st_mtime,
            "error": None,
            "verdicts": [e["payload"] for e in done],
            "leak_scan": None,
        }

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.runs_dir.is_dir():
            return []
        dirs = [d for d in self.runs_dir.iterdir() if d.is_dir() and runstore.RUN_ID.match(d.name)]
        dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        out: list[dict[str, Any]] = []
        for d in dirs:
            rec = self.record(d.name)
            if rec is not None:
                out.append(rec)
            if len(out) >= limit:
                break
        out.sort(key=lambda r: r["created_at"], reverse=True)
        return out

    def is_live(self, run_id: str) -> bool:
        rec = self.record(run_id)
        return rec is not None and rec["status"] in ACTIVE
