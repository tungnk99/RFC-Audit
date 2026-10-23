"""Vòng điều tra với LLM THẬT trên MÃ NGUỒN wolfSSL THẬT (chỉ mục tree-sitter), SUT và backend kiểm thử vẫn GIẢ.

Khác `e2e_live.py` đúng một chỗ: chỉ mục mã là chỉ mục SQLite dựng từ bản sao wolfSSL, nên Code Reader đọc mã thật bằng các
công cụ cấu trúc (danh sách tệp, đại cương, tìm ký hiệu, đọc hàm). KHÔNG có bộ chạy lệnh (không explore/search_text), nên không
có gì chạy trên máy. Phản ứng của SUT vẫn do bộ mô phỏng `rfcv.eval` trả về; vì vậy T3 KHÔNG nói gì về wolfSSL thật, và nhãn
có thể mâu thuẫn giữa T1 (mã thật) với T3 (mô phỏng). Đó là hạn chế đã biết, không phải kết quả đo wolfSSL.

    uv run python -m rfcv.codeindex build --root <bản sao phạm vi src/ wolfssl/> --out runs/wolfssl/index.db
    uv run python scripts/e2e_wolfssl.py faulty|correct [thư mục ra]   (mặc định runs/e2e-wolfssl-<ca>)
    RFCV_WOLFSSL_INDEX=đường/dẫn/index.db để dùng chỉ mục khác
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
from agents.tester.handler import ScenarioHandler  # noqa: E402
from agents.verifier.handler import NoopHandler  # noqa: E402
from rfcv.adapters.manifest import load_manifest  # noqa: E402
from rfcv.codeindex.sqlite_index import SqliteCodeIndex  # noqa: E402
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
from rfcv.eval.demo_providers import NoExec  # noqa: E402
from rfcv.eval.faults import FAMILIES, SimImpl, correct_behaviour, references  # noqa: E402
from rfcv.eval.sim import SimLauncher  # noqa: E402
from rfcv.evidence.artifacts import ArtifactStore  # noqa: E402
from rfcv.evidence.store import EvidenceStore  # noqa: E402
from rfcv.gates.code_gate import build_code_tools  # noqa: E402
from rfcv.gates.explore_policy import CodeScope  # noqa: E402
from rfcv.gates.tool_gateway import ToolGateway  # noqa: E402
from rfcv.plugins import current_registry, use_registry  # noqa: E402
from rfcv.runtime.pydantic_ai import PydanticAIRoleRunner  # noqa: E402


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


async def main(kind: str, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    reg = current_registry()
    manifest = load_manifest(ROOT / "adapters" / "tls13")
    if kind == "faulty":
        impl = next(f for f in FAMILIES if f.name == "wrong_alert").make(0)
    else:
        impl = SimImpl("correct-0", "correct", correct_behaviour)
    refs = references()
    index = SqliteCodeIndex(Path(os.environ.get("RFCV_WOLFSSL_INDEX", ROOT / "runs" / "wolfssl" / "index.db")))

    store = EvidenceStore(outdir / "evidence.db")
    trace = TraceLog(outdir / "trace.db")
    artifacts = ArtifactStore(outdir / "artifacts")
    policy = PolicyStore.load(None, reg, "rfc_protocol")
    llm = LLMGateway.load(ROOT / "config" / "models.yaml", env=dict(os.environ))
    llm.validate()
    assert not llm.uncovered(policy.roles)
    skills = default_registry(ROOT / "skills", manifest.adapter)

    rt = SimpleNamespace(
        run_id="run-wolfssl",
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
        runtime.attach_driver(driver)  # để công cụ tester.run_scenario của Test agent chạy thử trên cùng bộ mô phỏng
        handlers = {
            "LOCATE": LocationHandler(rt, SchemaGate(index, vocabulary_terms(manifest))),
            "SELECT_TESTS": ScenarioHandler(rt, driver),
            "CRITIQUE": NoopHandler(),
        }
        handlers["TRACE_PATHS"] = handlers["RECHECK"] = handlers["LOCATE"]
        runner = PydanticAIRoleRunner(policy, gateway, llm, trace, skills=skills)
        loop = ExecutionLoop(
            run_id="run-wolfssl",
            runner=runner,
            policy=policy,
            store=store,
            trace=trace,
            handlers=handlers,
            budget=RequirementBudget(rounds=8, tool_calls=120, tokens=1_500_000, seconds=900),
        )
        with use_registry(reg):
            verdict = await loop.investigate(inv)
            if os.environ.get("RFCV_EXPLAIN") == "1":  # bước giải thích sau kết luận (Report agent + Output gate)
                explanation = await loop.explain(inv, verdict)
                print("giải thích:", "được Output gate nhận" if explanation else "bị bỏ (xem sự kiện explanation_rejected)")
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
    asyncio.run(main(case, Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "runs" / f"e2e-wolfssl-{case}"))
