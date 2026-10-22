# Chuẩn bị nguồn đánh giá trên Windows: clone SUT và bộ công cụ, ghim commit, sinh danh sách commit ứng viên.
# Chạy từ thư mục gốc repo:  powershell -File scripts/eval_prepare.ps1
# Git không có trong PATH thì đặt $env:RFCV_GIT. Dựng image SUT cần Docker (Linux container), xem eval/README.md.
$ErrorActionPreference = "Stop"
$git = if ($env:RFCV_GIT) { $env:RFCV_GIT } else { "git" }
$cfg = Get-Content eval/config/eval.yaml -Raw
$work = "eval/work"; New-Item -ItemType Directory -Force $work | Out-Null

function Sync-Repo($name, $url, $rev) {
    $dir = "$work/$name"
    if (-not (Test-Path "$dir/.git")) { & $git clone --quiet $url $dir } else { & $git -C $dir fetch --quiet origin }
    if ($rev) { & $git -C $dir checkout --quiet $rev }
    "{0,-11} {1}" -f $name, (& $git -C $dir rev-parse --short HEAD)
}

Sync-Repo "wolfssl"    "https://github.com/wolfSSL/wolfssl" $null
Sync-Repo "tlsfuzzer"  "https://github.com/tlsfuzzer/tlsfuzzer"  ([regex]::Match($cfg, 'tlsfuzzer: \{[^}]*commit: "([0-9a-f]+)"').Groups[1].Value)
Sync-Repo "tlslite-ng" "https://github.com/tlsfuzzer/tlslite-ng" ([regex]::Match($cfg, 'tlslite-ng: \{[^}]*commit: "([0-9a-f]+)"').Groups[1].Value)

$env:RFCV_GIT = $git
uv run python scripts/eval_collect_wolfssl_commits.py --repo "$work/wolfssl" --out eval/dataset/real/wolfssl_commit_ung_vien.csv
