"""Dữ liệu cho các tab quản lý: thống kê gộp nhiều lần chạy, hồ sơ agent, thư viện skill, tình trạng hệ thống, chi tiết adapter.

Chỉ đọc. Số liệu gộp lấy từ chính trace.db/evidence.db của từng lần chạy; lần chạy đã xong không đổi nên bản tóm tắt được nhớ
theo (đường dẫn, mtime, kích thước) và chỉ tính lại khi tệp đổi.
"""

from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import sqlite3
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import yaml

from rfcv import __version__
from rfcv.adapters.checker import check_adapter
from rfcv.adapters.manifest import load_manifest
from rfcv.api import catalog, runstore
from rfcv.api.runs import RunManager
from rfcv.plugins import Registry, current_registry

_DIGESTS: dict[tuple[str, int, int, int], dict[str, Any]] = {}
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


# ---- tóm tắt một lần chạy ---------------------------------------------------------------------------------------


def _tail(path: Path) -> tuple[int, int]:
    s = path.stat()
    return s.st_mtime_ns, s.st_size


def run_digest(run_dir: Path) -> dict[str, Any]:
    """Tóm tắt số liệu của một lần chạy: nhãn, token và công cụ theo agent, bằng chứng theo tầng. Nhớ theo tệp."""
    trace, ev = run_dir / "trace.db", run_dir / "evidence.db"
    if not trace.is_file():
        return {}
    ev_sig = _tail(ev) if ev.is_file() else (0, 0)
    key = (str(run_dir), *_tail(trace), ev_sig[0])
    if key in _DIGESTS:
        return _DIGESTS[key]
    roles: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "runs": 0,
            "tokens": 0,
            "tool_calls": 0,
            "duration_ms": 0,
            "failures": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    )
    tools: Counter[str] = Counter()
    denied: Counter[str] = Counter()
    verdicts: list[dict[str, Any]] = []
    stops: dict[str, dict[str, Any]] = {}
    first, last = runstore.time_span(run_dir)
    rounds = 0
    for e in runstore.kind_events(run_dir, "role_run", "llm_run", "tool_call", "tool_denied", "verdict", "stop"):
        p: dict[str, Any] = e["payload"]
        k = e["kind"]
        if k == "role_run":
            r = roles[str(p.get("role"))]
            r["runs"] += 1
            r["tokens"] += int(p.get("tokens") or 0)
            r["tool_calls"] += int(p.get("tool_calls") or 0)
            r["duration_ms"] += int(p.get("duration_ms") or 0)
            r["failures"] += 0 if p.get("ok") else 1
        elif k == "llm_run":
            r = roles[str(e["role"])]
            r["input_tokens"] += int(p.get("input_tokens") or 0)
            r["output_tokens"] += int(p.get("output_tokens") or 0)
        elif k == "tool_call":
            tools[str(p.get("tool"))] += 1
        elif k == "tool_denied":
            denied[str(p.get("tool"))] += 1
        elif k == "verdict":
            verdicts.append(
                {
                    "requirement_id": e["requirement_id"],
                    "label": p.get("label"),
                    "rule": p.get("rule"),
                    "assurance": p.get("assurance"),
                }
            )
        elif k == "stop":
            stops[str(e["requirement_id"])] = p
            rounds += int(p.get("round") or 0)
    tiers: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    n_evidence = 0
    if ev.is_file():
        with runstore.ro(ev) as c:
            for (body,) in c.execute("SELECT body FROM evidence"):
                rec: dict[str, Any] = json.loads(body)
                n_evidence += 1
                tiers[str(rec.get("tier"))] += 1
                body_payload: dict[str, Any] = rec.get("payload") or {}
                kinds[str(body_payload.get("kind"))] += 1
    used: list[dict[str, Any]] = [s.get("used") or {} for s in stops.values()]
    out: dict[str, Any] = {
        "verdicts": verdicts,
        "roles": dict(roles),
        "tools": dict(tools),
        "denied": dict(denied),
        "evidence": n_evidence,
        "evidence_by_tier": dict(tiers),
        "evidence_by_kind": dict(kinds),
        "requirements": len(stops) or len(verdicts),
        "rounds": rounds,
        "tokens": sum(int(r["tokens"]) for r in roles.values()),
        "tool_calls": sum(int(u.get("tool_calls") or 0) for u in used),
        "seconds": (last - first) / 1e9 if last > first else 0.0,
        "stop_reasons": dict(Counter(str(s.get("reason")) for s in stops.values())),
    }
    _DIGESTS[key] = out
    return out


# ---- thống kê gộp -----------------------------------------------------------------------------------------------


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def stats(m: RunManager, days: int | None) -> dict[str, Any]:
    now = time.time()
    since = now - days * 86400 if days else 0.0
    runs = [r for r in m.list_runs(10_000) if (r.get("started_at") or r["created_at"]) >= since]
    by_status: Counter[str] = Counter(r["status"] for r in runs)
    by_mode: Counter[str] = Counter(str(r["spec"].get("mode")) for r in runs)
    by_adapter: Counter[str] = Counter(str(r["spec"].get("adapter")) for r in runs)
    labels: Counter[str] = Counter()
    rules: Counter[str] = Counter()
    assurance: Counter[str] = Counter()
    role_tot: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    tools: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    stop_reasons: Counter[str] = Counter()
    daily: dict[str, dict[str, int]] = {}
    span = days or 30
    for i in range(span - 1, -1, -1):
        daily[_day(now - i * 86400)] = {"runs": 0, "finished": 0, "failed": 0, "tokens": 0, "tool_calls": 0}
    tokens = tool_calls = evidence = requirements = 0
    seconds = 0.0
    recent: list[dict[str, Any]] = []
    for r in runs:
        d = m.run_dir(r["run_id"])
        dig = run_digest(d) if d else {}
        tokens += int(dig.get("tokens", 0))
        tool_calls += int(dig.get("tool_calls", 0))
        evidence += int(dig.get("evidence", 0))
        requirements += int(dig.get("requirements", 0))
        seconds += float(dig.get("seconds", 0.0))
        for v in dig.get("verdicts", []):
            labels[str(v["label"])] += 1
            rules[str(v["rule"])] += 1
            assurance[str(v["assurance"])] += 1
        for role, st in dig.get("roles", {}).items():
            for k2, v2 in st.items():
                role_tot[role][k2] += int(v2)
        tools.update(dig.get("tools", {}))
        tiers.update(dig.get("evidence_by_tier", {}))
        kinds.update(dig.get("evidence_by_kind", {}))
        stop_reasons.update(dig.get("stop_reasons", {}))
        day = _day(r.get("started_at") or r["created_at"])
        if day in daily:
            b = daily[day]
            b["runs"] += 1
            b["finished"] += r["status"] == "finished"
            b["failed"] += r["status"] in ("failed", "interrupted")
            b["tokens"] += int(dig.get("tokens", 0))
            b["tool_calls"] += int(dig.get("tool_calls", 0))
        if r["status"] in ("failed", "interrupted") or (r.get("leak_scan") and not r["leak_scan"]["clean"]):
            recent.append(
                {"run_id": r["run_id"], "status": r["status"], "error": r.get("error"), "leak": r.get("leak_scan")}
            )
    return {
        "range_days": days,
        "totals": {
            "runs": len(runs),
            "active": by_status["running"] + by_status["queued"],
            "requirements": requirements,
            "tokens": tokens,
            "tool_calls": tool_calls,
            "evidence": evidence,
            "seconds": seconds,
            "tokens_per_requirement": tokens // requirements if requirements else 0,
            "seconds_per_requirement": seconds / requirements if requirements else 0.0,
        },
        "by_status": dict(by_status),
        "by_mode": dict(by_mode),
        "by_adapter": dict(by_adapter),
        "verdicts": dict(labels),
        "rules": dict(rules),
        "assurance": dict(assurance),
        "stop_reasons": dict(stop_reasons),
        "daily": [{"date": k, **v} for k, v in daily.items()],
        "roles": [{"role": k, **v} for k, v in sorted(role_tot.items(), key=lambda kv: -kv[1]["tokens"])],
        "tools": [{"tool": k, "count": v} for k, v in tools.most_common(15)],
        "evidence_by_tier": [{"tier": k, "count": v} for k, v in sorted(tiers.items())],
        "evidence_by_kind": [{"kind": k, "count": v} for k, v in kinds.most_common(12)],
        "attention": recent[:8],
    }


# ---- agent ------------------------------------------------------------------------------------------------------


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def agent_detail(name: str, agents_root: Path, m: RunManager) -> dict[str, Any] | None:
    reg = current_registry()
    spec = next((a for p in reg.domains.values() for a in p.agents if a.name == name), None)
    if spec is None:
        return None
    role_file = agents_root / name / "role.yaml"
    role: dict[str, Any] = yaml.safe_load(role_file.read_text(encoding="utf-8")) if role_file.is_file() else {}
    prompt_name = str(role.get("prompt") or "prompt.md")
    tools: list[dict[str, Any]] = []
    for t in cast("list[str]", role.get("tools") or []):
        d = reg.tools.get(t)
        tools.append(
            {"name": t, "effect": d.effect.value if d else None, "reads_untrusted": bool(d and d.reads_untrusted)}
        )
    totals: dict[str, int] = defaultdict(int)
    for r in m.list_runs(10_000):
        rd = m.run_dir(r["run_id"])
        roles_of: dict[str, dict[str, int]] = run_digest(rd).get("roles", {}) if rd else {}
        st = roles_of.get(name)
        if st:
            for k, v in st.items():
                totals[k] += int(v)
    return {
        "name": name,
        "stage": spec.stage,
        "wired": spec.wired,
        "summary": spec.summary,
        "zone": role.get("zone") or spec.zone or "tất định",
        "tasks": [{"name": t.name, "deterministic": t.deterministic, "target_role": t.target_role} for t in spec.tasks],
        "role": role,
        "tools": tools,
        "prompt": _read(agents_root / name / prompt_name),
        "usage": dict(totals),
        "files": sorted(
            p.name for p in (agents_root / name).glob("*") if p.is_file() and p.suffix in (".py", ".yaml", ".md")
        ),
    }


# ---- skill ------------------------------------------------------------------------------------------------------


def _split_front(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONT.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
    return meta, m.group(2)


def _skill_dirs(skills_root: Path) -> Iterator[tuple[str, Path]]:
    for f in sorted(skills_root.glob("*/*/SKILL.md")):
        yield f.parent.parent.name, f.parent


def skills_list(skills_root: Path, agents_root: Path) -> list[dict[str, Any]]:
    used: dict[str, list[str]] = defaultdict(list)
    for role in sorted(agents_root.glob("*/role.yaml")):
        data: dict[str, Any] = yaml.safe_load(role.read_text(encoding="utf-8")) or {}
        for s in cast("list[str]", data.get("skills") or []):
            used[s].append(role.parent.name)
    out: list[dict[str, Any]] = []
    for scope, d in _skill_dirs(skills_root):
        meta, body = _split_front((d / "SKILL.md").read_text(encoding="utf-8"))
        md = cast("dict[str, Any]", meta.get("metadata") or {})
        out.append(
            {
                "name": d.name,
                "scope": scope,
                "description": meta.get("description", ""),
                "task_types": str(md.get("rfcv-task-types", "")).split(),
                "version": str(md.get("version", "")),
                "used_by": used.get(d.name, []),
                "lines": body.count("\n") + 1,
                "references": sorted(p.name for p in (d / "references").glob("*") if p.is_file())
                if (d / "references").is_dir()
                else [],
            }
        )
    return out


def skill_detail(skills_root: Path, scope: str, name: str, file: str | None) -> dict[str, Any] | None:
    d = (skills_root / scope / name).resolve()
    if skills_root.resolve() not in d.parents or not (d / "SKILL.md").is_file():
        return None
    if file:
        refs = (d / "references").resolve()
        ref = (refs / file).resolve()
        if refs not in ref.parents or not ref.is_file():
            return None
        return {"name": name, "file": file, "text": ref.read_text(encoding="utf-8")}
    meta, body = _split_front((d / "SKILL.md").read_text(encoding="utf-8"))
    return {"name": name, "scope": scope, "meta": meta, "text": body}


# ---- giao thức --------------------------------------------------------------------------------------------------


def adapter_detail(root: Path, adapter_id: str) -> dict[str, Any] | None:
    adapter_dir = root / "adapters" / adapter_id
    if not (adapter_dir / "adapter.yaml").is_file() or adapter_dir.resolve().parent != (root / "adapters").resolve():
        return None
    manifest = load_manifest(adapter_dir)
    checks = [
        {"check": c.check, "status": c.status.value, "detail": c.detail}
        for c in check_adapter(adapter_dir, root / "skills")
    ]
    found = [a for a in catalog.list_adapters(root, root / "inputs" / "rfc") if a.get("dir") == adapter_id]
    base: dict[str, Any] = found[0] if found else {}
    return {
        **base,
        "manifest": manifest.model_dump(mode="json"),
        "digest": manifest.digest,
        "yaml": (adapter_dir / "adapter.yaml").read_text(encoding="utf-8"),
        "checks": checks,
        "files": sorted(
            str(p.relative_to(adapter_dir)).replace("\\", "/") for p in adapter_dir.rglob("*") if p.is_file()
        ),
    }


# ---- hệ thống ---------------------------------------------------------------------------------------------------


def _version(pkg: str) -> str | None:
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return None


def _registry_view(reg: Registry) -> dict[str, Any]:
    return {
        "domains": [
            {"name": k, "version": v.version, "agents": len(v.agents), "tasks": len(v.tasks)}
            for k, v in reg.domains.items()
        ],
        "evidence_kinds": [
            {"name": k, "tier": v.tier, "version": v.version, "producers": sorted(v.producers)}
            for k, v in reg.kinds.items()
        ],
        "tasks": [
            {"name": k, "target_role": v.target_role, "deterministic": v.deterministic} for k, v in reg.tasks.items()
        ],
        "tools": [
            {"name": k, "effect": v.effect.value, "reads_untrusted": v.reads_untrusted}
            for k, v in sorted(reg.tools.items())
        ],
        "rule_sets": [{"name": k, "version": v.version} for k, v in reg.rule_sets.items()],
        "backends": sorted(reg.backends),
        "code_indexes": sorted(reg.code_indexes),
        "executors": sorted(reg.executors),
        "sut_launchers": sorted(reg.sut_launchers),
        "llm_providers": sorted(reg.llm_providers),
        "agent_runtimes": sorted(reg.agent_runtimes),
    }


def system_info(m: RunManager) -> dict[str, Any]:
    import os

    reg = current_registry()
    size = count = 0
    if m.runs_dir.is_dir():
        for f in m.runs_dir.rglob("*"):
            if f.is_file():
                count += 1
                size += f.stat().st_size
    models_path = m.root / "config" / "models.yaml"
    return {
        "versions": {
            "rfcv": __version__,
            "python": platform.python_version(),
            "os": platform.platform(),
            "pydantic_ai": _version("pydantic-ai-slim"),
            "pydantic": _version("pydantic"),
            "fastapi": _version("fastapi"),
            "uvicorn": _version("uvicorn"),
            "sqlite": sqlite3.sqlite_version,
        },
        "paths": {"root": str(m.root), "runs": str(m.runs_dir), "code_roots": [str(p) for p in m.code_roots]},
        "storage": {
            "files": count,
            "bytes": size,
            "runs": len(list(m.runs_dir.glob("*/trace.db"))) if m.runs_dir.is_dir() else 0,
        },
        "models": catalog.models_status(models_path),
        "models_yaml": _read(models_path),
        "capabilities": catalog.capabilities(reg),
        "registry": _registry_view(reg),
        "flags": {
            "unsandboxed_executor": os.environ.get(catalog.ALLOW_LOCAL_ENV) == "1",
            "trace_mirror": bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")),
        },
    }
