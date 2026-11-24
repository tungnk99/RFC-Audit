"""Build Docker images cho HTTP/2 (nghttp2 v1.64.0 head + các đột biến H1..H4 từ mutants_http2.yaml)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

BACKEND = Path(__file__).resolve().parent.parent
DOCKERFILE = BACKEND / "docker" / "eval-nghttp2.Dockerfile"
YAML_PATH = BACKEND / "eval" / "dataset" / "mutants" / "mutants_http2.yaml"


def build_image(tag: str, overlay_files: dict[str, Path], commit_rev: str = "") -> None:
    tmp = Path(tempfile.mkdtemp(prefix="rfcv-h2-build-"))
    try:
        ov = tmp / "overlay"
        ov.mkdir()
        for rel, src in overlay_files.items():
            dst = ov / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        cmd = ["docker", "build", "-f", str(DOCKERFILE), "-t", tag]
        if commit_rev:
            cmd += ["--build-arg", f"COMMIT_REV={commit_rev}"]
        cmd.append(str(tmp))
        print(f"=== Building {tag} ===", flush=True)
        subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    data: dict[str, Any] = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    # 1. Build head (dùng cho H5, H6 và làm nghttp2-ref)
    build_image("rfcv/sut-nghttp2:head", {})
    # 2. Build 4 đột biến H1..H4
    seen: set[str] = {"rfcv/sut-nghttp2:head"}
    for item in data["items"]:
        img = str(item["image"])
        if img in seen:
            continue
        seen.add(img)
        code_root = BACKEND / item["code_root"]
        files = {rel: code_root / rel for rel in item["fix_location"]["files"]}
        build_image(img, files, commit_rev=str(item["commit"]))
    print("ALL HTTP/2 IMAGES BUILT SUCCESSFULLY!", flush=True)


if __name__ == "__main__":
    main()
