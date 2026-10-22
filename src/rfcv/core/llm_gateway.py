"""LLM gateway: cổng duy nhất tới LLM (thiết kế chính, Bảng 17).

- Giữ khoá: khoá API chỉ đọc từ biến môi trường ở đây, không ra khỏi thành phần này.
- Cố định mô hình và tham số theo vai trò (config/models.yaml); hash cấu hình ghi vào bản kê.
- Đa nhà cung cấp qua registry `rfcv.llm_providers` (Anthropic, mọi endpoint tương thích OpenAI như Qwen,
  DeepSeek, vLLM cục bộ, hoặc plugin khác), để hai luồng dịch dùng hai họ mô hình khác nhau.
- Không biết framework agent nào: mô hình trả ra là một "handle" mờ do nhà cung cấp tạo.

Lưu ý: các mô hình Claude đời mới từ chối tham số lấy mẫu (temperature…) với lỗi 400,
nên `settings` khai báo riêng theo vai trò, không đặt mặc định chung.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from rfcv.common.hashing import content_hash
from rfcv.plugins import current_registry

ModelHandle = Any  # đối tượng mờ do nhà cung cấp tạo; chỉ runtime agent biết dùng
ProviderFactory = Callable[["ModelSpec", str], ModelHandle]


class ModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    api_key_env: str
    base_url: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class ModelsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    roles: dict[str, ModelSpec]


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
        bad = sorted({s.provider for s in self._config.roles.values() if s.provider not in known})
        if bad:
            raise UnknownProviderError(f"nhà cung cấp chưa đăng ký: {bad} (có: {sorted(known)})")

    def _spec(self, key: str) -> ModelSpec:
        role = key.split(".", 1)[0]
        spec = self._config.roles.get(key) or self._config.roles.get(role)
        if spec is None:
            raise KeyError(f"không có cấu hình mô hình cho {key}")
        return spec

    def model_for(self, key: str) -> ModelHandle:
        """key là tên vai trò, hoặc vai trò.luồng (ví dụ rfc_analyst.b)."""
        if key in self._overrides:
            return self._overrides[key]
        role = key.split(".", 1)[0]
        if role in self._overrides:
            return self._overrides[role]
        if key not in self._cache:
            self._cache[key] = self._build(self._spec(key))
        return self._cache[key]

    def settings_for(self, key: str) -> dict[str, Any] | None:
        if key in self._overrides or key.split(".", 1)[0] in self._overrides:
            return None
        return dict(self._spec(key).settings) or None

    def _build(self, spec: ModelSpec) -> ModelHandle:
        factory = self._factories().get(spec.provider)
        if factory is None:
            raise UnknownProviderError(f"nhà cung cấp '{spec.provider}' chưa đăng ký")
        api_key = self._env.get(spec.api_key_env)
        if not api_key:
            raise RuntimeError(f"thiếu biến môi trường {spec.api_key_env}")
        return factory(spec, api_key)
