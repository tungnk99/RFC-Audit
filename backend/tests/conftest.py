from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic_ai import models

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT.parent / "docs"  # tài liệu dùng chung nằm ở gốc repo, ngoài backend/
sys.path.insert(0, str(Path(__file__).parent))

# Kiểm thử không bao giờ gọi LLM thật.
models.ALLOW_MODEL_REQUESTS = False

from rfcv.adapters.manifest import AdapterManifest, load_manifest  # noqa: E402
from rfcv.core.policy import PolicyStore  # noqa: E402
from rfcv.core.trace import TraceLog  # noqa: E402
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary  # noqa: E402
from rfcv.domains.rfc_protocol.spec.oracle_compiler import CompiledOracle, compile_oracle  # noqa: E402
from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs  # noqa: E402
from rfcv.evidence.store import EvidenceStore  # noqa: E402
from rfcv.plugins import Registry, current_registry  # noqa: E402

ADAPTER_DIR = ROOT / "adapters" / "tls13"
AGENTS_DIR = ROOT / "agents"


@pytest.fixture(scope="session")
def registry() -> Registry:
    return current_registry()


@pytest.fixture
def store(tmp_path: Path) -> Iterator[EvidenceStore]:
    s = EvidenceStore(tmp_path / "evidence.db")
    yield s
    s.close()


@pytest.fixture
def trace(tmp_path: Path) -> TraceLog:
    return TraceLog(tmp_path / "trace.db")


@pytest.fixture(scope="session")
def manifest() -> AdapterManifest:
    return load_manifest(ADAPTER_DIR)


@pytest.fixture(scope="session")
def oracle(manifest: AdapterManifest) -> CompiledOracle:
    rbs = parse_rbs((ADAPTER_DIR / "examples" / "TLS13-0042.rbs").read_text(encoding="utf-8"))
    return compile_oracle(rbs, to_vocabulary(manifest))


@pytest.fixture(scope="session")
def policy(registry: Registry) -> PolicyStore:
    return PolicyStore.load(None, registry)


@pytest.fixture(autouse=True)
def _no_environment_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Thử lại ca lỗi hạ tầng không được làm chậm bộ test."""
    from rfcv.domains.rfc_protocol.sandbox import driver

    monkeypatch.setattr(driver, "ENVIRONMENT_RETRY_DELAY_S", 0.0)


LEGACY_CODE_TOOLS = (
    "code.list_dir",
    "code.file_outline",
    "code.search_symbol",
    "code.read_function",
    "code.read_range",
    "code.get_definition",
    "code.find_references",
    "code.callees",
    "code.search_text",
    "code.explore",
)


@pytest.fixture(scope="session")
def legacy_policy(registry: Registry) -> PolicyStore:
    """Chính sách mà Code Reader còn được dùng 10 công cụ cũ (đã thay bằng grep/glob/read/eval ở role.yaml). Chỉ cho test
    của chính các công cụ cũ, đến khi chúng bị gỡ."""
    base = PolicyStore.load(None, registry)
    profiles = [base.profile(r) for r in base.roles]
    profiles = [
        p.model_copy(update={"tools": (*p.tools, *LEGACY_CODE_TOOLS)}) if p.role == "code_reader" else p
        for p in profiles
    ]
    paths = {r: base.prompt_path(r) for r in base.roles} if hasattr(base, "prompt_path") else None
    return PolicyStore(profiles, registry.schemas, registry.tools, registry.domain().required_roles, paths)
