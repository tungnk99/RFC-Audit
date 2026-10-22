"""Thành phần có sẵn của rfcv, đăng ký bằng đúng API công khai của Registry (cùng cách plugin bên thứ ba dùng).

Plugin bên thứ ba khai báo ở nhóm entry point `rfcv.*` trong pyproject.toml của chúng; thành phần có sẵn không cần
cài gói mới chạy được, nên đăng ký trực tiếp ở đây.
"""

from __future__ import annotations

from typing import Any

from rfcv.plugins import Registry


def _backend(module: str, cls: str) -> Any:
    """Nhập muộn: chỉ nạp mô-đun backend khi adapter chọn nó."""

    def factory(manifest: Any, config: Any) -> Any:
        import importlib

        return getattr(importlib.import_module(f"rfcv.backends.{module}"), cls)()

    return factory


# tên backend (giá trị trường `backend` trong adapter.yaml) → (mô-đun trong rfcv.backends, lớp).
BACKENDS = {
    "tlsfuzzer": ("tlsfuzzer", "TlsfuzzerBackend"),
    "dnspython": ("dns", "DnspythonBackend"),
    "h2spec": ("http2", "H2specBackend"),
    "aioquic": ("quic", "AioquicBackend"),
    "asyncssh": ("ssh", "AsyncsshBackend"),
}


def _codeindex(name: str) -> Any:
    """Nhập muộn: chỉ khi cấu hình chọn mới nạp gói chỉ mục và bộ chạy lệnh."""

    def factory(manifest: Any, config: Any) -> Any:
        from rfcv.codeindex import providers

        return getattr(providers, name)(manifest, config)

    return factory


def register_builtin(reg: Registry) -> None:
    from rfcv.domains.rfc_protocol import pack
    from rfcv.gates.code_gate import CODE_TOOL_DESCRIPTORS
    from rfcv.runtime.pydantic_ai import anthropic_factory, create_runner, openai_compatible_factory

    for tool in CODE_TOOL_DESCRIPTORS:  # code pack dùng chung cho mọi miền đọc mã
        reg.register_tool(tool)
    reg.register_domain(pack())
    for name, (module, cls) in BACKENDS.items():
        reg.register_backend(name, _backend(module, cls))
    reg.register_code_index("treesitter", _codeindex("treesitter_sandboxed"))
    reg.register_code_index("treesitter-local", _codeindex("treesitter_local"))
    reg.register_executor("docker", _codeindex("docker_executor"))
    reg.register_executor("local-unsandboxed", _codeindex("local_executor"))
    reg.register_llm_provider("anthropic", anthropic_factory)
    reg.register_llm_provider("openai_compatible", openai_compatible_factory)
    reg.register_agent_runtime("pydantic_ai", create_runner)
