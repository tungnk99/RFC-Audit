"""Sinh bộ 6 ca đột biến & đối chứng thật trên HTTP/2 (nghttp2 v1.64.0) cho thực nghiệm đa giao thức (Dev 2).

Các ca:
  - H1 (VIOLATION, WRONG_ALERT):       HTTP2-0001 (RFC 9113 §4.2) — đổi NGHTTP2_FRAME_SIZE_ERROR -> NGHTTP2_PROTOCOL_ERROR (dòng 5963)
  - H2 (VIOLATION, WRONG_ALERT_OTHER): HTTP2-0001 (RFC 9113 §4.2) — đổi NGHTTP2_FRAME_SIZE_ERROR -> NGHTTP2_INTERNAL_ERROR (dòng 5963)
  - H3 (VIOLATION, THRESHOLD_SHIFT):   HTTP2-0001 (RFC 9113 §4.2) — nâng ngưỡng max_frame_size thêm +1024 (dòng 5958)
  - H4 (VIOLATION, DEL_CHECK):         HTTP2-0002 (RFC 9113 §6.7) — bỏ kiểm tra `payloadleft != 8` trên PING (dòng 6239)
  - H5 (COMPLIANT, BASELINE):          HTTP2-0001 trên nghttp2 v1.64.0 gốc
  - H6 (COMPLIANT, BASELINE):          HTTP2-0002 trên nghttp2 v1.64.0 gốc

Cách dùng:
    uv run python scripts/eval_make_mutants_http2.py
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import yaml

BACKEND = Path(__file__).resolve().parent.parent
WORK = BACKEND / "eval" / "work" / "nghttp2"
BASE_ADAPTER = BACKEND / "adapters" / "http2"
OUT_SRC = BACKEND / "runs" / "real" / "src"
OUT_ADAPTERS = BACKEND / "eval" / "adapters"
OUT_YAML = BACKEND / "eval" / "dataset" / "mutants" / "mutants_http2.yaml"

FRAME_SIZE_DSL = """\
id: http2.frame.size_limit_dsl
requirement_types: [B]
rfc_refs: ["RFC9113§4.2"]
checks_behavior: "receive(frame, length > 16384) → send_goaway(frame_size_error)"
variant_class: length_bound
runner: h2spec
steps:
  - {op: connect, args: {tls: false}}
  - {op: complete_handshake}
  - {op: send_raw_record, args: {type: data, flags: "0", stream_id: 1, length: "$frame.length", body: zeros}}
  - {op: expect, args: {within_ms: 2000}}
bindings: {frame.length: from_variant}
oracle: {pass: "alert == frame_size_error", fail: "otherwise", error: "sanity_failed or preface_failed"}
"""

CASES: list[dict[str, Any]] = [
    {
        "id": "H1",
        "family": "F",
        "requirement": "HTTP2-0001",
        "rbs": "HTTP2-0001.rbs",
        "operator": "WRONG_ALERT",
        "expected": "VIOLATION",
        "file": "lib/nghttp2_session.c",
        "line": 5963,
        "old": 'session, NGHTTP2_FRAME_SIZE_ERROR, "too large frame size");',
        "new": 'session, NGHTTP2_PROTOCOL_ERROR, "too large frame size");',
        "why": "Gửi GOAWAY(PROTOCOL_ERROR) thay vì FRAME_SIZE_ERROR khi khung vượt SETTINGS_MAX_FRAME_SIZE.",
    },
    {
        "id": "H2",
        "family": "F",
        "requirement": "HTTP2-0001",
        "rbs": "HTTP2-0001.rbs",
        "operator": "WRONG_ALERT_OTHER",
        "expected": "VIOLATION",
        "file": "lib/nghttp2_session.c",
        "line": 5963,
        "old": 'session, NGHTTP2_FRAME_SIZE_ERROR, "too large frame size");',
        "new": 'session, NGHTTP2_INTERNAL_ERROR, "too large frame size");',
        "why": "Gửi GOAWAY(INTERNAL_ERROR) thay vì FRAME_SIZE_ERROR khi khung vượt SETTINGS_MAX_FRAME_SIZE.",
    },
    {
        "id": "H3",
        "family": "F",
        "requirement": "HTTP2-0001",
        "rbs": "HTTP2-0001.rbs",
        "operator": "THRESHOLD_SHIFT",
        "expected": "VIOLATION",
        "file": "lib/nghttp2_session.c",
        "line": 5958,
        "old": "if (iframe->frame.hd.length > session->local_settings.max_frame_size) {",
        "new": "if (iframe->frame.hd.length > session->local_settings.max_frame_size + 1024) {",
        "why": "Nâng ngưỡng kiểm tra độ dài khung thêm +1024 nên bỏ qua khung 16385..17408 byte.",
    },
    {
        "id": "H4",
        "family": "P",
        "requirement": "HTTP2-0002",
        "rbs": "HTTP2-0002.rbs",
        "operator": "DEL_CHECK",
        "expected": "VIOLATION",
        "file": "lib/nghttp2_session.c",
        "line": 6239,
        "old": "if (iframe->payloadleft != 8) {",
        "new": "if (0 && iframe->payloadleft != 8) {",
        "why": "Bỏ kiểm tra độ dài khung PING != 8, không đóng kết nối mà xử lý tiếp.",
    },
    {
        "id": "H5",
        "family": "F",
        "requirement": "HTTP2-0001",
        "rbs": "HTTP2-0001.rbs",
        "operator": "BASELINE",
        "expected": "COMPLIANT",
        "file": None,
        "line": None,
        "old": None,
        "new": None,
        "why": "nghttp2 v1.64.0 gốc tuân thủ RFC 9113 §4.2.",
    },
    {
        "id": "H6",
        "family": "P",
        "requirement": "HTTP2-0002",
        "rbs": "HTTP2-0002.rbs",
        "operator": "BASELINE",
        "expected": "COMPLIANT",
        "file": None,
        "line": None,
        "old": None,
        "new": None,
        "why": "nghttp2 v1.64.0 gốc tuân thủ RFC 9113 §6.7.",
    },
]


def main() -> None:
    if not WORK.is_dir():
        raise SystemExit(f"Thiếu {WORK}; hãy clone nghttp2 v1.64.0 trước.")
    OUT_SRC.mkdir(parents=True, exist_ok=True)
    OUT_ADAPTERS.mkdir(parents=True, exist_ok=True)
    OUT_YAML.parent.mkdir(parents=True, exist_ok=True)

    items_yaml: list[dict[str, Any]] = []
    for c in CASES:
        cid = c["id"]
        src_dir = OUT_SRC / f"nghttp2-{cid}"
        if src_dir.exists():
            shutil.rmtree(src_dir)
        shutil.copytree(WORK, src_dir, ignore=shutil.ignore_patterns(".git", "doc", "tests"))

        tag = "head"
        commit40 = "526ff38e0249acbcc4d0e8958c12cdeae9960cfe"
        if c["file"] is not None:
            target = src_dir / c["file"]
            txt = target.read_text(encoding="utf-8")
            assert c["old"] in txt, f"Không tìm thấy đoạn gốc cho {cid} trong {target}"
            txt = txt.replace(c["old"], c["new"], 1)
            target.write_text(txt, encoding="utf-8")
            commit40 = hashlib.sha256(f"{cid}:{c['new']}".encode()).hexdigest()[:40]
            tag = commit40[:12]

        # Tạo thư mục adapter riêng cho từng ca
        ad_dir = OUT_ADAPTERS / f"http2-{cid}"
        if ad_dir.exists():
            shutil.rmtree(ad_dir)
        shutil.copytree(BASE_ADAPTER, ad_dir)
        # Chỉ giữ đúng tệp .rbs của yêu cầu này
        for rbs_p in (ad_dir / "examples").glob("*.rbs"):
            if rbs_p.name != c["rbs"]:
                rbs_p.unlink()
        (ad_dir / "templates" / "frame_size.yaml").write_text(FRAME_SIZE_DSL, encoding="utf-8")
        ad_cfg = yaml.safe_load((ad_dir / "adapter.yaml").read_text(encoding="utf-8"))
        ad_cfg["references"] = ["nghttp2-ref"]
        ad_cfg["sut"]["commit"] = commit40
        (ad_dir / "adapter.yaml").write_text(yaml.safe_dump(ad_cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

        entry: dict[str, Any] = {
            "id": cid,
            "family": c["family"],
            "adapter": f"eval/adapters/http2-{cid}",
            "code_root": f"runs/real/src/nghttp2-{cid}",
            "image": f"rfcv/sut-nghttp2:{tag}",
            "commit": ad_cfg["sut"]["commit"],
            "operator": c["operator"],
            "requirement": c["requirement"],
            "expected": c["expected"],
            "why": c["why"],
        }
        if c["file"] is not None:
            entry["fix_location"] = {"files": {c["file"]: [[c["line"], c["line"]]]}}
        else:
            entry["fix_location"] = {"files": {}}
        items_yaml.append(entry)
        print(f"Prepared {cid}: {entry['adapter']} (image={entry['image']})")

    OUT_YAML.write_text(yaml.safe_dump({"items": items_yaml}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"\nWrote {OUT_YAML} ({len(items_yaml)} items)")


if __name__ == "__main__":
    main()
