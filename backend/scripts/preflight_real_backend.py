"""Kiểm tra trước khi tốn token LLM: chạy backend và launcher THẬT trên các image SUT, in phản ứng ở vài độ dài bản ghi.

    uv run python scripts/preflight_real_backend.py            # bug fix head + hai tham chiếu
Kỳ vọng theo số đo nền của tlsfuzzer (xem scripts/run_tlsfuzzer_baseline.py): bản lỗi không cảnh báo khi N > 16640;
bản sửa và bản mới nhất gửi record_overflow rồi đóng.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src")]

from rfcv.backends.docker_launcher import DockerSutLauncher, default_specs  # noqa: E402
from rfcv.backends.tlsfuzzer import TlsfuzzerBackend  # noqa: E402
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal  # noqa: E402

SCENARIO = ScenarioProposal.model_validate(
    {
        "requirement_id": "TLS13-0042",
        "reach_state": "connected",
        "steps": [
            {"op": "complete_handshake"},
            {"op": "send_raw_record", "args": {"length": "$record.length", "encrypted": True}},
            {"op": "expect", "args": {"within_ms": 2000}},
        ],
        "bindings": {"record.length": "from_variant"},
    }
)
LENGTHS = (16, 17, 100, 16401, 16402, 16640, 16641, 17000, 65535)
TARGETS = (
    ("bug", "wolfssl", "0cecccdf6e0504100c78126a558b6cbbcc486247"),
    ("fix", "wolfssl", "c18833f5206e5a96ab7400c569f830903f0c36c5"),
    ("head", "wolfssl", "28bc7540dd420114dc33371e181b5617a4a66611"),
    ("openssl", "openssl", None),
    ("gnutls", "gnutls", None),
)


async def main() -> None:
    only = set(sys.argv[1:])
    backend = TlsfuzzerBackend()
    print(f"{'phiên bản':9} " + " ".join(f"{n:>9}" for n in LENGTHS))
    for label, impl, commit in TARGETS:
        if only and label not in only:
            continue
        launcher = DockerSutLauncher(default_specs(commit))
        cells: list[str] = []
        sanity = "?"
        for n in LENGTHS:
            async with launcher.start(impl, coverage=False, environment=0) as ep:
                if sanity == "?":
                    sanity = "OK" if await backend.sanity(ep) else "SANITY-FAIL"
                tr = await backend.run(SCENARIO, {"record.length": n}, ep, 1)
            if not tr.trigger_reached:
                cells.append("không-gửi")
            else:
                alert = str(tr.observation["alert"])
                cells.append(f"{alert[:8]}{'+X' if tr.observation['closed'] else ''}")
        print(f"{label:9} " + " ".join(f"{c:>9}" for c in cells) + f"   [sanity {sanity}]")


asyncio.run(main())
