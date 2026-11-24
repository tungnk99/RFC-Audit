"""Gắn git repo + commit SHA thật cho code_root và đóng dấu /sut/.rev + tag image (đáp ứng ràng buộc C3 của rfcv)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

BACKEND = Path(__file__).resolve().parent.parent


def main() -> None:
    yaml_path = Path(sys.argv[1]).resolve()
    repo_prefix = sys.argv[2]  # e.g. rfcv/sut-nghttp2
    data: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    for it in data["items"]:
        src = (BACKEND / it["code_root"]).resolve()
        if not (src / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=src, check=True)
            subprocess.run(["git", "add", "-A"], cwd=src, check=True)
            subprocess.run(
                ["git", "-c", "user.name=rfcv", "-c", "user.email=rfcv@local", "commit", "-q", "-m", str(it["id"])],
                cwd=src,
                check=True,
            )
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=src, text=True).strip()
        old_img = str(it["image"])
        new_img = f"{repo_prefix}:{sha[:12]}"
        tmp = Path(tempfile.mkdtemp(prefix="rfcv-stamp-"))
        try:
            df = f'FROM {old_img}\nUSER root\nRUN printf "%s\\n" "{sha}" > /sut/.rev\nUSER nobody\n'
            (tmp / "Dockerfile").write_text(df, encoding="utf-8")
            subprocess.run(["docker", "build", "-q", "-t", new_img, str(tmp)], check=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        it["commit"] = sha
        it["image"] = new_img
        ad_p = (BACKEND / it["adapter"] / "adapter.yaml").resolve()
        ad = yaml.safe_load(ad_p.read_text(encoding="utf-8"))
        ad["sut"]["commit"] = sha
        ad_p.write_text(yaml.safe_dump(ad, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"Stamped {it['id']}: {sha[:12]} -> {new_img}", flush=True)
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    main()
