"""Nhà cung cấp mô hình của runtime PydanticAI: Anthropic và mọi endpoint tương thích OpenAI."""

from __future__ import annotations

from typing import Any

from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from rfcv.core.llm_gateway import ModelSpec


def anthropic_factory(spec: ModelSpec, api_key: str) -> Any:
    return AnthropicModel(spec.model, provider=AnthropicProvider(api_key=api_key, base_url=spec.base_url))


def openai_compatible_factory(spec: ModelSpec, api_key: str) -> Any:
    return OpenAIChatModel(spec.model, provider=OpenAIProvider(base_url=spec.base_url, api_key=api_key))
