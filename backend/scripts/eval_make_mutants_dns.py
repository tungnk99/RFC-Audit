"""Sinh bộ 6 ca đột biến & đối chứng thật trên DNS (Knot DNS v3.4.2) cho thực nghiệm đa giao thức (Dev 3).

Các ca:
  - D1 (VIOLATION, DEL_CHECK):         DNS-0001 (RFC 6891 §6.1.1) — bỏ kiểm tra `pkt->opt_rr != NULL` (src/libknot/packet/pkt.c:647)
  - D2 (VIOLATION, WRONG_ALERT):       DNS-0001 (RFC 6891 §6.1.1) — đổi KNOT_RCODE_FORMERR -> KNOT_RCODE_SERVFAIL (src/knot/nameserver/process_query.c:824)
  - D3 (VIOLATION, WRONG_ALERT):       DNS-0002 (RFC 6891 §6.1.3) — đổi KNOT_RCODE_BADVERS -> KNOT_RCODE_NOTIMP (src/knot/nameserver/process_query.c:269)
  - D4 (VIOLATION, WRONG_ALERT_OTHER): DNS-0002 (RFC 6891 §6.1.3) — đổi KNOT_RCODE_BADVERS -> KNOT_RCODE_FORMERR (src/knot/nameserver/process_query.c:269)
  - D5 (COMPLIANT, BASELINE):          DNS-0001 trên Knot DNS v3.4.2 gốc
  - D6 (COMPLIANT, BASELINE):          DNS-0002 trên Knot DNS v3.4.2 gốc
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import yaml

BACKEND = Path(__file__).resolve().parent.parent
WORK = BACKEND / "eval" / "work" / "knot"
BASE_ADAPTER = BACKEND / "adapters" / "dns"
OUT_SRC = BACKEND / "runs" / "real" / "src"
OUT_ADAPTERS = BACKEND / "eval" / "adapters"
OUT_YAML = BACKEND / "eval" / "dataset" / "mutants" / "mutants_dns.yaml"

EDNS_VERSION_DSL = """\
id: dns.edns.version_dsl
requirement_types: [B]
rfc_refs: ["RFC6891§6.1.3"]
checks_behavior: "receive(query, opt.version > 0) → respond(badvers)"
variant_class: length_bound
runner: dnspython
steps:
  - {op: connect, args: {transport: udp}}
  - {op: mutate, args: {field: opt.version, op: set, value: "$opt.version"}}
  - {op: send_msg, args: {type: query, qname: example.test}}
  - {op: expect, args: {within_ms: 2000}}
bindings: {opt.version: from_variant}
oracle: {pass: "alert == badvers", fail: "otherwise", error: "sanity_failed"}
"""

OPT_DUP_DSL = """\
id: dns.edns.opt_duplicate_dsl
requirement_types: [B]
rfc_refs: ["RFC6891§6.1.1"]
checks_behavior: "receive(query, query.opt_count > 1) → respond(formerr)"
variant_class: length_bound
runner: dnspython
steps:
  - {op: connect, args: {transport: udp}}
  - {op: mutate, args: {field: query.opt_count, op: set, value: "$query.opt_count"}}
  - {op: send_msg, args: {type: query, qname: example.test}}
  - {op: expect, args: {within_ms: 2000}}
bindings: {query.opt_count: from_variant}
oracle: {pass: "alert == formerr", fail: "otherwise", error: "sanity_failed"}
"""

CASES: list[dict[str, Any]] = [
    {
        "id": "D1",
        "family": "O",
        "requirement": "DNS-0001",
        "rbs": "DNS-0001.rbs",
        "operator": "DEL_CHECK",
        "expected": "VIOLATION",
        "file": "src/libknot/packet/pkt.c",
        "line": 647,
        "old": "if (pkt->current != KNOT_ADDITIONAL || pkt->opt_rr != NULL ||",
        "new": "if (pkt->current != KNOT_ADDITIONAL ||",
        "why": "Bỏ kiểm tra trùng lặp OPT RR (`pkt->opt_rr != NULL`), không trả FORMERR khi query.opt_count > 1.",
    },
    {
        "id": "D2",
        "family": "O",
        "requirement": "DNS-0001",
        "rbs": "DNS-0001.rbs",
        "operator": "WRONG_ALERT",
        "expected": "VIOLATION",
        "file": "src/knot/nameserver/process_query.c",
        "line": 594,
        "old": "\tif (query->parsed < query->size) {\n\t\tqdata->rcode = KNOT_RCODE_FORMERR;",
        "new": "\tif (query->parsed < query->size) {\n\t\tqdata->rcode = KNOT_RCODE_SERVFAIL;",
        "why": "Trả RCODE SERVFAIL thay vì FORMERR khi gặp thông điệp có nhiều hơn 1 OPT RR.",
    },
    {
        "id": "D3",
        "family": "E",
        "requirement": "DNS-0002",
        "rbs": "DNS-0002.rbs",
        "operator": "WRONG_ALERT",
        "expected": "VIOLATION",
        "file": "src/knot/nameserver/process_query.c",
        "line": 269,
        "old": "qdata->rcode = KNOT_RCODE_BADVERS;",
        "new": "qdata->rcode = KNOT_RCODE_NOTIMPL;",
        "why": "Trả RCODE NOTIMP thay vì BADVERS khi opt.version > 0.",
    },
    {
        "id": "D4",
        "family": "E",
        "requirement": "DNS-0002",
        "rbs": "DNS-0002.rbs",
        "operator": "WRONG_ALERT_OTHER",
        "expected": "VIOLATION",
        "file": "src/knot/nameserver/process_query.c",
        "line": 269,
        "old": "qdata->rcode = KNOT_RCODE_BADVERS;",
        "new": "qdata->rcode = KNOT_RCODE_FORMERR;",
        "why": "Trả RCODE FORMERR thay vì BADVERS khi opt.version > 0.",
    },
    {
        "id": "D5",
        "family": "O",
        "requirement": "DNS-0001",
        "rbs": "DNS-0001.rbs",
        "operator": "BASELINE",
        "expected": "COMPLIANT",
        "file": None,
        "line": None,
        "old": None,
        "new": None,
        "why": "Knot DNS v3.4.2 gốc tuân thủ RFC 6891 §6.1.1.",
    },
    {
        "id": "D6",
        "family": "E",
        "requirement": "DNS-0002",
        "rbs": "DNS-0002.rbs",
        "operator": "BASELINE",
        "expected": "COMPLIANT",
        "file": None,
        "line": None,
        "old": None,
        "new": None,
        "why": "Knot DNS v3.4.2 gốc tuân thủ RFC 6891 §6.1.3.",
    },
]


def main() -> None:
    if not WORK.is_dir():
        raise SystemExit(f"Thiếu {WORK}; hãy clone Knot DNS v3.4.2 trước.")
    OUT_SRC.mkdir(parents=True, exist_ok=True)
    OUT_ADAPTERS.mkdir(parents=True, exist_ok=True)
    OUT_YAML.parent.mkdir(parents=True, exist_ok=True)

    items_yaml: list[dict[str, Any]] = []
    for c in CASES:
        cid = c["id"]
        src_dir = OUT_SRC / f"knot-{cid}"
        if src_dir.exists():
            shutil.rmtree(src_dir)
        shutil.copytree(WORK, src_dir, ignore=shutil.ignore_patterns(".git", "doc", "tests", "tests-fuzz"))

        tag = "head"
        commit40 = "93efd4c5dbfe884f9a4c0bf99b5126aaee3d614a"
        if c["file"] is not None:
            target = src_dir / c["file"]
            txt = target.read_text(encoding="utf-8")
            assert c["old"] in txt, f"Không tìm thấy đoạn gốc cho {cid} trong {target}"
            txt = txt.replace(c["old"], c["new"], 1)
            target.write_text(txt, encoding="utf-8")
            commit40 = hashlib.sha256(f"{cid}:{c['new']}".encode()).hexdigest()[:40]
            tag = commit40[:12]

        ad_dir = OUT_ADAPTERS / f"dns-{cid}"
        if ad_dir.exists():
            shutil.rmtree(ad_dir)
        shutil.copytree(BASE_ADAPTER, ad_dir)
        for rbs_p in (ad_dir / "examples").glob("*.rbs"):
            if rbs_p.name != c["rbs"]:
                rbs_p.unlink()
        (ad_dir / "templates" / "edns_version.yaml").write_text(EDNS_VERSION_DSL, encoding="utf-8")
        (ad_dir / "templates" / "opt_duplicate.yaml").write_text(OPT_DUP_DSL, encoding="utf-8")
        ad_cfg = yaml.safe_load((ad_dir / "adapter.yaml").read_text(encoding="utf-8"))
        ad_cfg["references"] = ["knot-ref"]
        ad_cfg["sut"]["commit"] = commit40
        (ad_dir / "adapter.yaml").write_text(yaml.safe_dump(ad_cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

        entry: dict[str, Any] = {
            "id": cid,
            "family": c["family"],
            "adapter": f"eval/adapters/dns-{cid}",
            "code_root": f"runs/real/src/knot-{cid}",
            "image": f"rfcv/sut-knot:{tag}",
            "commit": commit40,
            "operator": c["operator"],
            "requirement": c["requirement"],
            "expected": c["expected"],
            "why": c["why"],
        }
        entry["fix_location"] = {"files": {c["file"]: [[c["line"], c["line"]]]}} if c["file"] is not None else {"files": {}}
        items_yaml.append(entry)
        print(f"Prepared {cid}: {entry['adapter']} (image={entry['image']})")

    OUT_YAML.write_text(yaml.safe_dump({"items": items_yaml}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"\nWrote {OUT_YAML} ({len(items_yaml)} items)")


if __name__ == "__main__":
    main()
