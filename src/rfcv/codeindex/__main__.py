"""`python -m rfcv.codeindex build --root <kho mã> --out <index.db>`: điểm vào của container code-indexer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rfcv.codeindex.builder import IndexBuildError, build_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rfcv.codeindex")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="dựng chỉ mục SQLite bằng tree-sitter")
    b.add_argument("--root", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        meta = build_index(args.root, args.out)
    except IndexBuildError as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
