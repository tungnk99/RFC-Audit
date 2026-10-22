"""Hàm chấm điểm của scripts/measure_component_map.py (BL-15): so bản đồ của agent với nhãn chuẩn, áp hai luật loại của handler."""

from __future__ import annotations

import importlib.util
from types import ModuleType

from conftest import ROOT


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "measure_component_map", ROOT / "scripts" / "measure_component_map.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeIndex:
    def __init__(self, known: set[tuple[str, str]]) -> None:
        self.known = known

    def symbol_in_file(self, file: str, symbol: str) -> object | None:
        return object() if (file, symbol) in self.known else None


def test_score_counts_correct_wrong_missing_and_the_handlers_rejections() -> None:
    m = load()
    m.TRUTH = {("a.c", "f"): "alerts", ("a.c", "g"): "handshake", ("a.c", "h"): "extensions", ("a.c", "i"): "alerts"}
    index = FakeIndex({("a.c", "f"), ("a.c", "g"), ("a.c", "h"), ("a.c", "extra")})
    entries = [
        {"file": "a.c", "symbol": "f", "component": "alerts"},  # đúng
        {"file": "a.c", "symbol": "g", "component": "extensions"},  # sai thành phần
        {"file": "a.c", "symbol": "h", "component": "not_a_component"},  # ngoài phân loại: bị loại, tính là chưa gán
        {"file": "a.c", "symbol": "ghost", "component": "alerts"},  # ký hiệu không có trong chỉ mục: bị loại
        {"file": "a.c", "symbol": "extra", "component": "alerts"},  # hợp lệ nhưng không thuộc nhãn chuẩn
    ]
    r = m.score(entries, index, {"alerts", "handshake", "extensions"})
    assert (r["correct"], r["of"], r["accuracy"]) == (1, 4, 0.25)
    assert r["wrong"] == {"g": ("handshake", "extensions")}
    assert sorted(r["not_mapped"]) == ["h", "i"]
    assert r["rejected_by_handler"] == {"COMPONENT_NOT_IN_TAXONOMY": 1, "SYMBOL_NOT_IN_INDEX": 1}
    assert r["extra_entries"] == 1


def test_the_first_entry_for_a_symbol_wins() -> None:
    m = load()
    m.TRUTH = {("a.c", "f"): "alerts"}
    index = FakeIndex({("a.c", "f")})
    entries = [
        {"file": "a.c", "symbol": "f", "component": "handshake"},
        {"file": "a.c", "symbol": "f", "component": "alerts"},
    ]
    assert m.score(entries, index, {"alerts", "handshake"})["correct"] == 0


def test_the_ground_truth_sets_are_disjoint_and_use_the_adapter_taxonomy() -> None:
    import yaml

    m = load()
    taxonomy = set(
        yaml.safe_load((ROOT / "adapters" / "tls13" / "adapter.yaml").read_text("utf-8"))["component_taxonomy"]
    )
    assert not set(m.EASY) & set(m.HARD)
    assert len(m.EASY) == 30 and set(m.EASY.values()) <= taxonomy and set(m.HARD.values()) <= taxonomy
