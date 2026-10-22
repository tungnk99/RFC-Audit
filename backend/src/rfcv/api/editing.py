"""Soạn thảo có kiểm soát các thứ quyết định hành vi của hệ thống: yêu cầu RBS, lời nhắc và hồ sơ agent, skill, cấu hình mô hình.

Nguyên tắc: không ghi gì mà chưa qua đúng cổng kiểm tra mà lõi vẫn dùng (RBS qua parser và Oracle compiler, hồ sơ agent qua PolicyStore
tức là ràng buộc vùng tin cậy và công cụ, skill qua SkillRegistry, mô hình qua ModelsConfig). Chỉ sửa được một danh sách tài nguyên
cố định (không đường dẫn tuỳ ý). Mỗi lần lưu: kiểm tra, chống ghi đè khi tệp đã bị người khác đổi (so hash), bắt buộc ghi lý do, giữ
bản cũ để khôi phục, và ghi nhật ký kiểm toán. Lần chạy sau tự nhận bản mới qua digest trong bản kê; lần đang chạy giữ bản đã nạp.

Danh tính người sửa do người dùng tự khai (giao diện chưa có đăng nhập).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from rfcv.api.runs import ACTIVE, RunManager
from rfcv.plugins import current_registry

KINDS = {
    "rbs": "Yêu cầu RBS",
    "prompt": "Lời nhắc agent",
    "role": "Hồ sơ agent (role.yaml)",
    "skill": "Skill (SKILL.md)",
    "models": "Cấu hình mô hình",
}
MAX_BYTES = 200_000
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,60}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")
_KEYLIKE = re.compile(r"(?i)(\bsk-[A-Za-z0-9_-]{16,}|\bapi[_-]?key\s*:\s*[^\s#]+)")
PLAYBOOK = re.compile(r"<!-- playbook:begin -->(.*?)<!-- playbook:end -->", re.DOTALL)


class EditError(Exception):
    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


@dataclass(frozen=True)
class Ctx:
    root: Path
    agents_root: Path
    manager: RunManager

    @property
    def state(self) -> Path:
        return self.root / ".rfcv-ui"


def sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "__", name)


# ---- tài nguyên -------------------------------------------------------------------------------------------------


def resolve(ctx: Ctx, kind: str, name: str, *, create: bool = False) -> Path:
    """Đường dẫn của một tài nguyên trong danh sách cho phép; ném EditError nếu không thuộc danh sách."""
    if kind not in KINDS:
        raise EditError(404, f"loại '{kind}' không sửa được")
    parts = name.split("/")
    if kind == "models":
        path = ctx.root / "config" / "models.yaml"
    elif kind == "rbs":
        if len(parts) != 2 or not _NAME.match(parts[0]) or not _ID.match(parts[1]):
            raise EditError(422, "tên yêu cầu phải dạng <adapter>/<MÃ>, ví dụ tls13/TLS13-0100 (mã gồm chữ, số, gạch)")
        adapter = ctx.root / "adapters" / parts[0]
        if not (adapter / "adapter.yaml").is_file():
            raise EditError(404, f"adapter '{parts[0]}' không có")
        path = adapter / "examples" / f"{parts[1]}.rbs"
    elif kind in ("prompt", "role"):
        if len(parts) != 1 or not _NAME.match(name) or not (ctx.agents_root / name / "role.yaml").is_file():
            raise EditError(404, f"agent '{name}' không có hồ sơ role.yaml")
        path = ctx.agents_root / name / ("prompt.md" if kind == "prompt" else "role.yaml")
    else:  # skill
        if len(parts) != 2 or not all(_NAME.match(p) for p in parts):
            raise EditError(422, "tên skill phải dạng <phạm vi>/<tên>")
        path = ctx.root / "skills" / parts[0] / parts[1] / "SKILL.md"
    if not path.is_file() and not (create and kind == "rbs"):
        raise EditError(404, "tệp không tồn tại")
    return path


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def listing(ctx: Ctx) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(kind: str, name: str, path: Path, title: str) -> None:
        text = _text(path)
        out.append(
            {
                "kind": kind,
                "name": name,
                "title": title,
                "path": path.relative_to(ctx.root).as_posix() if ctx.root in path.parents else str(path),
                "bytes": len(text.encode()),
                "mtime": path.stat().st_mtime,
                "sha": sha(text),
                "versions": len(history(ctx, kind, name)),
            }
        )

    for f in sorted((ctx.root / "adapters").glob("*/examples/*.rbs")):
        add("rbs", f"{f.parent.parent.name}/{f.stem}", f, f.stem)
    for r in sorted(ctx.agents_root.glob("*/role.yaml")):
        add("role", r.parent.name, r, r.parent.name)
        if (r.parent / "prompt.md").is_file():
            add("prompt", r.parent.name, r.parent / "prompt.md", r.parent.name)
    for s in sorted((ctx.root / "skills").glob("*/*/SKILL.md")):
        add("skill", f"{s.parent.parent.name}/{s.parent.name}", s, s.parent.name)
    models = ctx.root / "config" / "models.yaml"
    if models.is_file():
        add("models", "models", models, "models.yaml")
    return out


def read(ctx: Ctx, kind: str, name: str) -> dict[str, Any]:
    path = resolve(ctx, kind, name)
    text = _text(path)
    return {
        "kind": kind,
        "name": name,
        "path": str(path),
        "text": text,
        "sha": sha(text),
        "history": history(ctx, kind, name),
        "live_runs": _live(ctx),
    }


def _live(ctx: Ctx) -> int:
    return sum(1 for r in ctx.manager.list_runs(200) if r["status"] in ACTIVE)


# ---- kiểm tra ---------------------------------------------------------------------------------------------------


def _agents_copy(ctx: Ctx, tmp: Path) -> Path:
    dst = tmp / "agents"
    shutil.copytree(ctx.agents_root, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


def _domain_of(agent: str) -> str:
    for pack in current_registry().domains.values():
        if any(a.name == agent for a in pack.agents):
            return pack.name
    return next(iter(current_registry().domains))


def validate(ctx: Ctx, kind: str, name: str, text: str) -> dict[str, Any]:
    """Chạy đúng cổng kiểm tra của lõi trên bản nháp. Trả {ok, errors, warnings, info}; không ghi gì."""
    errors: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {}
    text = text.replace("\r\n", "\n")
    if len(text.encode()) > MAX_BYTES:
        errors.append(f"tệp quá lớn (tối đa {MAX_BYTES // 1000} KB)")
    if not text.strip():
        errors.append("nội dung trống")
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}
    try:
        path = resolve(ctx, kind, name, create=True)
        exists = path.is_file()
        {
            "rbs": _check_rbs,
            "prompt": _check_prompt,
            "role": _check_role,
            "skill": _check_skill,
            "models": _check_models,
        }[kind](ctx, name, text, path, errors, warnings, info)
        info["new"] = not exists
    except EditError as exc:
        errors.append(exc.message)
    except Exception as exc:  # cổng của lõi ném nhiều loại lỗi; người dùng cần thấy nguyên văn
        errors.append(f"{type(exc).__name__}: {exc}")
    if (n := _live(ctx)) and not errors:
        warnings.append(f"{n} lần chạy đang diễn ra đã nạp cấu hình cũ; thay đổi chỉ áp dụng cho các lần chạy sau")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "info": info}


def _check_rbs(
    ctx: Ctx, name: str, text: str, path: Path, errors: list[str], warnings: list[str], info: dict[str, Any]
) -> None:
    from rfcv.adapters.manifest import load_manifest
    from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary
    from rfcv.domains.rfc_protocol.spec.oracle_compiler import compile_oracle
    from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs

    adapter, rid = name.split("/")
    rbs = parse_rbs(text)
    if rbs.requirement_id != rid:
        errors.append(f"mã yêu cầu trong tệp ({rbs.requirement_id}) phải trùng tên tệp ({rid})")
    oracle = compile_oracle(rbs, to_vocabulary(load_manifest(ctx.root / "adapters" / adapter)))
    info.update(
        requirement_id=rbs.requirement_id,
        rtype=rbs.rtype,
        modal=rbs.modal,
        oracle_hash=oracle.oracle_hash,
        variants=sorted(oracle.required_variant_names),
    )
    if rbs.modal in ("SHOULD", "MAY"):
        warnings.append("SHOULD/MAY được báo cáo tách khỏi MUST (BR5)")


def _policy_check(ctx: Ctx, agent: str, mutate: Path, text: str, errors: list[str], info: dict[str, Any]) -> None:
    from rfcv.core.policy import PolicyStore
    from rfcv.core.prompts import prompts_digest

    with tempfile.TemporaryDirectory() as tmp:
        root = _agents_copy(ctx, Path(tmp))
        (root / agent / mutate.name).write_text(text, encoding="utf-8")
        policy = PolicyStore.load(None, current_registry(), _domain_of(agent), root)
        info["prompts_digest"] = prompts_digest(policy, [agent])[:23]
        info["roles"] = list(policy.roles)
        _ = errors


def _check_prompt(
    ctx: Ctx, name: str, text: str, path: Path, errors: list[str], warnings: list[str], info: dict[str, Any]
) -> None:
    _policy_check(ctx, name, path, text, errors, info)
    old = _text(path)
    a, b = PLAYBOOK.search(old), PLAYBOOK.search(text)
    if bool(a) != bool(b) or (a and b and a.group(1) != b.group(1)):
        warnings.append(
            "Khối sổ tay điều tra (playbook) được sinh từ dữ liệu của miền (sync_prompt); sửa tay sẽ làm lệch và có thể làm kiểm thử đồng bộ sổ tay thất bại"
        )
    if len(text) > 30_000:
        warnings.append("Lời nhắc rất dài; tốn token ở mọi lượt gọi agent này")


def _check_role(
    ctx: Ctx, name: str, text: str, path: Path, errors: list[str], warnings: list[str], info: dict[str, Any]
) -> None:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("role.yaml phải là một ánh xạ YAML")
    _policy_check(ctx, name, path, text, errors, info)
    warnings.append("Vùng tin cậy và schema đầu ra do MÃ khai báo; role.yaml phải khớp (kiến trúc, không phải tham số)")


def _check_skill(
    ctx: Ctx, name: str, text: str, path: Path, errors: list[str], warnings: list[str], info: dict[str, Any]
) -> None:
    from rfcv.core.skills import default_registry

    scope, skill = name.split("/")
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "skills"
        shutil.copytree(ctx.root / "skills", dst)
        (dst / scope / skill / "SKILL.md").write_text(text, encoding="utf-8")
        reg = default_registry(dst, None if scope == "core" else scope)
        if skill not in reg.skills:
            errors.append(f"skill '{skill}' không nạp được (kiểm tra tên trong phần đầu tệp phải trùng tên thư mục)")
        else:
            s = reg.skills[skill]
            info.update(description=s.description[:160], task_types=sorted(s.task_types), digest=s.digest[:23])
    if "scripts/" in text.lower() and "```" not in text:
        warnings.append("Skill chỉ là văn bản; thư mục scripts/ và allowed-tools bị cấm")


def _check_models(
    ctx: Ctx, name: str, text: str, path: Path, errors: list[str], warnings: list[str], info: dict[str, Any]
) -> None:
    from rfcv.core.llm_gateway import LLMGateway, ModelsConfig

    if _KEYLIKE.search(re.sub(r"api_key_env\s*:\s*\S+", "", text)):
        errors.append("không ghi khoá API vào tệp cấu hình; chỉ ghi TÊN biến môi trường ở api_key_env")
        return
    cfg = ModelsConfig.model_validate(yaml.safe_load(text))
    roles = [r for pack in current_registry().domains.values() for r in pack.required_roles]
    if missing := LLMGateway(cfg).uncovered(roles):
        errors.append(f"agent chưa được gán mô hình: {', '.join(missing)}")
    info.update(models=sorted(cfg.models), agents=dict(cfg.agents))
    if len(set(cfg.agents.values())) == 1:
        warnings.append("Mọi agent dùng cùng một mô hình: phản biện của Verifier chưa độc lập về họ mô hình")


# ---- lưu, lịch sử, khôi phục ------------------------------------------------------------------------------------


def _hdir(ctx: Ctx, kind: str, name: str) -> Path:
    return ctx.state / "history" / kind / _safe(name)


def history(ctx: Ctx, kind: str, name: str) -> list[dict[str, Any]]:
    d = _hdir(ctx, kind, name)
    out: list[dict[str, Any]] = []
    files: list[Path] = list(d.glob("*.json")) if d.is_dir() else []
    for f in files:
        meta: dict[str, Any] = json.loads(f.read_text(encoding="utf-8"))
        out.append({k: meta[k] for k in ("id", "ts", "actor", "note", "sha", "action", "bytes")})
    return sorted(out, key=lambda h: h["ts"], reverse=True)


def version_text(ctx: Ctx, kind: str, name: str, vid: str) -> str:
    resolve(ctx, kind, name, create=True)
    if not _NAME.match(vid):
        raise EditError(404, "không có phiên bản này")
    f = _hdir(ctx, kind, name) / f"{vid}.txt"
    if not f.is_file():
        raise EditError(404, "không có phiên bản này")
    return f.read_text(encoding="utf-8")


def _snapshot(ctx: Ctx, kind: str, name: str, text: str, actor: str, note: str, action: str) -> str:
    d = _hdir(ctx, kind, name)
    d.mkdir(parents=True, exist_ok=True)
    ts = time.time()
    vid = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(ts))}-{sha(text)[7:15]}"
    (d / f"{vid}.txt").write_text(text, encoding="utf-8", newline="\n")
    (d / f"{vid}.json").write_text(
        json.dumps(
            {
                "id": vid,
                "ts": ts,
                "actor": actor,
                "note": note,
                "sha": sha(text),
                "action": action,
                "bytes": len(text.encode()),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return vid


def _audit(ctx: Ctx, entry: dict[str, Any]) -> None:
    ctx.state.mkdir(parents=True, exist_ok=True)
    with (ctx.state / "audit.jsonl").open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"ts": time.time(), **entry}, ensure_ascii=False) + "\n")


def audit(ctx: Ctx, limit: int = 200) -> list[dict[str, Any]]:
    f = ctx.state / "audit.jsonl"
    if not f.is_file():
        return []
    rows = [
        cast("dict[str, Any]", json.loads(line)) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return rows[::-1][:limit]


def save(
    ctx: Ctx, kind: str, name: str, text: str, *, base_sha: str | None, note: str, actor: str, action: str = "save"
) -> dict[str, Any]:
    actor, note = actor.strip(), note.strip()
    if not actor:
        raise EditError(422, "cần khai tên người sửa")
    if len(note) < 3:
        raise EditError(422, "bắt buộc ghi lý do thay đổi (từ 3 ký tự)")
    text = text.replace("\r\n", "\n")
    result = validate(ctx, kind, name, text)
    if not result["ok"]:
        raise EditError(422, "bản nháp không qua kiểm tra", errors=result["errors"])
    path = resolve(ctx, kind, name, create=True)
    before = _text(path) if path.is_file() else None
    if before is not None and base_sha != sha(before):
        raise EditError(
            409, "tệp đã bị đổi kể từ khi bạn mở; tải lại để xem bản mới rồi gộp thay đổi", current_sha=sha(before)
        )
    if before is None and base_sha:
        raise EditError(409, "tệp đã bị xoá kể từ khi bạn mở")
    if before == text:
        raise EditError(422, "không có thay đổi nào để lưu")
    if before is not None and not history(ctx, kind, name):
        _snapshot(ctx, kind, name, before, "hệ thống", "bản gốc trước lần sửa đầu tiên bằng giao diện", "baseline")
    crlf = path.is_file() and b"\r\n" in path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    tmp.replace(path)
    vid = _snapshot(ctx, kind, name, text, actor, note, action)
    _audit(
        ctx,
        {
            "actor": actor,
            "kind": kind,
            "name": name,
            "action": action,
            "note": note,
            "before": sha(before) if before is not None else None,
            "after": sha(text),
            "version": vid,
            "identity": "tự khai, chưa xác thực",
        },
    )
    return {
        "ok": True,
        "sha": sha(text),
        "version": vid,
        "warnings": result["warnings"],
        "info": result["info"],
        "created": before is None,
    }


def restore(ctx: Ctx, kind: str, name: str, vid: str, *, actor: str, note: str) -> dict[str, Any]:
    old = version_text(ctx, kind, name, vid)
    path = resolve(ctx, kind, name)
    return save(
        ctx,
        kind,
        name,
        old,
        base_sha=sha(_text(path)),
        note=note or f"khôi phục phiên bản {vid}",
        actor=actor,
        action="restore",
    )
