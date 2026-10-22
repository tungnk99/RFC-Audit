"""Danh mục cho màn hình chọn: giao thức RFC (adapter) và yêu cầu của nó, agent, mô hình, nhà cung cấp khả dụng.

Chỉ đọc. Không bao giờ trả giá trị khoá API, chỉ trả tên biến và việc nó đã đặt hay chưa.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
from pathlib import Path
from typing import Any, cast

import yaml

from rfcv.adapters.manifest import load_manifest
from rfcv.plugins import Registry, current_registry

_RBS_HEAD = re.compile(r"^requirement\s+(\S+)\s+from\s+(\S+)\s+modal\s+(\w+)\s+type\s+(\w)", re.MULTILINE)
RBS_HEAD = _RBS_HEAD
ALLOW_LOCAL_ENV = "RFCV_ALLOW_UNSANDBOXED_EXECUTOR"


def requirement_files(adapter_dir: Path) -> dict[str, Path]:
    """requirement_id -> tệp .rbs trong examples/ của adapter."""
    out: dict[str, Path] = {}
    for f in sorted((adapter_dir / "examples").glob("*.rbs")):
        m = _RBS_HEAD.search(f.read_text(encoding="utf-8"))
        out[m.group(1) if m else f.stem] = f
    return out


def _requirement_info(rid: str, path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    m = _RBS_HEAD.search(text)
    return {
        "id": rid,
        "source": m.group(2) if m else None,
        "modal": m.group(3) if m else None,
        "rtype": m.group(4) if m else None,
        "text": text,
    }


def list_adapters(root: Path, rfc_dir: Path | None) -> list[dict[str, Any]]:
    """Mỗi adapter là một giao thức/đối tượng kiểm chứng; `specs` là các RFC trong phạm vi, `requirements` là yêu cầu đã duyệt."""
    out: list[dict[str, Any]] = []
    for yml in sorted((root / "adapters").glob("*/adapter.yaml")):
        adapter_dir = yml.parent
        try:
            m = load_manifest(adapter_dir)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            out.append({"id": adapter_dir.name, "error": str(exc)[:300], "specs": [], "requirements": []})
            continue
        specs = [
            {
                "doc": s.doc,
                "role": s.role,
                "sections": list(s.sections_in_scope),
                "xml_available": bool(rfc_dir and (rfc_dir / f"{s.doc.lower()}.xml").is_file()),
            }
            for s in m.specs
        ]
        out.append(
            {
                "id": m.adapter,
                "dir": adapter_dir.name,
                "version": m.version,
                "domain": m.domain,
                "backend": m.backend,
                "specs": specs,
                "components": list(m.component_taxonomy),
                "sut": {"repo": m.sut.repo, "commit": m.sut.commit, "start": m.sut.start},
                "references": list(m.references),
                "code_scope": {"include": list(m.code_scope.include), "exclude": list(m.code_scope.exclude)},
                "requirements": [_requirement_info(rid, p) for rid, p in requirement_files(adapter_dir).items()],
                "demo_supported": m.adapter == "tls13",  # bộ mô phỏng chỉ mô hình hoá độ dài bản ghi TLS
            }
        )
    return out


def list_agents(reg: Registry, agents_root: Path, models: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pack in reg.domains.values():
        for a in pack.agents:
            role: dict[str, Any] = {}
            role_file = agents_root / a.name / "role.yaml"
            if a.has_role and role_file.is_file():
                role = yaml.safe_load(role_file.read_text(encoding="utf-8")) or {}
            rows.append(
                {
                    "name": a.name,
                    "domain": pack.name,
                    "zone": role.get("zone", "tất định"),
                    "stage": a.stage,
                    "tasks": [t.name for t in a.tasks],
                    "skills": list(role.get("skills", [])),
                    "output": role.get("output_schema"),
                    "wired": a.wired,
                    "summary": a.summary,
                    "deterministic": not a.has_role,
                    "model": models.get("agents", {}).get(a.name),
                }
            )
    return rows


def models_status(models_path: Path) -> dict[str, Any]:
    """Mô hình khai báo và khoá đã đặt trong môi trường chưa (không bao giờ trả giá trị khoá)."""
    if not models_path.is_file():
        return {"error": f"không có {models_path}", "models": {}, "agents": {}}
    cfg: dict[str, Any] = yaml.safe_load(models_path.read_text(encoding="utf-8")) or {}
    declared = cast("dict[str, dict[str, Any]]", cfg.get("models") or {})
    models = {
        name: {
            "provider": spec.get("provider"),
            "model": spec.get("model"),
            "api_key_env": spec.get("api_key_env"),
            "key_set": bool(os.environ.get(str(spec.get("api_key_env")))),
        }
        for name, spec in declared.items()
    }
    return {"models": models, "agents": dict(cfg.get("agents") or {})}


def capabilities(reg: Registry) -> dict[str, Any]:
    """Nhà cung cấp chạy thật cần gì và máy này đã có chưa, để giao diện báo trước thay vì lỗi giữa chừng."""
    docker = shutil.which(os.environ.get("RFCV_DOCKER", "docker")) is not None
    tree_sitter = importlib.util.find_spec("tree_sitter") is not None
    local_ok = os.environ.get(ALLOW_LOCAL_ENV) == "1"
    return {
        "code_indexes": [
            {
                "name": n,
                "available": docker if n == "treesitter" else tree_sitter,
                "note": "cần docker và image code-indexer"
                if n == "treesitter"
                else "cần gói tree-sitter (extra codeindex)",
            }
            for n in sorted(reg.code_indexes)
        ],
        "executors": [
            {
                "name": n,
                "available": docker if n == "docker" else local_ok,
                "note": "cần docker và image code-index-worker"
                if n == "docker"
                else f"chạy lệnh trên máy, KHÔNG sandbox; người vận hành phải đặt {ALLOW_LOCAL_ENV}=1 trước khi bật serve",
            }
            for n in sorted(reg.executors)
        ],
        "sut_launchers": [{"name": n, "available": True, "note": ""} for n in sorted(reg.sut_launchers)],
        "demo_cases": [
            {"name": "faulty", "label": "SUT giả gửi sai cảnh báo (kỳ vọng VIOLATION)"},
            {"name": "correct", "label": "SUT giả đúng RFC (kỳ vọng COMPLIANT)"},
        ],
    }


def build_catalog(root: Path, *, agents_root: Path, code_roots: list[Path]) -> dict[str, Any]:
    reg = current_registry()
    rfc_dir = root / "inputs" / "rfc"
    models = models_status(root / "config" / "models.yaml")
    return {
        "adapters": list_adapters(root, rfc_dir if rfc_dir.is_dir() else None),
        "agents": list_agents(reg, agents_root, models),
        "models": models,
        "capabilities": capabilities(reg),
        "code_roots": [str(p) for p in code_roots],
    }
