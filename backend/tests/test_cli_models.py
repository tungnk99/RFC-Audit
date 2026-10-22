"""`rfcv models`: báo đúng trạng thái biến chứa khoá và nói rõ CLI không tự nạp .env (CT-15)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfcv.ui.cli import app

CONFIG = Path(__file__).resolve().parents[1] / "config" / "models.yaml"


def _key_vars() -> list[str]:
    import yaml

    models = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["models"]
    return sorted({spec["api_key_env"] for spec in models.values()})


def test_models_reports_unset_keys_and_explains_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _key_vars():
        monkeypatch.delenv(var, raising=False)
    result = CliRunner().invoke(app, ["models", str(CONFIG)])
    assert "CHƯA đặt trong môi trường" in result.output
    assert "không tự nạp .env" in result.output


def test_models_never_prints_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-test-khong-duoc-in-ra"
    for var in _key_vars():
        monkeypatch.setenv(var, secret)
    result = CliRunner().invoke(app, ["models", str(CONFIG)])
    assert secret not in result.output
    assert "CHƯA đặt" not in result.output
    assert "không tự nạp .env" not in result.output
