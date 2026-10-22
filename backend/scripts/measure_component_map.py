"""Đo MAP_COMPONENTS (Code Indexer) với LLM THẬT trên mã wolfSSL thật (BL-15, CT-18, CI-3, CI-4).

    uv run python scripts/measure_component_map.py --runs 3

Dựng chỉ mục tree-sitter thật cho ba tệp của wolfSSL (src/internal.c, src/tls13.c, src/tls.c trong eval/work/wolfssl),
giao Code Indexer gán 30 hàm vào phân loại thành phần của adapter TLS 1.3, rồi so với nhãn chuẩn bên dưới.

LƯU Ý ĐỘ TIN CẬY: nhãn chuẩn do MỘT người đánh giá (trợ lý AI, dựa vào tên hàm, tệp và kiến thức về wolfSSL), không phải hai
người độc lập, nên đây là số đo sơ bộ về khả năng gán thành phần, không phải độ chính xác đã kiểm chứng. Các hàm được chọn
là những hàm có thành phần rõ ràng; hàm lưng chừng (ví dụ BuildTls13HandshakeHmac) cố ý không đưa vào.
Chạy tách khỏi vòng điều tra: hub chưa cấp `task.scope` (xem CT-18), nên script tự đưa danh sách hàm vào ngữ cảnh.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from rfcv.adapters.manifest import load_manifest  # noqa: E402
from rfcv.codeindex.builder import build_index  # noqa: E402
from rfcv.codeindex.sqlite_index import SqliteCodeIndex  # noqa: E402
from rfcv.core.context_builder import ContextBuilder  # noqa: E402
from rfcv.core.envelope import EnvelopeFactory, MessageKind  # noqa: E402
from rfcv.core.ifc import Labeled, TrustLabel  # noqa: E402
from rfcv.core.llm_gateway import LLMGateway  # noqa: E402
from rfcv.core.policy import PolicyStore  # noqa: E402
from rfcv.core.trace import TraceLog  # noqa: E402
from rfcv.gates.code_gate import build_code_tools  # noqa: E402
from rfcv.gates.explore_policy import CodeScope  # noqa: E402
from rfcv.gates.tool_gateway import ToolGateway, ToolSession  # noqa: E402
from rfcv.plugins import current_registry, use_registry  # noqa: E402
from rfcv.runtime.pydantic_ai import PydanticAIRoleRunner  # noqa: E402

FILES = ("src/internal.c", "src/tls13.c", "src/tls.c")

# Bộ DỄ: tên hàm tự lộ thành phần (TLSX_*, *Alert*, Derive*). Nhãn chuẩn: (tệp, hàm) -> thành phần, một người gán.
EASY: dict[tuple[str, str], str] = {
    # record_layer: đọc/ghi và kiểm tra bản ghi
    ("src/internal.c", "GetRecordHeader"): "record_layer",
    ("src/internal.c", "CheckAvailableSize"): "record_layer",
    ("src/internal.c", "GetSEQIncrement"): "record_layer",
    ("src/internal.c", "SendBuffered"): "record_layer",
    ("src/internal.c", "ProcessReplyEx"): "record_layer",
    ("src/internal.c", "SendData"): "record_layer",
    # handshake: các thông điệp bắt tay TLS 1.3
    ("src/tls13.c", "DoTls13ClientHello"): "handshake",
    ("src/tls13.c", "SendTls13ServerHello"): "handshake",
    ("src/tls13.c", "DoTls13Finished"): "handshake",
    ("src/tls13.c", "SendTls13Finished"): "handshake",
    ("src/tls13.c", "DoTls13Certificate"): "handshake",
    ("src/tls13.c", "SendTls13CertificateVerify"): "handshake",
    ("src/tls13.c", "DoTls13CertificateVerify"): "handshake",
    # key_schedule: dẫn xuất khoá
    ("src/tls13.c", "DeriveTls13Keys"): "key_schedule",
    ("src/tls13.c", "DeriveEarlySecret"): "key_schedule",
    ("src/tls13.c", "DeriveHandshakeSecret"): "key_schedule",
    ("src/tls13.c", "DeriveMasterSecret"): "key_schedule",
    ("src/tls13.c", "Tls13HKDFExpandLabel"): "key_schedule",
    ("src/tls13.c", "DeriveFinishedSecret"): "key_schedule",
    # extensions: tiện ích TLS (TLSX_*)
    ("src/tls.c", "TLSX_Parse"): "extensions",
    ("src/tls.c", "TLSX_SupportedVersions_Parse"): "extensions",
    ("src/tls.c", "TLSX_KeyShare_Parse"): "extensions",
    ("src/tls.c", "TLSX_SNI_Parse"): "extensions",
    ("src/tls.c", "TLSX_PreSharedKey_Parse"): "extensions",
    ("src/tls.c", "TLSX_Cookie_Parse"): "extensions",
    # alerts: gửi, xử lý, ánh xạ cảnh báo
    ("src/internal.c", "SendAlert"): "alerts",
    ("src/internal.c", "SendAlert_ex"): "alerts",
    ("src/internal.c", "SendFatalAlertOnly"): "alerts",
    ("src/internal.c", "DoProcessAlertRecord"): "alerts",
    ("src/internal.c", "TranslateErrorToAlert"): "alerts",
}

# Bộ KHÓ: tên không lộ thành phần. Người gán tự tin ở mức vừa; chỉ chọn hàm có thành phần khá rõ.
HARD: dict[tuple[str, str], str] = {
    ("src/tls.c", "TLS_hmac"): "record_layer",  # MAC của bản ghi
    ("src/tls.c", "TLS_hmac_SetInner"): "record_layer",
    ("src/tls.c", "Hmac_UpdateFinal_CT"): "record_layer",
    ("src/internal.c", "IsEncryptionOn"): "record_layer",
    ("src/tls13.c", "RestartHandshakeHash"): "handshake",  # băm bản ghi bắt tay sau HelloRetryRequest
    ("src/tls13.c", "CreateCookie"): "handshake",
    ("src/tls13.c", "TlsCheckCookie"): "handshake",
    ("src/tls13.c", "wolfSSL_connect_TLSv13"): "handshake",
    ("src/tls13.c", "CreateSigData"): "handshake",  # dữ liệu ký của CertificateVerify
    ("src/tls13.c", "GetMsgHash"): "handshake",
    ("src/tls.c", "ALPN_Select"): "extensions",
    ("src/tls.c", "ALPN_find_match"): "extensions",
    ("src/tls.c", "wolfSSL_CTX_set_groups"): "extensions",  # supported_groups
    ("src/tls.c", "wolfSSL_set_groups"): "extensions",
}

SETS = {"easy": EASY, "hard": HARD}
TRUTH: dict[tuple[str, str], str] = EASY  # bộ đang đo; đặt lại trong main()


class NoExec:
    async def run(self, segments: list[list[str]], timeout_s: float) -> str:
        return ""


def load_dotenv() -> None:
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


def stage_index(wolfssl: Path, work: Path) -> SqliteCodeIndex:
    stage = work / "stage"
    for rel in FILES:
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(wolfssl / rel, dst)
    db = work / "index.db"
    build_index(stage, db)
    return SqliteCodeIndex(db)


def score(entries: list[dict[str, str]], index: SqliteCodeIndex, taxonomy: set[str]) -> dict[str, object]:
    """So bản đồ của agent với nhãn chuẩn, áp đúng hai luật loại bỏ của handler (ngoài phân loại, ký hiệu không có)."""
    accepted: dict[tuple[str, str], str] = {}
    rejected: Counter[str] = Counter()
    for e in entries:
        if e["component"] not in taxonomy:
            rejected["COMPONENT_NOT_IN_TAXONOMY"] += 1
        elif index.symbol_in_file(e["file"], e["symbol"]) is None:
            rejected["SYMBOL_NOT_IN_INDEX"] += 1
        else:
            accepted.setdefault((e["file"], e["symbol"]), e["component"])
    correct = sum(1 for k, v in TRUTH.items() if accepted.get(k) == v)
    missing = [k[1] for k in TRUTH if k not in accepted]
    wrong = {k[1]: (TRUTH[k], accepted[k]) for k in TRUTH if k in accepted and accepted[k] != TRUTH[k]}
    return {
        "correct": correct,
        "of": len(TRUTH),
        "accuracy": round(correct / len(TRUTH), 3),
        "not_mapped": missing,
        "wrong": wrong,
        "rejected_by_handler": dict(rejected),
        "extra_entries": sum(1 for k in accepted if k not in TRUTH),
    }


async def one_run(i: int, index: SqliteCodeIndex, stage: Path, outdir: Path) -> dict[str, object]:
    reg = current_registry()
    manifest = load_manifest(ROOT / "adapters" / "tls13")
    policy = PolicyStore.load(None, reg, "rfc_protocol")
    llm = LLMGateway.load(ROOT / "config" / "models.yaml", env=dict(os.environ))
    llm.validate()
    trace = TraceLog(outdir / f"trace-{i}.db")
    gateway = ToolGateway(policy, trace, reg.tools)
    for spec in build_code_tools(index, NoExec(), CodeScope(stage)):
        gateway.register(spec)
    runner = PydanticAIRoleRunner(policy, gateway, llm, trace)
    available = {
        "adapter.component_taxonomy": Labeled(list(manifest.component_taxonomy), TrustLabel.TRUSTED),
        "adapter.locator_hints": Labeled(
            {k: {kk: list(vv) for kk, vv in v.items()} for k, v in manifest.locator_hints.items()}, TrustLabel.TRUSTED
        ),
        "task.scope": Labeled(sorted(f"{f}:{s}" for f, s in TRUTH), TrustLabel.DERIVED),
    }
    context = ContextBuilder(policy).build("code_indexer", available)
    env = EnvelopeFactory(f"run-map-{i}").make(
        requirement_id="TLS13-0042",
        from_role="execution_loop",
        to_role="code_indexer",
        kind=MessageKind.DISPATCH,
        round=1,
        body={"task_type": "MAP_COMPONENTS", "params": {}},
        budget_left={},
    )
    session = ToolSession(f"run-map-{i}", "code_indexer", "TLS13-0042", max_tool_calls=40)
    started = time.monotonic()
    with use_registry(reg):
        outcome = await runner.run(env, context, session)
    seconds = round(time.monotonic() - started, 1)
    base: dict[str, object] = {"run": i, "seconds": seconds, "tokens": outcome.tokens, "tool_calls": session.tool_calls}
    if outcome.output is None:
        return {**base, "failure": outcome.failure or "NO_OUTPUT"}
    entries = [e.model_dump() for e in outcome.output.entries]  # type: ignore[attr-defined]
    return {**base, "entries": len(entries), **score(entries, index, set(manifest.component_taxonomy))}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wolfssl", type=Path, default=ROOT / "eval" / "work" / "wolfssl")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--set", choices=("easy", "hard"), default="easy", help="bộ hàm cần gán (xem EASY và HARD)")
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "component-map")
    args = ap.parse_args()
    load_dotenv()
    global TRUTH
    TRUTH = SETS[args.set]
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        index = stage_index(args.wolfssl, work)
        missing = [k for k in TRUTH if index.symbol_in_file(*k) is None]
        if missing:
            sys.exit(f"nhãn chuẩn trỏ vào hàm không có trong chỉ mục (sai commit wolfSSL?): {missing}")
        results = [await one_run(i, index, work / "stage", args.out) for i in range(1, args.runs + 1)]
        close = getattr(index, "close", None)
        if callable(close):
            close()
    per_component: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in results:
        wrong = r.get("wrong", {})
        for (_, sym), truth in TRUTH.items():
            if "failure" in r:
                continue
            per_component[truth][1] += 1
            if sym not in r.get("not_mapped", []) and sym not in wrong:  # type: ignore[operator]
                per_component[truth][0] += 1
    print(json.dumps({"runs": results}, ensure_ascii=False, indent=1))
    print("\nTheo thành phần (đúng / tổng qua các lần chạy):")
    for comp, (ok, total) in sorted(per_component.items()):
        print(f"  {comp:<14} {ok}/{total}")


if __name__ == "__main__":
    asyncio.run(main())
