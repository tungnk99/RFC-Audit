"""Số đo nền trên SUT THẬT: chạy script tlsfuzzer `test-tls13-record-layer-limits.py` trên các image wolfSSL đã dựng.

Mỗi ca chạy với MỘT tiến trình server mới (đúng cách tài liệu khả thi đã chạy tay). Container không có mạng ngoài
(`--network none`); server và client cùng nằm trong container nên nói chuyện qua 127.0.0.1.

    docker build -f docker/eval-sut.Dockerfile --build-arg 'WOLFSSL_REV=c18833f52^' -t rfcv/sut-wolfssl:bug .   (xem eval/README.md)
    uv run python scripts/run_tlsfuzzer_baseline.py bug fix head            # chạy cả danh sách ca
    uv run python scripts/run_tlsfuzzer_baseline.py head --limit 5          # thử nhanh vài ca

Kết quả: runs/real/baseline-<tag>.json (từng ca PASS/FAIL, thời gian) và bảng tổng hợp in ra màn hình. Đây là số đo của
tlsfuzzer trên wolfSSL thật, chưa phải kết quả của hệ thống đa agent.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "real"
IMAGE = "rfcv/sut-wolfssl:{tag}"
SCRIPT = "/opt/tlsfuzzer/scripts/test-tls13-record-layer-limits.py"
PY = "/opt/venv/bin/python3"
PORT = 4433
HEX_PORT = f"{PORT:04X}"  # /proc/net/tcp ghi cổng dạng hex

# Chạy trong container; đọc tên ca từ stdin, mỗi dòng một ca. In `CASE<TAB>kết quả<TAB>tên`.
CONTAINER_LOOP = rf"""
cd /sut
while IFS= read -r name; do
  ./examples/server/server -v 4 -d -g -i -p {PORT} >/dev/null 2>&1 &
  srv=$!
  n=0; until grep -q ":{HEX_PORT} .* 0A " /proc/net/tcp; do sleep 0.05; n=$((n+1)); [ $n -gt 100 ] && break; done
  out=$(timeout 60 {PY} {SCRIPT} -h 127.0.0.1 -p {PORT} "$name" 2>&1)
  if   printf '%s' "$out" | grep -q '^PASS: 1$'; then res=PASS
  elif printf '%s' "$out" | grep -q '^FAIL: 1$'; then res=FAIL
  else res=ERROR; fi
  kill $srv 2>/dev/null; wait $srv 2>/dev/null
  printf 'CASE\t%s\t%s\n' "$res" "$name"
done
"""

LIST_CMD = f"cd /sut && {PY} {SCRIPT} -h 127.0.0.1 -p {PORT} -n 0 2>&1"


def docker(tag: str, *args: str, stdin: str | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    """Chạy một container. Truyền stdin dạng bytes: ở chế độ văn bản Windows đổi \n thành \r\n làm hỏng tên ca."""
    cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--entrypoint", "sh", IMAGE.format(tag=tag), "-c", *args]
    raw = subprocess.run(
        cmd, input=(stdin or "").encode("utf-8"), capture_output=True, timeout=timeout, check=False
    )
    return subprocess.CompletedProcess(
        cmd, raw.returncode, raw.stdout.decode("utf-8", "replace"), raw.stderr.decode("utf-8", "replace")
    )


def list_cases(tag: str) -> list[str]:
    """Danh sách tên ca: chạy script khi chưa có server, mọi ca đều FAIL và được liệt kê đủ trong mục FAILED."""
    out = docker(tag, LIST_CMD, timeout=900).stdout
    body = out.split("FAILED:", 1)[1] if "FAILED:" in out else ""
    names = re.findall(r"^\t'(.*)'$", body, flags=re.M)
    return list(dict.fromkeys(names))


def run(tag: str, cases: list[str]) -> dict[str, object]:
    t0 = time.time()
    proc = docker(tag, CONTAINER_LOOP, stdin="\n".join(cases) + "\n")
    results = [line.split("\t", 2)[1:] for line in proc.stdout.splitlines() if line.startswith("CASE\t")]
    return {
        "image": IMAGE.format(tag=tag),
        "seconds": round(time.time() - t0, 1),
        "cases": [{"name": name, "result": res} for res, name in results],
        "stderr_tail": proc.stderr[-500:],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="+", help="bug fix head")
    ap.add_argument("--limit", type=int, default=0, help="chỉ chạy N ca đầu (thử nhanh)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    cases = list_cases(args.tags[0])
    if not cases:
        print("Không lấy được danh sách ca (image có chạy được không?)", file=sys.stderr)
        return 2
    if args.limit:
        cases = cases[: args.limit]
    print(f"{len(cases)} ca; chạy {', '.join(args.tags)}\n")

    summary: dict[str, dict[str, int]] = {}
    for tag in args.tags:
        res = run(tag, cases)
        (OUT / f"baseline-{tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        counts: dict[str, int] = {}
        for c in res["cases"]:  # type: ignore[union-attr]
            counts[c["result"]] = counts.get(c["result"], 0) + 1  # type: ignore[index]
        summary[tag] = counts
        print(f"{tag:5} {counts}  ({res['seconds']} giây)")

    print()
    print(f"{'image':8} {'PASS':>5} {'FAIL':>5} {'ERROR':>6}")
    for tag, c in summary.items():
        print(f"{tag:8} {c.get('PASS', 0):>5} {c.get('FAIL', 0):>5} {c.get('ERROR', 0):>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
