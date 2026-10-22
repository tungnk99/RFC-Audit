"""Bản kê lần chạy: mọi đầu vào ảnh hưởng kết luận, băm và ghi lại (thiết kế chính, mục 2.4; BR4).

Kết luận chỉ có giá trị cho đúng bộ đầu vào ghi ở đây. `inputs_digest` chỉ băm phần tất định (không có giờ chạy hay
mã lần chạy), nên hai lần chạy cùng cấu hình cho cùng `inputs_digest`, và khác nhau ở đâu thì `diff` chỉ ra được.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from rfcv import __version__
from rfcv.common.hashing import content_hash
from rfcv.plugins import Registry

TRACKED_PACKAGES = ("pydantic-ai-slim", "pydantic-ai-harness", "pydantic", "lark")


def package_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in TRACKED_PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "không cài"
    return out


def registry_fingerprint(reg: Registry) -> str:
    """Băm tập thứ đã đăng ký (loại bằng chứng, nhiệm vụ, công cụ, schema, miền, bộ quy tắc, nhà cung cấp)."""
    return content_hash(
        {
            "kinds": {k: (v.tier, v.version) for k, v in sorted(reg.kinds.items())},
            "tasks": {k: (v.target_role, v.deterministic) for k, v in sorted(reg.tasks.items())},
            "tools": {k: (v.effect.value, v.reads_untrusted) for k, v in sorted(reg.tools.items())},
            "schemas": sorted(reg.schemas),
            "domains": {k: v.version for k, v in sorted(reg.domains.items())},
            "rule_sets": {k: v.version for k, v in sorted(reg.rule_sets.items())},
            "llm_providers": sorted(reg.llm_providers),
            "backends": sorted(reg.backends),
        }
    )


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    tenant: str
    domain: str
    domain_version: str
    adapter: str
    adapter_version: str
    digests: dict[str, str]
    packages: dict[str, str]
    config: dict[str, Any] = field(default_factory=dict[str, Any])
    rfcv_version: str = __version__
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @property
    def inputs_digest(self) -> str:
        return content_hash(
            {
                "rfcv": self.rfcv_version,
                "tenant": self.tenant,
                "domain": [self.domain, self.domain_version],
                "adapter": [self.adapter, self.adapter_version],
                "digests": self.digests,
                "packages": self.packages,
                "config": self.config,
            }
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "rfcv_version": self.rfcv_version,
            "tenant": self.tenant,
            "domain": {"name": self.domain, "version": self.domain_version},
            "adapter": {"name": self.adapter, "version": self.adapter_version},
            "digests": self.digests,
            "packages": self.packages,
            "config": self.config,
            "inputs_digest": self.inputs_digest,
        }

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def diff(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Các khoá digest khác nhau giữa hai bản kê (để biết vì sao hai lần chạy không so sánh được)."""
    da, db = a.get("digests", {}), b.get("digests", {})
    return sorted(k for k in da.keys() | db.keys() if da.get(k) != db.get(k))
