"""Sinh bộ 6 ca đột biến & đối chứng thật trên SSH (Dropbear 2024.86) cho thực nghiệm Held-out Protocol 1.

Các ca:
  - S1 (VIOLATION, DEL_EXIT):          SSH-0001 (RFC 4252 §6) — xoá `dropbear_exit` khi nhận gói >= 80 trước userauth (`src/process-packet.c:140`)
  - S2 (VIOLATION, THRESH_HIGH):       SSH-0001 (RFC 4252 §6) — nâng ngưỡng `MAX_UNAUTH_PACKET_TYPE` lên `255` (`src/process-packet.c:139`)
  - S3 (VIOLATION, KEX_NO_DISCONNECT): SSH-0002 (RFC 4253 §7.1) — đổi `goto error;` thành `return;` khi không có KEX chung (`src/common-kex.c:891`)
  - S4 (VIOLATION, KEX_ERR_NO_EXIT):   SSH-0002 (RFC 4253 §7.1) — đổi `dropbear_exit` ở nhãn `error:` thành `return;` (`src/common-kex.c:1044`)
  - S5 (COMPLIANT, BASELINE):          SSH-0001 trên Dropbear 2024.86 gốc
  - S6 (COMPLIANT, BASELINE):          SSH-0002 trên Dropbear 2024.86 gốc

Cách dùng:
    uv run python scripts/eval_make_mutants_ssh.py
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

BACKEND = Path(__file__).resolve().parent.parent
WORK = BACKEND / "eval" / "work" / "dropbear"
BASE_ADAPTER = BACKEND / "adapters" / "ssh"
OUT_SRC = BACKEND / "runs" / "real" / "src"
OUT_ADAPTERS = BACKEND / "eval" / "adapters"
OUT_YAML = BACKEND / "eval" / "dataset" / "mutants" / "mutants_ssh.yaml"

MSG_BEFORE_AUTH_DSL = """\
id: ssh.userauth.msg_before_auth_plain
requirement_types: [C]
rfc_refs: ["RFC4252§6"]
checks_behavior: "receive(msg, number >= 80) trước khi xác thực xong → close"
variant_class: message_order
runner: asyncssh
steps:
  - {op: connect}
  - {op: send_raw_record, args: {msg_number: "$msg.number", body: zeros, encrypted: false}}
  - {op: expect, args: {within_ms: 2000}}
bindings: {msg.number: from_variant}
oracle: {pass: "closed and no USERAUTH_SUCCESS", fail: "otherwise", error: "sanity_failed"}
"""

SUT_DROPBEAR_YAML = """\
implementation: dropbear
repo: https://github.com/mkj/dropbear
roles:
  server:
    cmd: "/sut/dropbear -F -E -r /sut/host_ed25519_key -p 127.0.0.1:{port}"
    docker_cmd: "/sut/dropbear -F -E -r /sut/host_ed25519_key -p 127.0.0.1:{port}"
    port: 2222
    workdir: /sut
lifecycle:
  per_case_process: false
  ready_check: {kind: listen_socket, port: "{port}", timeout_s: 5}
  sanity_case: "asyncssh:sanity"
  stop_signal: SIGTERM
"""

CASES: list[dict[str, Any]] = [
    {
        "id": "S1",
        "family": "P",
        "requirement": "SSH-0001",
        "expected": "VIOLATION",
        "operator": "DEL_EXIT",
        "file": "src/process-packet.c",
        "target": '\t\tdropbear_exit("Received message %d before userauth", type);',
        "replacement": '\t\t/* MUTANT S1: removed dropbear_exit */ (void)type;',
        "lines": [[139, 141]],
        "symbol": "process_packet",
        "why": "Bỏ dropbear_exit khi nhận gói có mã >= 80 trước userauth (RFC 4252 §6).",
    },
    {
        "id": "S2",
        "family": "P",
        "requirement": "SSH-0001",
        "expected": "VIOLATION",
        "operator": "THRESH_HIGH",
        "file": "src/process-packet.c",
        "target": "\tif ( !ses.authstate.authdone && type > MAX_UNAUTH_PACKET_TYPE ) {",
        "replacement": "\tif ( !ses.authstate.authdone && type > 255 ) { /* MUTANT S2 */",
        "lines": [[139, 141]],
        "symbol": "process_packet",
        "why": "Nâng ngưỡng kiểm tra gói trước userauth từ MAX_UNAUTH_PACKET_TYPE lên 255 nên không ngắt kết nối.",
    },
    {
        "id": "S3",
        "family": "K",
        "requirement": "SSH-0002",
        "expected": "VIOLATION",
        "operator": "KEX_NO_DISCONNECT",
        "file": "src/common-kex.c",
        "target": '\t\terralgo = "kex";\n\t\tgoto error;',
        "replacement": '\t\terralgo = "kex";\n\t\treturn; /* MUTANT S3 */',
        "lines": [[888, 892]],
        "symbol": "read_kex_algos",
        "why": "Không nhảy tới error để ngắt kết nối khi không có thuật toán KEX chung (RFC 4253 §7.1).",
    },
    {
        "id": "S4",
        "family": "K",
        "requirement": "SSH-0002",
        "expected": "VIOLATION",
        "operator": "KEX_ERR_NO_EXIT",
        "file": "src/common-kex.c",
        "target": 'error:\n\tdropbear_exit("No matching algo %s", erralgo);',
        "replacement": 'error:\n\t(void)erralgo; return; /* MUTANT S4 */',
        "lines": [[1043, 1044]],
        "symbol": "read_kex_algos",
        "why": "Nhãn error của read_kex_algos trả về thay vì gọi dropbear_exit khi không khớp thuật toán KEX.",
    },
    {
        "id": "S5",
        "family": "P",
        "requirement": "SSH-0001",
        "expected": "COMPLIANT",
        "operator": "BASELINE",
        "file": None,
        "lines": [],
        "symbol": "",
        "why": "Dropbear 2024.86 gốc tuân thủ RFC 4252 §6 (ngắt kết nối khi nhận gói >= 80 trước userauth).",
    },
    {
        "id": "S6",
        "family": "K",
        "requirement": "SSH-0002",
        "expected": "COMPLIANT",
        "operator": "BASELINE",
        "file": None,
        "lines": [],
        "symbol": "",
        "why": "Dropbear 2024.86 gốc tuân thủ RFC 4253 §7.1 (ngắt kết nối khi không có KEX chung).",
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
    head_src = OUT_SRC / "dropbear-head"
    _copy_work(head_src)
    head_commit = _stamp_git(head_src, "baseline dropbear 2024.86")

    items: list[dict[str, Any]] = []
    for c in CASES:
        cid = c["id"]
        if c["file"] is None:
            src_dir = head_src
            commit = head_commit
            image = "rfcv/sut-dropbear:head"
        else:
            src_dir = OUT_SRC / f"dropbear-{cid}"
            _copy_work(src_dir)
            fp = src_dir / c["file"]
            text = fp.read_text(encoding="utf-8")
            if c["replacement"] not in text:
                assert c["target"] in text, f"{cid}: target not found in {fp}"
                fp.write_text(text.replace(c["target"], c["replacement"], 1), encoding="utf-8")
            commit = _stamp_git(src_dir, f"mutant {cid} ({c['operator']})")
            image = f"rfcv/sut-dropbear:{commit[:12]}"

        ad_dir = OUT_ADAPTERS / f"ssh-{cid}"
        if ad_dir.exists():
            shutil.rmtree(ad_dir)
        ad_dir.mkdir(parents=True)
        (ad_dir / "examples").mkdir()
        (ad_dir / "templates").mkdir()
        (ad_dir / "sut").mkdir()

        # Copy đúng 1 file .rbs của yêu cầu
        shutil.copy2(BASE_ADAPTER / "examples" / f"{c['requirement']}.rbs", ad_dir / "examples" / f"{c['requirement']}.rbs")
        shutil.copy2(BASE_ADAPTER / "templates" / "kex_no_common.yaml", ad_dir / "templates" / "kex_no_common.yaml")
        (ad_dir / "templates" / "msg_before_auth.yaml").write_text(MSG_BEFORE_AUTH_DSL, encoding="utf-8")
        (ad_dir / "sut" / "dropbear.yaml").write_text(SUT_DROPBEAR_YAML, encoding="utf-8")

        base_cfg: dict[str, Any] = yaml.safe_load((BASE_ADAPTER / "adapter.yaml").read_text(encoding="utf-8"))
        base_cfg["sut"] = {
            "repo": "https://github.com/mkj/dropbear",
            "commit": commit,
            "recipe": "sut/dropbear.yaml",
            "start": {"role": "server", "port": 2222},
        }
        base_cfg["references"] = ["dropbear-ref"]
        base_cfg["code_scope"] = {
            "include": ["src/**"],
            "exclude": ["test/**", "fuzz/**"],
        }
        base_cfg["locator_hints"] = {
            "packet_protocol": {
                "keywords": ["process_packet", "MAX_UNAUTH_PACKET_TYPE", "authdone", "dropbear_exit"],
                "entry_points": ["process_packet"],
                "paths": ["src/process-packet.c", "src/packet.c"],
            },
            "kex": {
                "keywords": ["read_kex_algos", "buf_match_algo", "erralgo", "dropbear_exit"],
                "entry_points": ["read_kex_algos"],
                "paths": ["src/common-kex.c"],
            },
        }
        base_cfg["build_flags"] = ["--disable-pam"]
        base_cfg["build_config_complete"] = True
        (ad_dir / "adapter.yaml").write_text(yaml.safe_dump(base_cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

        item: dict[str, Any] = {
            "id": cid,
            "family": c["family"],
            "requirement": c["requirement"],
            "expected": c["expected"],
            "operator": c["operator"],
            "adapter": f"eval/adapters/ssh-{cid}",
            "code_root": f"runs/real/src/{src_dir.name}",
            "commit": commit,
            "image": image,
            "why": c["why"],
        }
        if c["file"] is not None:
            item["fix_location"] = {
                "files": {c["file"]: c["lines"]},
                "symbols": [c["symbol"]],
            }
        items.append(item)

    OUT_YAML.write_text(
        yaml.safe_dump({"protocol": "ssh", "sut": "dropbear", "items": items}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Generated {len(items)} SSH items -> {OUT_YAML}")


if __name__ == "__main__":
    main()
