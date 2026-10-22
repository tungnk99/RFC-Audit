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
from agents.tester.handler import ScenarioHandler  # noqa: E402
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
from rfcv.eval.demo_providers import NoExec, code_index  # noqa: E402
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
        runtime.attach_driver(driver)  # để công cụ tester.run_scenario của Test agent chạy thử trên cùng bộ mô phỏng
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
    asyncio.run(main(case, Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "runs" / f"e2e-{case}"))
