"""Thành phần có sẵn của rfcv, đăng ký bằng đúng API công khai của Registry (cùng cách plugin bên thứ ba dùng).

Plugin bên thứ ba khai báo ở nhóm entry point `rfcv.*` trong pyproject.toml của chúng; thành phần có sẵn không cần
cài gói mới chạy được, nên đăng ký trực tiếp ở đây.
"""

from __future__ import annotations

from typing import Any

from rfcv.plugins import Registry


def _tlsfuzzer(manifest: Any, config: Any) -> Any:
    from rfcv.backends.tlsfuzzer import TlsfuzzerBackend

    return TlsfuzzerBackend()


def register_builtin(reg: Registry) -> None:
    from rfcv.domains.rfc_protocol import pack
    from rfcv.gates.code_gate import CODE_TOOL_DESCRIPTORS
    from rfcv.runtime.pydantic_ai import anthropic_factory, create_runner, openai_compatible_factory

    for tool in CODE_TOOL_DESCRIPTORS:  # code pack dùng chung cho mọi miền đọc mã
        reg.register_tool(tool)
    reg.register_domain(pack())
    reg.register_backend("tlsfuzzer", _tlsfuzzer)
    reg.register_llm_provider("anthropic", anthropic_factory)
    reg.register_llm_provider("openai_compatible", openai_compatible_factory)
    reg.register_agent_runtime("pydantic_ai", create_runner)
