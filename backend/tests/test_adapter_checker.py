"""Adapter checker: kiểm tra hình thức adapter mẫu và adapter hỏng."""

from __future__ import annotations

from pathlib import Path

from conftest import ADAPTER_DIR
from rfcv.adapters.checker import Status, check_adapter, passed


def test_real_adapter_passes_form_checks() -> None:
    items = check_adapter(ADAPTER_DIR)
    assert passed(items)
    assert {i.check for i in items if i.status is Status.SKIPPED} == {
        "build.sut",
        "oracle.stable",
        "oracle.discriminating",
        "coverage.expressiveness",
    }


def test_broken_adapter_fails(tmp_path: Path) -> None:
    (tmp_path / "adapter.yaml").write_text("adapter: x\n", encoding="utf-8")
    assert not passed(check_adapter(tmp_path))
