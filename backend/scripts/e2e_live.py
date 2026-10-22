"""Phép thử đầu-cuối với LLM THẬT, để đo lại sau mỗi lần cải thiện (xem docs/management/theo_doi_cai_thien.md).

Chạy cả vòng điều tra thật: Planner, Code Reader, Test, Verifier dùng mô hình trong config/models.yaml.
Phần giả: SUT và backend kiểm thử (bộ mô phỏng rfcv.eval), và chỉ mục mã (một tệp C nhỏ trong bộ nhớ, nhất quán với lỗi
gieo sẵn). Nên kết quả cho thấy cơ chế phối hợp, KHÔNG cho thấy độ chính xác trên mã wolfSSL thật.

    uv run python scripts/e2e_live.py faulty            # bản gửi sai cảnh báo: kỳ vọng VIOLATION (V2)
    uv run python scripts/e2e_live.py correct           # bản đúng: kỳ vọng COMPLIANT (V5, LINKED)
    uv run python scripts/e2e_live.py faulty runs/x     # chọn thư mục ra (mặc định runs/e2e-<ca>)

Khoá API đọc từ môi trường; nếu có tệp .env ở gốc repo thì nạp biến chưa đặt (không in giá trị).
Xem kết quả bằng `uv run rfcv trace runs/e2e-faulty` và `uv run python scripts/analyze_run.py runs/e2e-faulty`.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agents.code_reader.handler import LocationHandler  # noqa: E402
from agents.test.handler import ScenarioHandler  # noqa: E402
from agents.verifier.handler import NoopHandler  # noqa: E402
from rfcv.adapters.manifest import load_manifest  # noqa: E402
from rfcv.core.budget import RequirementBudget  # noqa: E402
from rfcv.core.execution_loop import ExecutionLoop  # noqa: E402
from rfcv.core.llm_gateway import LLMGateway  # noqa: E402
from rfcv.core.policy import PolicyStore  # noqa: E402
from rfcv.core.skills import default_registry  # noqa: E402
from rfcv.core.trace import TraceLog  # noqa: E402
from rfcv.domains.rfc_protocol.adapter_view import vocabulary_terms  # noqa: E402
from rfcv.domains.rfc_protocol.runtime import ProtocolRuntime  # noqa: E402
from rfcv.domains.rfc_protocol.sandbox.driver import TestDriver  # noqa: E402
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate  # noqa: E402
from rfcv.eval.coord_world import CoordBackend  # noqa: E402
from rfcv.eval.faults import FAMILIES, SimImpl, correct_behaviour, references  # noqa: E402
from rfcv.eval.sim import SimLauncher  # noqa: E402
from rfcv.evidence.artifacts import ArtifactStore  # noqa: E402
from rfcv.evidence.store import EvidenceStore  # noqa: E402
from rfcv.gates.code_gate import InMemoryCodeIndex, SymbolInfo, build_code_tools  # noqa: E402
from rfcv.gates.explore_policy import CodeScope  # noqa: E402
from rfcv.gates.tool_gateway import ToolGateway  # noqa: E402
from rfcv.plugins import current_registry, use_registry  # noqa: E402
from rfcv.runtime.pydantic_ai import PydanticAIRoleRunner  # noqa: E402

FILE = "src/internal.c"


def load_dotenv() -> None:
    """Nạp .env ở gốc repo cho biến chưa đặt. Không in giá trị."""
    env = ROOT / ".env"
    if not env.is_file():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ.setdefault(key.strip(), value)


def code_index(alert: str) -> InMemoryCodeIndex:
    """Một tệp C nhỏ: macro ngưỡng ở dòng 20-21, kiểm tra độ dài ở 812, phản ứng ở 815 (khớp dữ liệu độ phủ của mô phỏng)."""
    src = [f"/* line {i} */" for i in range(1, 900)]

    def put(n: int, text: str) -> None:
        src[n - 1] = text

    put(20, "#define MAX_RECORD_SIZE 16384")
    put(21, "#define MAX_MSG_EXTRA   256   /* MAC + padding + AEAD expansion */")
    put(350, "        ret = GetRecordHeader(ssl, &size);")
    put(800, "static int GetRecordHeader(WOLFSSL* ssl, word32* size)")
    put(801, "{")
    put(810, "    /* read the 5-byte record header */")
    put(811, "    GetRecordLength(ssl, size);")
    put(812, "    if (*size > MAX_RECORD_SIZE + MAX_MSG_EXTRA) {")
    put(813, '        WOLFSSL_MSG("record too long");')
    put(814, "        /* reject over-long record */")
    put(815, f"        SendAlert(ssl, alert_fatal, {alert});")
    put(816, "        return LENGTH_ERROR;")
    put(817, "    }")
    put(830, "}")
    sig = "static int GetRecordHeader(WOLFSSL* ssl, word32* size)"
    return InMemoryCodeIndex(
        sources={FILE: src},
        symbols=[
            SymbolInfo(FILE, "GetRecordHeader", "function", 800, 830, sig),
            SymbolInfo(FILE, "ProcessReply", "function", 300, 420, "int ProcessReply(WOLFSSL* ssl)"),
            SymbolInfo(FILE, "MAX_RECORD_SIZE", "macro", 20, 20, "#define MAX_RECORD_SIZE 16384"),
            SymbolInfo(FILE, "MAX_MSG_EXTRA", "macro", 21, 21, "#define MAX_MSG_EXTRA 256"),
        ],
        calls={("ProcessReply", "GetRecordHeader")},
    )


class NoExec:
    async def run(self, segments: list[list[str]], timeout_s: float) -> str:
        return ""


async def main(kind: str, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    reg = current_registry()
    manifest = load_manifest(ROOT / "adapters" / "tls13")
    if kind == "faulty":
        impl = next(f for f in FAMILIES if f.name == "wrong_alert").make(0)
        alert = "handshake_failure"
    else:
        impl = SimImpl("correct-0", "correct", correct_behaviour)
        alert = "record_overflow"
    refs = references()
    index = code_index(alert)

    store = EvidenceStore(outdir / "evidence.db")
    trace = TraceLog(outdir / "trace.db")
    artifacts = ArtifactStore(outdir / "artifacts")
    policy = PolicyStore.load(None, reg, "rfc_protocol")
    llm = LLMGateway.load(ROOT / "config" / "models.yaml", env=dict(os.environ))
    llm.validate()
    assert not llm.uncovered(policy.roles)
    skills = default_registry(ROOT / "skills", manifest.adapter)

    rt = SimpleNamespace(
        run_id="run-live",
        manifest=manifest,
        trace=trace,
        store=store,
        artifacts=artifacts,
        seed=7,
        providers=SimpleNamespace(code_index=index),
    )
    runtime = ProtocolRuntime()
    gateway = ToolGateway(policy, trace, reg.tools)
    with tempfile.TemporaryDirectory() as tmp:
        for spec in build_code_tools(index, NoExec(), CodeScope(Path(tmp))):
            gateway.register(spec)
        for spec in runtime.tools(rt):
            gateway.register(spec)
        inv = runtime.investigations(rt, ROOT / "adapters" / "tls13" / "examples")[0]
        driver = TestDriver(
            CoordBackend([impl, *refs]),
            SimLauncher(),
            store,
            artifacts,
            trace,
            sut_impl=impl.name,
            references=[r.name for r in refs],
        )
        handlers = {
            "LOCATE": LocationHandler(rt, SchemaGate(index, vocabulary_terms(manifest))),
            "SELECT_TESTS": ScenarioHandler(rt, driver),
            "CRITIQUE": NoopHandler(),
        }
        handlers["TRACE_PATHS"] = handlers["RECHECK"] = handlers["LOCATE"]
        runner = PydanticAIRoleRunner(policy, gateway, llm, trace, skills=skills)
        loop = ExecutionLoop(
            run_id="run-live",
            runner=runner,
            policy=policy,
            store=store,
            trace=trace,
            handlers=handlers,
            budget=RequirementBudget(rounds=8, tool_calls=120, tokens=1_500_000, seconds=900),
        )
        with use_registry(reg):
            verdict = await loop.investigate(inv)
    print(f"\n##### KẾT QUẢ ({kind}, impl={impl.name}) #####")
    print("nhãn:", verdict.label.value, "| quy tắc:", verdict.rule, "| dừng:", verdict.stop_reason.value)
    print("assurance:", verdict.assurance, "| chuỗi hash bằng chứng:", "OK" if store.verify_chain().ok else "HỎNG")
    print(f"trace: {outdir}  (xem: rfcv trace {outdir} | python scripts/analyze_run.py {outdir})")
    store.close()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("faulty", "correct"):
        sys.exit(__doc__)
    load_dotenv()
    case = sys.argv[1]
    asyncio.run(main(case, Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "runs" / f"e2e-{case}"))
