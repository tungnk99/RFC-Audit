# Dữ liệu và môi trường đánh giá

Triển khai mục 4, 9 của [docs/evaluation/thiet_ke_danh_gia.md](../../docs/evaluation/thiet_ke_danh_gia.md). Thư mục `eval/` này là dữ liệu và script; mã chấm điểm/mô phỏng nằm ở `src/rfcv/eval/`.

```
eval/
  config/eval.yaml          mốc kiến thức, hạt giống, commit cố định của tlsfuzzer/tlslite-ng, từ khoá lọc, ngưỡng
  dataset/
    real/wolfssl_commit_ung_vien.csv   commit ứng viên (script sinh; cột type/keep/requirement do NGƯỜI điền)
    mutants/operators.yaml             toán tử tạo lỗi + mẫu bản ghi
  scripts/
    prepare.ps1                        clone wolfSSL, tlsfuzzer, tlslite-ng; sinh CSV ứng viên
    collect_wolfssl_commits.py         lọc lịch sử commit
    make_manifest.py                   ghi/kiểm eval_manifest (bước "Chốt")
  manifest/eval_manifest.json          hash mọi đầu vào, sinh sau khi chốt
  work/  out/                          bản clone và kết quả chạy (git bỏ qua)
docker/eval-sut.Dockerfile             dựng SUT wolfSSL theo commit + tlsfuzzer cố định
```

## Dựng lại

```powershell
winget install astral-sh.uv ; uv sync
$env:RFCV_GIT = "<đường dẫn git.exe>"    # nếu git không có trong PATH
powershell -File eval/scripts/prepare.ps1
```

Dựng SUT (cần Docker chạy Linux container hoặc máy Linux):

```bash
docker build -f docker/eval-sut.Dockerfile --build-arg WOLFSSL_REV='c18833f52^' -t rfcv/sut-wolfssl:bug .
docker build -f docker/eval-sut.Dockerfile --build-arg WOLFSSL_REV=c18833f52    -t rfcv/sut-wolfssl:fix .
docker build -f docker/eval-sut.Dockerfile --build-arg WOLFSSL_REV=28bc7540d    -t rfcv/sut-wolfssl:head .
```

Kiểm tra môi trường đúng: chạy `test-tls13-record-layer-limits.py` (67 ca, mỗi ca một tiến trình SUT) phải cho bug 12 PASS/55 FAIL, fix và head 66 PASS/1 FAIL (tài liệu khả thi, Bảng 7).

## Việc người phải làm (script không thay được)

1. Lọc tay CSV ứng viên: điền `keep`, `type` (A–D), `requirement`; bỏ commit thêm tính năng.
2. Tạo phiên bản lỗi theo `operators.yaml`, không xem kết quả của hệ thống (N2).
3. Gán nhãn kappa: hai người, ~30 mục, hạt giống `seeds.kappa`.
4. Chốt: `python eval/scripts/make_manifest.py`, sau đó mọi lần chạy gọi `--check` trước.
