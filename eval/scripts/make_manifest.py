"""Ghi eval_manifest: hash mọi đầu vào ảnh hưởng kết luận (thiết kế đánh giá, N1 và bước 2 của mục 9).

    python eval/scripts/make_manifest.py             # in tổng hash, ghi eval/manifest/eval_manifest.json
    python eval/scripts/make_manifest.py --check     # so với bản đã ghi; thoát 1 nếu có tệp đổi (tức là đã sửa sau khi chốt)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval" / "manifest" / "eval_manifest.json"
GLOBS = [
    "eval/config/**/*", "eval/dataset/**/*", "eval/scripts/**/*.py",
    "adapters/**/*", "agents/**/*.md", "agents/**/*.yaml", "skills/**/*", "config/models.yaml",
    "src/rfcv/domains/rfc_protocol/rules.py", "uv.lock",
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def collect() -> dict[str, str]:
    files = {p for g in GLOBS for p in ROOT.glob(g) if p.is_file() and "__pycache__" not in p.parts}
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    files = collect()
    overall = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    if a.check:
        old = json.loads(OUT.read_text(encoding="utf-8"))["files"]
        changed = sorted(k for k in files.keys() | old.keys() if files.get(k) != old.get(k))
        for k in changed:
            print("ĐỔI", k)
        print("khớp bản đã chốt" if not changed else f"{len(changed)} tệp khác bản đã chốt")
        return 1 if changed else 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"overall": overall, "files": files}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(files)} tệp, hash {overall}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
