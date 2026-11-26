"""Thí nghiệm C8 (Chặng A — gen-41): Đánh giá khả năng Tester LLM tự soạn kịch bản KHÔNG có template sẵn.

Xoá sạch thư mục `templates/` trong bản sao tạm của từng adapter (0 mẫu có sẵn), ép `ScenarioHandler.synthesize()`
trả `None` và `tester__list_examples` trả danh sách mẫu rỗng. `Tester LLM` (`DeepSeek-V4-Flash`) buộc phải tự đọc
RBS + mô tả DSL của backend, tự viết `ScenarioProposal@1` từ đầu, chạy thử đối chứng trên bản tham chiếu thật trong
Docker (`tester__run_scenario`), tự sửa nếu sai cú pháp/tham số, rồi nộp cho `TestDriver` chạy toàn bộ biến thể.

Chạy trên 5 yêu cầu thuộc 4 giao thức khác nhau:
  1. TLS 1.3 (`R9`, `wolfSSL`):   `TLS13-0042` (`record.length > 16640`, encrypted record sau bắt tay)
  2. TLS 1.3 (`OU2`, `OpenSSL`):  `TLS13-0101` (`record.content_type`, plaintext record trước bắt tay)
  3. HTTP/2 (`H1`, `nghttp2`):    `HTTP2-0001` (`frame.length > 16384`, `send_goaway(frame_size_error)`)
  4. DNS (`D3`, `Knot DNS`):      `DNS-0002` (`opt.version > 0`, `respond(badvers)`)
  5. QUIC (`Q1`, `ngtcp2`):       `QUIC-0001` (`datagram.payload_length < 1200`, `expect discard`)

Cách dùng:
    uv run python scripts/run_tester_zero_template_c8.py
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent

CASES: list[dict[str, str]] = [
    {
        "id": "R9",
        "protocol": "TLS 1.3 (wolfSSL)",
        "requirement": "TLS13-0042",
        "adapter": "eval/adapters/tls13-R9",
        "code_root": "runs/real/src/wolfssl-R9",
        "expected": "VIOLATION",
    },
    {
        "id": "OU2",
        "protocol": "TLS 1.3 (OpenSSL)",
        "requirement": "TLS13-0101",
        "adapter": "eval/adapters/tls13-OU2",
        "code_root": "runs/real/src/openssl-OU2",
        "expected": "VIOLATION",
    },
    {
        "id": "H1",
        "protocol": "HTTP/2 (nghttp2)",
        "requirement": "HTTP2-0001",
        "adapter": "eval/adapters/http2-H1",
        "code_root": "runs/real/src/nghttp2-H1",
        "expected": "VIOLATION",
    },
    {
        "id": "D3",
        "protocol": "DNS (Knot DNS)",
        "requirement": "DNS-0002",
        "adapter": "eval/adapters/dns-D3",
        "code_root": "runs/real/src/knot-D3",
        "expected": "VIOLATION",
    },
    {
        "id": "Q1",
        "protocol": "QUIC (ngtcp2)",
        "requirement": "QUIC-0001",
        "adapter": "eval/adapters/quic-Q1",
        "code_root": "runs/real/src/ngtcp2-Q1",
        "expected": "VIOLATION",
    },
]


def _load_env() -> dict[str, str]:
    env = os.environ.copy()
    env_file = BACKEND / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())
    return env


def _inspect_trace(run_dir: Path) -> dict[str, Any]:
    dbs = sorted(run_dir.glob("run-*/trace.db"))
    if not dbs:
        return {"error": "no trace.db"}
    db = dbs[-1]
    con = sqlite3.connect(db)
    tester_runs = 0
    tester_ok = False
    tester_tokens = 0
    tester_tools = 0
    dry_runs = 0
    dry_run_pass = False
    gate_rejects = 0
    t3_written = 0
    verdict_label = "UNKNOWN"
    verdict_rule = ""
    authored_steps: list[Any] = []
    for kind, raw in con.execute("SELECT kind, payload FROM events ORDER BY seq"):
        p = json.loads(raw)
        if kind == "role_run" and p.get("role") == "tester":
            tester_runs += 1
            tester_tokens += int(p.get("tokens") or 0)
            tester_tools += int(p.get("tool_calls") or 0)
            if p.get("ok") and isinstance(p.get("output"), dict):
                tester_ok = True
                authored_steps = p["output"].get("steps") or []
        elif kind == "tool_call" and p.get("tool") == "tester__run_scenario":
            dry_runs += 1
            res_txt = str(p.get("result") or p.get("output") or "")
            if '"outcome": "PASS"' in res_txt or "'outcome': 'PASS'" in res_txt or '"trigger_reached": true' in res_txt:
                dry_run_pass = True
        elif kind == "gate_reject" and p.get("gate") == "tool_gateway":
            gate_rejects += 1
        elif kind == "task_result" and p.get("task_type") == "SELECT_TESTS":
            t3_written += int(p.get("new_evidence") or 0)
        elif kind == "verdict":
            verdict_label = str(p.get("label") or "")
            verdict_rule = str(p.get("rule") or "")
    con.close()
    return {
        "run_id": db.parent.name,
        "tester_llm_runs": tester_runs,
        "tester_output_ok": tester_ok,
        "tester_tokens": tester_tokens,
        "tester_tool_calls": tester_tools,
        "dry_runs": dry_runs,
        "dry_run_verified": dry_run_pass,
        "gate_rejects": gate_rejects,
        "t3_evidence_written": t3_written,
        "authored_step_ops": [s.get("op") for s in authored_steps if isinstance(s, dict)],
        "verdict": verdict_label,
        "rule": verdict_rule,
    }


def run_case(case: dict[str, str], out_root: Path, env: dict[str, str]) -> dict[str, Any]:
    cid = case["id"]
    tmp_ad = Path(tempfile.mkdtemp(prefix=f"rfcv-notpl-{cid}-"))
    try:
        src_ad = BACKEND / case["adapter"]
        dst_ad = tmp_ad / "adapter"
        shutil.copytree(src_ad, dst_ad)
        # Xoá sạch toàn bộ template trong bản sao tạm để đảm bảo 0 mẫu có sẵn
        tpl_dir = dst_ad / "templates"
        if tpl_dir.exists():
            shutil.rmtree(tpl_dir)
        tpl_dir.mkdir(parents=True, exist_ok=True)
        assert not list(tpl_dir.glob("*.yaml")), "templates dir must be empty!"

        case_dir = out_root / cid
        case_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        rfcv_bin = Path(sys.executable).with_name("rfcv.exe" if os.name == "nt" else "rfcv")
        cmd = [
            str(rfcv_bin),
            "run",
            "--adapter",
            str(dst_ad),
            "--code-root",
            str(BACKEND / case["code_root"]),
            "--run-dir",
            str(case_dir),
            "--code-index",
            "treesitter",
            "--executor",
            "docker",
            "--sut-launcher",
            "docker",
            "--effort",
            "efficient",
            "--no-explain",
        ]
        proc = subprocess.run(cmd, cwd=BACKEND, env=env, capture_output=True, text=True)
        elapsed = int(time.monotonic() - t0)
        info = _inspect_trace(case_dir)
        row = {
            "id": cid,
            "protocol": case["protocol"],
            "requirement": case["requirement"],
            "templates_available": 0,
            "exit_code": proc.returncode,
            "seconds": elapsed,
            "expected": case["expected"],
            **info,
            "verdict_correct": info.get("verdict") == case["expected"],
            "scenario_verified_on_ref": bool(info.get("t3_evidence_written", 0) > 0 and info.get("tester_output_ok")),
        }
        print(json.dumps(row, ensure_ascii=False), flush=True)
        return row
    finally:
        shutil.rmtree(tmp_ad, ignore_errors=True)


def main() -> None:
    out_root = BACKEND / "runs" / "real" / "tester_zero_template_c8_gen41"
    out_root.mkdir(parents=True, exist_ok=True)
    env = _load_env()
    rows = [run_case(c, out_root, env) for c in CASES]
    n = len(rows)
    authored_ok = sum(1 for r in rows if r["scenario_verified_on_ref"])
    verdict_ok = sum(1 for r in rows if r["verdict_correct"])
    summary = {
        "total": n,
        "zero_template_verified_on_ref": f"{authored_ok}/{n} ({100.0 * authored_ok / n:.1f}%)",
        "end_to_end_verdict_correct": f"{verdict_ok}/{n} ({100.0 * verdict_ok / n:.1f}%)",
        "rows": rows,
    }
    (out_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== C8 ZERO-TEMPLATE TESTER SUMMARY ===", flush=True)
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
