"""Mô hình cục bộ không cần khoá (BL-63): vLLM, Ollama và các máy chủ kiểu OpenAI khác thường không có khoá API."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml
from pydantic_ai import Agent, models
from typer.testing import CliRunner

from rfcv.core.llm_gateway import NO_KEY_PLACEHOLDER, LLMGateway, ModelsConfig, ModelSpec
from rfcv.ui.cli import app


def config(base_url: str = "http://127.0.0.1:1/v1") -> ModelsConfig:
    return ModelsConfig.model_validate(
        {
            "models": {
                "local": {"provider": "openai_compatible", "model": "qwen-local", "base_url": base_url},
                "remote": {"provider": "openai_compatible", "model": "x", "api_key_env": "REMOTE_KEY"},
            },
            "agents": {"planner": "local", "verifier": "remote"},
        }
    )


def test_a_model_without_api_key_env_is_valid_and_the_key_is_optional() -> None:
    assert ModelSpec(provider="openai_compatible", model="m").api_key_env is None
    assert config().models["remote"].api_key_env == "REMOTE_KEY"


def test_a_local_model_is_built_without_any_environment_variable() -> None:
    llm = LLMGateway(config(), env={})
    assert llm.model_for("planner") is not None  # không đòi biến môi trường nào
    with pytest.raises(RuntimeError, match="REMOTE_KEY"):
        llm.model_for("verifier")  # mô hình ngoài vẫn đòi khoá như trước


def test_the_placeholder_key_never_appears_as_a_secret_to_scan_for() -> None:
    llm = LLMGateway(config(), env={"REMOTE_KEY": "sk-real-secret-0123456789"})
    assert llm.api_keys() == {"REMOTE_KEY": "sk-real-secret-0123456789"}
    assert LLMGateway(config(), env={}).api_keys() == {}  # mô hình cục bộ không đóng góp khoá nào


def test_models_command_says_local_models_need_no_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REMOTE_KEY", raising=False)
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(json.loads(config().model_dump_json())), encoding="utf-8")
    out = CliRunner().invoke(app, ["models", str(path)]).output
    assert "không cần khoá" in out and "qwen-local" in out
    assert "REMOTE_KEY (CHƯA đặt" in out


class _FakeOpenAI(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeOpenAI.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "model": body["model"]})
        reply = {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "xin chào"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture
def local_server() -> Iterator[str]:
    _FakeOpenAI.seen = []
    server = HTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()
    thread.join(timeout=5)


async def test_a_keyless_local_endpoint_is_reached_over_http_with_the_configured_model(local_server: str) -> None:
    """Đường đi thật: gateway → provider openai_compatible → HTTP tới `base_url`, không biến môi trường nào."""
    llm = LLMGateway(config(local_server), env={})
    with models.override_allow_model_requests(True):
        result = await Agent(llm.model_for("planner")).run("chào")
    assert result.output == "xin chào"
    (call,) = _FakeOpenAI.seen
    assert call["path"].endswith("/chat/completions") and call["model"] == "qwen-local"
    assert call["auth"] == f"Bearer {NO_KEY_PLACEHOLDER}"  # khoá giữ chỗ, không phải khoá thật
