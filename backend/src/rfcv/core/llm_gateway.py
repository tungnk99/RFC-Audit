"""LLM gateway: cổng duy nhất tới LLM (thiết kế chính, Bảng 17).

- Giữ khoá: khoá API chỉ đọc từ biến môi trường ở đây, không ra khỏi thành phần này.
- Cấu hình (config/models.yaml) có hai phần tách bạch: `models` là kho mô hình được hỗ trợ, mỗi mô hình khai báo một lần
  (nhà cung cấp, id mô hình, endpoint, biến môi trường chứa khoá, tham số); `agents` chỉ gán agent nào dùng mô hình nào.
  Đổi mô hình của một agent là đổi một dòng, không phải khai báo lại khoá. Hash cấu hình ghi vào bản kê.
- Đa nhà cung cấp qua registry `rfcv.llm_providers` (Anthropic, mọi endpoint tương thích OpenAI như Qwen,
  DeepSeek, vLLM cục bộ, hoặc plugin khác), để hai luồng dịch dùng hai họ mô hình khác nhau.
- Không biết framework agent nào: mô hình trả ra là một "handle" mờ do nhà cung cấp tạo.

Lưu ý: các mô hình Claude đời mới từ chối tham số lấy mẫu (temperature…) với lỗi 400,
nên `settings` khai báo riêng theo từng mô hình, không đặt mặc định chung.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfcv.common.hashing import content_hash
from rfcv.plugins import current_registry

ModelHandle = Any  # đối tượng mờ do nhà cung cấp tạo; chỉ runtime agent biết dùng
ProviderFactory = Callable[["ModelSpec", str], ModelHandle]


# SDK của nhà cung cấp đòi khoá không rỗng; máy chủ cục bộ bỏ qua giá trị này.
NO_KEY_PLACEHOLDER = "no-key-needed"


class ModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    # Tên biến môi trường chứa khoá. Bỏ trống cho máy chủ cục bộ không cần khoá (vLLM, Ollama...): khi đó mô hình được dựng
    # với khoá giữ chỗ, và mã không đọc biến môi trường nào.
    api_key_env: str | None = None
    base_url: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class ModelsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Kho mô hình được hỗ trợ, khai báo một lần: tên → nhà cung cấp, id, endpoint, biến môi trường chứa khoá, tham số.
    models: dict[str, ModelSpec] = Field(default_factory=dict[str, ModelSpec])
    # Agent (hoặc agent.luồng, ví dụ rfc_analyst.b) → tên mô hình trong `models`.
    agents: dict[str, str] = Field(default_factory=dict[str, str])

    @model_validator(mode="after")
    def _agents_use_declared_models(self) -> Self:
        unknown = sorted(f"{agent}: {name}" for agent, name in self.agents.items() if name not in self.models)
        if unknown:
            raise ValueError(f"agent gán mô hình chưa khai báo trong `models` ({sorted(self.models)}): {unknown}")
        return self


class UnknownProviderError(KeyError):
    pass


class LLMGateway:
    def __init__(
        self,
        config: ModelsConfig,
        env: Mapping[str, str] | None = None,
        overrides: Mapping[str, ModelHandle] | None = None,
        providers: Mapping[str, ProviderFactory] | None = None,
    ) -> None:
        self._config = config
        self._env = env if env is not None else os.environ
        self._overrides = dict(overrides or {})
        self._providers = providers
        self._cache: dict[str, ModelHandle] = {}

    @classmethod
    def load(cls, path: Path, **kwargs: Any) -> LLMGateway:
        return cls(ModelsConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))), **kwargs)

    @property
    def digest(self) -> str:
        return content_hash(self._config.model_dump(mode="json"))

    def _factories(self) -> Mapping[str, ProviderFactory]:
        return self._providers if self._providers is not None else current_registry().llm_providers

    def validate(self) -> None:
        """Từ chối cấu hình dùng nhà cung cấp chưa đăng ký, trước khi tốn tiền chạy."""
        known = self._factories()
        bad = sorted({s.provider for s in self._config.models.values() if s.provider not in known})
        if bad:
            raise UnknownProviderError(f"nhà cung cấp chưa đăng ký: {bad} (có: {sorted(known)})")

    def api_keys(self) -> dict[str, str]:
        """Tên biến → giá trị của các khoá đã đặt, chỉ để bộ quét rò rỉ tìm dấu vết sau lần chạy (QS-07). Không đưa ra
        ngoài LLM gateway và bộ quét; kết quả quét không bao giờ chứa giá trị."""
        names = {s.api_key_env for s in self._config.models.values() if s.api_key_env is not None}
        return {n: v for n in sorted(names) if (v := self._env.get(n))}

    def uncovered(self, agents: Iterable[str]) -> list[str]:
        """Agent chưa được gán mô hình (gán theo `agent` hoặc theo `agent.luồng`)."""
        assigned = self._config.agents
        return sorted(a for a in agents if a not in assigned and not any(k.startswith(f"{a}.") for k in assigned))

    def _model_name(self, key: str) -> str:
        name = self._config.agents.get(key) or self._config.agents.get(key.split(".", 1)[0])
        if name is None:
            raise KeyError(f"agent '{key}' chưa được gán mô hình trong config (mục agents)")
        return name

    def _spec(self, key: str) -> ModelSpec:
        return self._config.models[self._model_name(key)]

    def model_for(self, key: str) -> ModelHandle:
        """key là tên agent, hoặc agent.luồng (ví dụ rfc_analyst.b). Các agent dùng chung một mô hình dùng chung một handle."""
        if key in self._overrides:
            return self._overrides[key]
        agent = key.split(".", 1)[0]
        if agent in self._overrides:
            return self._overrides[agent]
        name = self._model_name(key)
        if name not in self._cache:
            self._cache[name] = self._build(self._config.models[name])
        return self._cache[name]

    def settings_for(self, key: str) -> dict[str, Any] | None:
        if key in self._overrides or key.split(".", 1)[0] in self._overrides:
            return None
        return dict(self._spec(key).settings) or None

    def _build(self, spec: ModelSpec) -> ModelHandle:
        factory = self._factories().get(spec.provider)
        if factory is None:
            raise UnknownProviderError(f"nhà cung cấp '{spec.provider}' chưa đăng ký")
        if spec.api_key_env is None:
            return factory(spec, NO_KEY_PLACEHOLDER)
        api_key = self._env.get(spec.api_key_env)
        if not api_key:
            raise RuntimeError(f"thiếu biến môi trường {spec.api_key_env}")
        return factory(spec, api_key)
