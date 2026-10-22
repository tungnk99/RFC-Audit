"""Chấm khía cạnh REACTION của Code Reader trên các lần chạy `e2e_hard.py` (BL-41).

Mỗi thư mục lần chạy có tên dạng `<ca>-<số>` hoặc chứa tên ca (`hard-correct`, `hard-wrong-alert`, `hard-no-close`). Với mỗi lần:
mọi T1 ghi trong lần chạy có khía cạnh REACTION; đúng khi giá trị (MATCH hay MISMATCH) trùng đáp án của ca và, với ca sai cảnh báo,
`observed` đúng là `send_alert(handshake_failure)`. In từng lần và tổng: recall REACTION, nhãn cuối đúng, token Code Reader.

    python scripts/measure_reaction.py runs/hard-base/*
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from rfcv.core.trace import TraceLog  # noqa: E402
from rfcv.eval.hard_world import WORLDS  # noqa: E402
from rfcv.evidence.store import EvidenceStore  # noqa: E402


def case_of(run_dir: Path) -> str:
    for name in sorted(WORLDS, key=len, reverse=True):
        if name in run_dir.name:
            return name
    raise SystemExit(f"không nhận ra ca từ tên thư mục: {run_dir.name}")


def score(run_dir: Path) -> dict[str, object]:
    world = WORLDS[case_of(run_dir)]  # type: ignore[index]
    store = EvidenceStore(run_dir / "evidence.db")
    reactions: list[tuple[str, str]] = []
    for e in store.for_requirement("TLS13-0042"):
        if str(e.tier) == "T1":
            for a in e.payload.aspects:  # type: ignore[attr-defined]
                if str(a.aspect) == "REACTION":
                    reactions.append((str(a.value), str(a.observed)))
    store.close()
    verdict: dict[str, object] = {}
    tokens = 0
    for ev in TraceLog(run_dir / "trace.db").events():
        if ev["kind"] == "verdict":
            verdict = ev["payload"]
        if ev["kind"] == "role_run" and ev["payload"].get("role") == "code_reader":
            tokens += int(ev["payload"].get("tokens", 0))

    def right(value: str, observed: str) -> bool:
        if value != world.expected_reaction:
            return False
        return world.case != "hard-wrong-alert" or observed == "send_alert(handshake_failure)"

    return {
        "case": world.case,
        "t1": len(reactions),
        "reaction_correct": sum(right(v, o) for v, o in reactions),
        "values": [f"{v}:{o}" for v, o in reactions],
        "label": verdict.get("label"),
        "label_ok": verdict.get("label") == world.expected_label,
        "code_reader_tokens": tokens,
    }


if __name__ == "__main__":
    rows = [score(Path(a)) for a in sys.argv[1:]]
    for r in rows:
        print(
            f"{r['case']:<17} T1={r['t1']} REACTION đúng {r['reaction_correct']}/{r['t1']} nhãn={r['label']} "
            f"({'đúng' if r['label_ok'] else 'SAI'}) token CR={r['code_reader_tokens']}  {r['values']}"
        )
    if rows:
        t1 = sum(int(r["t1"]) for r in rows)  # type: ignore[call-overload]
        ok = sum(int(r["reaction_correct"]) for r in rows)  # type: ignore[call-overload]
        labels = sum(1 for r in rows if r["label_ok"])
        tok = sum(int(r["code_reader_tokens"]) for r in rows) // len(rows)  # type: ignore[call-overload]
        print(
            f"\nTỔNG {len(rows)} lần: recall REACTION {ok}/{t1}, nhãn đúng {labels}/{len(rows)}, token Code Reader trung bình {tok}"
        )
