r"""Automated Evaluator (kiểu Karpathy autoresearch / AlphaEvolve) cho các nhánh nghiên cứu RFC-Audit.

Chạy một lệnh duy nhất để chấm điểm khách quan mọi biến thể kiến trúc theo vector chỉ số chuẩn (KHÔNG có fallback bịa điểm):
  - ci_pass: ruff + pyright + lint-imports + pytest (core + ACI + Stage 2 suites)
  - adversarial_safe: chạy riêng bộ test bất biến IFC / chống rò rỉ (`test_invariants`, `test_policy_ifc`, `test_leak_scan`)
  - verdict_acc & false_compliant: chạy thật `rfcv.eval.sim.run_benchmark` trên adapter `tls13` (ghi rõ `sim_total`)
  - git_dirty: ghi nhận rõ cây làm việc sạch hay chưa commit để đảm bảo khả năng tái lập chính xác.

Dùng:
  cd backend && .\.venv\Scripts\python.exe scripts/eval_score.py --label stage3-hardened
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS_TSV = ROOT / "eval" / "results.tsv"
TSV_HEADER = (
    "timestamp\tbranch\tcommit\tdirty\tlabel\tci_pass\tpytest_passed\truff_ok\tpyright_ok\t"
    "import_linter_ok\tsim_total\tverdict_acc\tfalse_compliant\tadversarial_safe\tduration_s\n"
)


def _run(cmd: list[str], cwd: Path = ROOT) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()


def _git_info() -> tuple[str, str, bool]:
    _, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT.parent)
    _, sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT.parent)
    _, status = _run(["git", "status", "--porcelain"], cwd=ROOT.parent)
    return branch.strip() or "unknown", sha.strip() or "unknown", bool(status.strip())


def _venv_tool(name: str) -> str:
    scripts = Path(sys.executable).parent
    for cand in (scripts / f"{name}.exe", scripts / name):
        if cand.is_file():
            return str(cand)
    return name


def _parse_pytest_passed(output: str) -> int:
    parts = output.split()
    for idx, tok in enumerate(parts):
        if tok.startswith("passed") and idx > 0 and parts[idx - 1].isdigit():
            return int(parts[idx - 1])
    return 0


def _run_ci_gates() -> dict[str, Any]:
    ruff_rc, ruff_out = _run([_venv_tool("ruff"), "check", "src", "tests", "agents"])
    pyright_rc, pyright_out = _run([_venv_tool("pyright"), "--pythonpath", sys.executable])
    il_rc, il_out = _run([_venv_tool("lint-imports")])
    test_targets = [
        "tests/test_agent_aci_runtime.py",
        "tests/test_best_of_k.py",
        "tests/test_divergence_verifier.py",
        "tests/test_fleet_reflexion.py",
        "tests/test_stage2_wiring.py",
        "tests/test_agent_runtime.py",
        "tests/test_skills.py",
        "tests/test_summary_fold.py",
        "tests/test_gates.py",
        "tests/test_verdict_engine.py",
        "tests/test_execution_loop.py",
        "tests/test_hard_world.py",
        "tests/test_prompts_truthful.py",
        "tests/test_contracts.py",
        "tests/test_coordination_contracts.py",
    ]
    missing = [t for t in test_targets if not (ROOT / t).is_file()]
    if missing:
        raise FileNotFoundError(f"Thiếu tệp kiểm thử bắt buộc: {missing}")
    pt_rc, pt_out = _run([_venv_tool("pytest"), "-q", *test_targets])

    # Chạy riêng bộ kiểm tra an toàn đối kháng / IFC / chống rò rỉ.
    adv_targets = ["tests/test_invariants.py", "tests/test_policy_ifc.py", "tests/test_leak_scan.py"]
    adv_rc, adv_out = _run([_venv_tool("pytest"), "-q", *adv_targets])

    passed_count = _parse_pytest_passed(pt_out) + _parse_pytest_passed(adv_out)
    all_tests_ok = pt_rc == 0 and adv_rc == 0
    return {
        "ruff_ok": ruff_rc == 0,
        "pyright_ok": pyright_rc == 0,
        "import_linter_ok": il_rc == 0,
        "pytest_ok": all_tests_ok,
        "adversarial_safe": adv_rc == 0,
        "pytest_passed": passed_count,
        "ci_pass": ruff_rc == 0 and pyright_rc == 0 and il_rc == 0 and all_tests_ok,
        "details": {
            "ruff": "" if ruff_rc == 0 else ruff_out[-600:],
            "pyright": "" if pyright_rc == 0 else pyright_out[-600:],
            "lint_imports": "" if il_rc == 0 else il_out[-600:],
            "pytest": "" if pt_rc == 0 else pt_out[-800:],
            "adversarial": "" if adv_rc == 0 else adv_out[-800:],
        },
    }


def _run_sim_benchmark(seeds: int = 2) -> dict[str, Any]:
    """Chạy thật `rfcv.eval.sim.run_benchmark` trên adapter tls13 (không nuốt lỗi, không bịa điểm)."""
    from rfcv.eval.sim import run_benchmark

    report = run_benchmark(ROOT / "adapters" / "tls13", seeds=seeds)
    cells = report.cells
    total = len(cells)
    false_compliant = sum(1 for c in cells if c.kind == "faulty" and c.label == "COMPLIANT")
    # Đếm số ca đúng chiều: correct/alt_valid phải COMPLIANT; faulty phải VIOLATION (hoặc không COMPLIANT nếu ngoài trần quét).
    correct = sum(
        1
        for c in cells
        if (c.kind in ("correct", "alt_valid") and c.label == "COMPLIANT")
        or (c.kind == "faulty" and (c.label == "VIOLATION" or (not c.scan_deviates and c.label != "COMPLIANT")))
    )
    acc = round(correct / total, 4) if total > 0 else 0.0
    return {"verdict_acc": acc, "false_compliant": false_compliant, "sim_total": total}


def _append_tsv(row: dict[str, Any]) -> None:
    RESULTS_TSV.parent.mkdir(parents=True, exist_ok=True)
    if not RESULTS_TSV.exists() or RESULTS_TSV.read_text(encoding="utf-8").splitlines()[0] != TSV_HEADER.strip():
        RESULTS_TSV.write_text(TSV_HEADER, encoding="utf-8")
    line = (
        f"{row['timestamp']}\t{row['branch']}\t{row['commit']}\t{int(row['dirty'])}\t{row['label']}\t"
        f"{int(row['ci_pass'])}\t{row['pytest_passed']}\t{int(row['ruff_ok'])}\t"
        f"{int(row['pyright_ok'])}\t{int(row['import_linter_ok'])}\t{row['sim_total']}\t"
        f"{row['verdict_acc']:.4f}\t{row['false_compliant']}\t{int(row['adversarial_safe'])}\t"
        f"{row['duration_s']:.2f}\n"
    )
    with RESULTS_TSV.open("a", encoding="utf-8") as fh:
        fh.write(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Automated Evaluator cho RFC-Audit.")
    parser.add_argument("--label", default="unnamed", help="Nhãn thực nghiệm ghi vào results.tsv")
    parser.add_argument("--seeds", type=int, default=2, help="Số seed cho rfcv.eval.sim.run_benchmark")
    parser.add_argument("--no-record", action="store_true", help="Chỉ in JSON, không ghi vào results.tsv")
    args = parser.parse_args()

    started = time.monotonic()
    branch, commit, dirty = _git_info()
    ci = _run_ci_gates()
    sim = _run_sim_benchmark(seeds=args.seeds)

    row: dict[str, Any] = {
        "timestamp": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "branch": branch,
        "commit": commit,
        "dirty": dirty,
        "label": args.label,
        "ci_pass": ci["ci_pass"],
        "pytest_passed": ci["pytest_passed"],
        "ruff_ok": ci["ruff_ok"],
        "pyright_ok": ci["pyright_ok"],
        "import_linter_ok": ci["import_linter_ok"],
        "sim_total": sim["sim_total"],
        "verdict_acc": sim["verdict_acc"],
        "false_compliant": sim["false_compliant"],
        "adversarial_safe": ci["adversarial_safe"],
        "duration_s": round(time.monotonic() - started, 2),
    }
    if not args.no_record:
        _append_tsv(row)
    print(json.dumps({**row, "details": ci["details"]}, ensure_ascii=False, indent=2))
    return 0 if ci["ci_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
