"""Sinh bộ 4 ca đột biến & đối chứng thật trên QUIC (ngtcp2 v1.9.1) cho thực nghiệm Held-out Protocol 2.

Các ca:
  - Q1 (VIOLATION, DEL_DGRAM_CHECK): QUIC-0001 (RFC 9000 §14.1) — xoá kiểm tra `pktlen < NGTCP2_MAX_UDP_PAYLOAD_SIZE` (`lib/ngtcp2_conn.c:10230`)
  - Q2 (VIOLATION, THRESH_LOW):      QUIC-0001 (RFC 9000 §14.1) — hạ ngưỡng `NGTCP2_MAX_UDP_PAYLOAD_SIZE` xuống `600` tại `ngtcp2_accept` (`lib/ngtcp2_conn.c:10230`)
  - Q3 (VIOLATION, MACRO_SHIFT):     QUIC-0001 (RFC 9000 §14.1) — đổi macro `#define NGTCP2_MAX_UDP_PAYLOAD_SIZE 1200` thành `512` (`lib/includes/ngtcp2/ngtcp2.h:303`)
  - Q4 (COMPLIANT, BASELINE):        QUIC-0001 trên ngtcp2 v1.9.1 gốc

Cách dùng:
    uv run python scripts/eval_make_mutants_quic.py
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

BACKEND = Path(__file__).resolve().parent.parent
WORK = BACKEND / "eval" / "work" / "ngtcp2"
BASE_ADAPTER = BACKEND / "adapters" / "quic"
OUT_SRC = BACKEND / "runs" / "real" / "src"
OUT_ADAPTERS = BACKEND / "eval" / "adapters"
OUT_YAML = BACKEND / "eval" / "dataset" / "mutants" / "mutants_quic.yaml"

SUT_NGTCP2_YAML = """\
implementation: ngtcp2
repo: https://github.com/ngtcp2/ngtcp2
roles:
  server:
    cmd: "/sut/rfcv_ngtcp2_srv {port}"
    docker_cmd: "/sut/rfcv_ngtcp2_srv {port}"
    port: 4433
    transport: udp
    workdir: /sut
lifecycle:
  per_case_process: false
  ready_check: {kind: udp_query, port: "{port}", timeout_s: 5}
  sanity_case: "aioquic:sanity"
  stop_signal: SIGTERM
"""

CASES: list[dict[str, Any]] = [
    {
        "id": "Q1",
        "family": "D",
        "requirement": "QUIC-0001",
        "expected": "VIOLATION",
        "operator": "DEL_DGRAM_CHECK",
        "file": "lib/ngtcp2_conn.c",
        "target": "  if (pktlen < NGTCP2_MAX_UDP_PAYLOAD_SIZE ||\n      (p->tokenlen == 0 && p->dcid.datalen < NGTCP2_MIN_INITIAL_DCIDLEN)) {",
        "replacement": "  if (/* MUTANT Q1: removed pktlen check */ (p->tokenlen == 0 && p->dcid.datalen < NGTCP2_MIN_INITIAL_DCIDLEN)) {",
        "lines": [[10230, 10233]],
        "symbol": "ngtcp2_accept",
        "why": "Bỏ kiểm tra pktlen < NGTCP2_MAX_UDP_PAYLOAD_SIZE trong ngtcp2_accept (RFC 9000 §14.1).",
    },
    {
        "id": "Q2",
        "family": "D",
        "requirement": "QUIC-0001",
        "expected": "VIOLATION",
        "operator": "THRESH_LOW",
        "file": "lib/ngtcp2_conn.c",
        "target": "  if (pktlen < NGTCP2_MAX_UDP_PAYLOAD_SIZE ||",
        "replacement": "  if (pktlen < 600 /* MUTANT Q2 */ ||",
        "lines": [[10230, 10233]],
        "symbol": "ngtcp2_accept",
        "why": "Hạ ngưỡng kích thước datagram Initial từ 1200 xuống 600 trong ngtcp2_accept (RFC 9000 §14.1).",
    },
    {
        "id": "Q3",
        "family": "D",
        "requirement": "QUIC-0001",
        "expected": "VIOLATION",
        "operator": "MACRO_SHIFT",
        "file": "lib/includes/ngtcp2/ngtcp2.h",
        "target": "#define NGTCP2_MAX_UDP_PAYLOAD_SIZE 1200",
        "replacement": "#define NGTCP2_MAX_UDP_PAYLOAD_SIZE 512 /* MUTANT Q3 */",
        "lines": [[303, 303], [10230, 10233]],
        "symbol": "ngtcp2_accept",
        "why": "Hạ macro NGTCP2_MAX_UDP_PAYLOAD_SIZE từ 1200 xuống 512 khiến ngtcp2_accept chấp nhận gói < 1200 byte.",
    },
    {
        "id": "Q4",
        "family": "D",
        "requirement": "QUIC-0001",
        "expected": "COMPLIANT",
        "operator": "BASELINE",
        "file": None,
        "lines": [],
        "symbol": "",
        "why": "ngtcp2 v1.9.1 gốc tuân thủ RFC 9000 §14.1 (bỏ mọi datagram Initial < 1200 byte).",
    },
]


def _stamp_git(repo_dir: Path, msg: str) -> str:
    git_dir = repo_dir / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
    res = subprocess.run(["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True, check=True)
    if res.stdout.strip():
        subprocess.run(
            ["git", "-c", "user.name=RFC-Audit", "-c", "user.email=eval@rfcv.local", "commit", "-q", "-m", msg],
            cwd=repo_dir,
            check=True,
        )
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir, text=True).strip()


def _copy_work(dst: Path) -> None:
    if dst.exists():
        return
    shutil.copytree(WORK, dst, ignore=shutil.ignore_patterns(".git"))


def main() -> None:
    OUT_SRC.mkdir(parents=True, exist_ok=True)
    head_src = OUT_SRC / "ngtcp2-head"
    _copy_work(head_src)
    head_commit = _stamp_git(head_src, "baseline ngtcp2 v1.9.1")

    items: list[dict[str, Any]] = []
    for c in CASES:
        cid = c["id"]
        if c["file"] is None:
            src_dir = head_src
            commit = head_commit
            image = "rfcv/sut-ngtcp2:head"
        else:
            src_dir = OUT_SRC / f"ngtcp2-{cid}"
            _copy_work(src_dir)
            fp = src_dir / c["file"]
            text = fp.read_text(encoding="utf-8")
            if c["replacement"] not in text:
                assert c["target"] in text, f"{cid}: target not found in {fp}"
                fp.write_text(text.replace(c["target"], c["replacement"], 1), encoding="utf-8")
            commit = _stamp_git(src_dir, f"mutant {cid} ({c['operator']})")
            image = f"rfcv/sut-ngtcp2:{commit[:12]}"

        ad_dir = OUT_ADAPTERS / f"quic-{cid}"
        if ad_dir.exists():
            shutil.rmtree(ad_dir)
        ad_dir.mkdir(parents=True)
        (ad_dir / "examples").mkdir()
        (ad_dir / "templates").mkdir()
        (ad_dir / "sut").mkdir()

        shutil.copy2(BASE_ADAPTER / "examples" / f"{c['requirement']}.rbs", ad_dir / "examples" / f"{c['requirement']}.rbs")
        shutil.copy2(
            BASE_ADAPTER / "templates" / "initial_datagram_size.yaml",
            ad_dir / "templates" / "initial_datagram_size.yaml",
        )
        (ad_dir / "sut" / "ngtcp2.yaml").write_text(SUT_NGTCP2_YAML, encoding="utf-8")

        base_cfg: dict[str, Any] = yaml.safe_load((BASE_ADAPTER / "adapter.yaml").read_text(encoding="utf-8"))
        base_cfg["sut"] = {
            "repo": "https://github.com/ngtcp2/ngtcp2",
            "commit": commit,
            "recipe": "sut/ngtcp2.yaml",
            "start": {"role": "server", "port": 4433},
        }
        base_cfg["references"] = ["ngtcp2-ref"]
        base_cfg["build_config_complete"] = True
        (ad_dir / "adapter.yaml").write_text(yaml.safe_dump(base_cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

        item: dict[str, Any] = {
            "id": cid,
            "family": c["family"],
            "requirement": c["requirement"],
            "expected": c["expected"],
            "operator": c["operator"],
            "adapter": f"eval/adapters/quic-{cid}",
            "code_root": f"runs/real/src/{src_dir.name}",
            "commit": commit,
            "image": image,
            "why": c["why"],
        }
        if c["file"] is not None:
            if c["file"] == "lib/includes/ngtcp2/ngtcp2.h":
                fmap = {c["file"]: [c["lines"][0]], "lib/ngtcp2_conn.c": [c["lines"][1]]}
            else:
                fmap = {c["file"]: c["lines"]}
            item["fix_location"] = {
                "files": fmap,
                "symbols": [c["symbol"]],
            }
        items.append(item)

    OUT_YAML.write_text(
        yaml.safe_dump({"protocol": "quic", "sut": "ngtcp2", "items": items}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Generated {len(items)} QUIC items -> {OUT_YAML}")


if __name__ == "__main__":
    main()
