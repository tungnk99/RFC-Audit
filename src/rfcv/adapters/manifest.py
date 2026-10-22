"""Bản kê adapter: tri thức riêng của một đối tượng kiểm chứng, dạng dữ liệu khai báo (thiết kế chính, mục 4.3).

Adapter không chứa mã tuỳ ý. Phần khai báo chung (nguồn đặc tả, SUT, phạm vi mã, tham chiếu) do lõi hiểu;
phần đặc thù miền (`vocabulary`, `field_domains`, `consistency_rules`) lưu dạng từ điển và do domain pack diễn giải.
Thêm đối tượng kiểm chứng có thể cần thêm backend, nhưng không bao giờ sửa lõi (M5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from rfcv.common.hashing import content_hash


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SpecScope(_M):
    """Một văn bản đặc tả trong phạm vi (ví dụ một RFC) và các mục được xét."""

    doc: str
    sections_in_scope: tuple[str, ...] = ()
    role: Literal["primary", "reference"] = "primary"


class SutSpec(_M):
    repo: str
    recipe: str
    start: dict[str, str | int] = Field(default_factory=dict)


class CodeScopeSpec(_M):
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()


class AdapterManifest(_M):
    adapter: str
    version: str
    domain: str = "rfc_protocol"
    backend: str
    verdict_profile: str | None = None  # tên bộ quy tắc trong registry; mặc định bộ duy nhất của miền
    specs: tuple[SpecScope, ...]
    component_taxonomy: tuple[str, ...] = ()
    # Phần đặc thù miền: lõi chỉ giữ và băm, domain pack kiểm định và diễn giải.
    vocabulary: dict[str, Any] = Field(default_factory=dict[str, Any])
    field_domains: dict[str, Any] = Field(default_factory=dict[str, Any])
    consistency_rules: tuple[dict[str, Any], ...] = ()
    locator_hints: dict[str, dict[str, tuple[str, ...]]] = Field(default_factory=dict)
    build_flags: tuple[str, ...] = ()
    sut: SutSpec
    references: tuple[str, ...] = ()
    code_scope: CodeScopeSpec
    examples: str = "examples/*.yaml"

    @property
    def digest(self) -> str:
        return content_hash(self.model_dump(mode="json"))


def load_manifest(adapter_dir: Path) -> AdapterManifest:
    return AdapterManifest.model_validate(yaml.safe_load((adapter_dir / "adapter.yaml").read_text(encoding="utf-8")))
