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
