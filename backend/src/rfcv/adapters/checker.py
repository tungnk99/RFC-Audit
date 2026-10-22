"""Adapter checker: kiểm định adapter trước khi nạp (thiết kế chính, mục 4.3; tài liệu adapter, Bảng 9).

Phần chung: bản kê đúng schema, backend đã đăng ký, công thức dựng SUT tồn tại, skill hợp lệ.
Phần riêng của miền (từ vựng, mẫu kiểm thử, ví dụ đặc tả) do domain pack đóng góp qua `adapter_checks`.
Các kiểm tra cần sandbox (dựng được, oracle ổn định, oracle phân biệt được, độ phủ biểu đạt) báo SKIPPED khi chưa
có Docker. Adapter chưa đạt không được nạp.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import ValidationError

from rfcv.adapters.manifest import AdapterManifest, load_manifest
from rfcv.plugins import Registry, current_registry


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class CheckItem:
    check: str
    status: Status
    detail: str = ""


def check_adapter(
    adapter_dir: Path, skills_root: Path | None = None, registry: Registry | None = None
) -> list[CheckItem]:
    reg = registry or current_registry()
    items: list[CheckItem] = []
    try:
        manifest = load_manifest(adapter_dir)
    except (OSError, ValidationError, yaml.YAMLError) as exc:
        return [CheckItem("form.manifest", Status.FAIL, str(exc)[:500])]
    items.append(CheckItem("form.manifest", Status.PASS, f"{manifest.adapter}@{manifest.version}"))

    if manifest.domain not in reg.domains:
        return [*items, CheckItem("form.domain", Status.FAIL, f"miền '{manifest.domain}' chưa đăng ký")]
    pack = reg.domain(manifest.domain)
    items += _check_common(adapter_dir, manifest, reg)
    for check in pack.adapter_checks:
        items += check(adapter_dir, manifest)
    items += _check_skills(manifest.adapter, skills_root or adapter_dir.parent.parent / "skills")
    for name in ("build.sut", "oracle.stable", "oracle.discriminating", "coverage.expressiveness"):
        items.append(CheckItem(name, Status.SKIPPED, "cần sandbox Docker"))
    return items


def _check_common(adapter_dir: Path, m: AdapterManifest, reg: Registry) -> list[CheckItem]:
    items = [CheckItem("form.backend", Status.PASS if m.backend in reg.backends else Status.FAIL, m.backend)]
    if m.verdict_profile is not None:
        known = m.verdict_profile in reg.rule_sets
        items.append(CheckItem("form.verdict_profile", Status.PASS if known else Status.FAIL, m.verdict_profile))
    recipe = adapter_dir / m.sut.recipe
    items.append(CheckItem("form.sut_recipe", Status.PASS if recipe.is_file() else Status.FAIL, m.sut.recipe))
    return items


def passed(items: list[CheckItem]) -> bool:
    return all(i.status is not Status.FAIL for i in items)


def _check_skills(adapter: str, skills_root: Path) -> list[CheckItem]:
    """Skill là đầu vào TRUSTED: phải đúng chuẩn Agent Skills và ràng buộc của rfcv (không scripts/, không symlink)."""
    from rfcv.core.skills import default_registry

    if not skills_root.is_dir():
        return [CheckItem("form.skills", Status.SKIPPED, "không có thư mục skills/")]
    try:
        registry = default_registry(skills_root, adapter)
    except ValueError as exc:
        return [CheckItem("form.skills", Status.FAIL, str(exc)[:800])]
    return [CheckItem("form.skills", Status.PASS, f"{len(registry.skills)} skill, digest {registry.digest[:19]}")]
