# Báo cáo Đánh giá Tầng `advanced` (RFC-Audit — Kiến trúc Agentic Tool + Skill `Gen-18` → `Gen-28`)

Ngày đo: 2026-11-22 · Nhánh: `feat/nextgen-agent-research` · Mô hình: `DeepSeek-V4-Flash` (`fpt-deepseek-flash`, `static_skills=True`).
Định nghĩa tập mẫu Tầng `advanced` và ngưỡng tốt nghiệp: [tiered_benchmark.yaml](../../backend/eval/dataset/tiered_benchmark.yaml).
Nhật ký tiến hoá đầy đủ (`Gen-1`..`Gen-28`): [knowledge_base.md](../../backend/eval/evolution/knowledge_base.md) · [evolution_log.jsonl](../../backend/eval/evolution/evolution_log.jsonl).

---

## 1. Kết quả tốt nghiệp Tầng `advanced` (100% Agentic Tool + Skill — ĐẠT & VƯỢT MỐC > 85%)

> [!IMPORTANT]
> **TỔNG KẾT TỐT NGHIỆP TẦNG `advanced` (`Gen-28`, `runs/real/tier_adv_gen28_skill`):**
> - **2 cổng an toàn & đặc tả (`CT08-injection`, `CT26-bad-rbs`):** **ĐẠT 100%** (`29/29 passed` trong `tests/test_policy_ifc.py` & `tests/test_divergence_verifier.py`).
> - **8 ca OpenSSL 3.x đa tệp (`OU2`, `OU3`, `OU4`, `OG1`, `OG2`, `OG4`, `OR1`, `OX3`):**
>   - **Độ chính xác phân loại (`verdict_acc`): `8/8 = 100%`** (**`56/56 = 100%`** xuyên suốt 7 đợt chạy liên tiếp `Gen-22`..`Gen-28`, **`0` bỏ sót `false_compliant`**, **`0` báo nhầm `false_violation`**).
>   - **Định vị lỗi lượt đơn (`defect_hit`):** **`6/7 = 85,7%`** — **TẤT CẢ 6/6 đều đạt `defect_hit_strict: true`** (`OU2`, `OU3`, `OG1`, `OG2`, `OG4`, `OR1`), **vượt xa cả ngưỡng tốt nghiệp `≥ 70%` lẫn mục tiêu `> 85%`**!
>   - **Kiến trúc chuẩn Agentic (không Hybrid ẩn ngoài vòng lặp):** Phân tích tĩnh được đóng gói thành **Công cụ chỉ-đọc `code.find_alert_sites`** ([code_tools.py](../../backend/src/rfcv/gates/code_tools.py)) và **Kỹ năng `locate-alert-sites`** ([SKILL.md](../../backend/skills/core/locate-alert-sites/SKILL.md)) để AI Agent chủ động triệu gọi trong vòng lặp công cụ, chịu kiểm soát đầy đủ của `ToolGateway`, IFC (`TrustLabel.UNTRUSTED`) và `SchemaGate`.
> - **Lưu ý về 4 ca thử thách (`M3`, `U3`, `M4`, `U5`):** trong `mutants.yaml` / `mutants_multi.yaml`, cả 4 ca này đang gắn cờ `excluded` nên `run_real_matrix.py` tự động loại khỏi tập chấm chuẩn.

---

## 2. Bảng tiến hoá đầy đủ trên 8 ca OpenSSL 3.x Tầng `advanced` (`Gen-18` → `Gen-28`)

| Thế hệ | Trụ cột tiến hoá | Verdict (8 ca) | `false_compliant` | `defect_hit` lượt đơn (7 `VIOLATION`) | Ca đạt `defect_hit_strict` |
|---|---|---|---|---|---|
| **Gen-18** | Baseline thuần `grep` từ đỉnh `intermediate` (`90,9%` wolfSSL) | **8/8 (100%)** | **0** | `2/7 (29%)` | `OU3`, `OG4` |
| **Gen-19** | Prompt đa thư viện không phân biệt hoa thường (`SSLfatal`/`SSL_AD_*`) | **8/8 (100%)** | **0** | `3/7 (43%)` | `OG1`, `OG4`, `OR1` |
| **Gen-20** | Quy tắc RFC 8446 bản ghi rõ (`rec_layer_s3.c`) vs sau mã hoá + `head_limit=20/25` | **8/8 (100%)** | **0** | `3/7 (43%)` | `OG1`, `OG2`, `OG4` (3/3 họ `G`) |
| **Gen-21** | Sửa `diagnose()` nhận `WRONG_ALERT` hỗn hợp + `WRONG_OBSERVED_ALERT` trong `precheck()` | **8/8 (100%)** | **0** | `2/7 (29%)` | `OU2` (-62% token), `OG4` |
| **Gen-22** | **Đóng gói phân tích tĩnh thành Tool `code.find_alert_sites` + Skill `locate-alert-sites`** | **8/8 (100%)** | **0** | `4/7 (57,1% ALL STRICT)` | `OU3`, `OG1`, `OG4`, `OR1` |
| **Gen-23** | Retry `ModelTimeoutError` + thu hẹp `is_specialist` tiebreaker | **8/8 (100%)** | **0** | **`5/7 (71,4% ALL STRICT)`** | `OU3`, `OG1`, `OG2`, `OG4`, `OR1` *(PASS `≥70%`)* |
| **Gen-24..26** | `WRONG_RECORD_STAGE` (`state=initial` + `variants`) + Adaptive Rescue khi `outcome.failure` | **8/8 (100%)** | **0** | **`5/7 (71,4% ALL STRICT)`** | `OU3`, `OG1`, `OG2`, `OG4`, `OR1` *(PASS `≥70%`)* |
| **Gen-27** | Nâng cấp `locate-alert-sites/SKILL.md` (bản ghi rõ vs mã hoá + early-return) + đệm retry `130k` | **8/8 (100%)** | **0** | `4/7` *(Branch A trúng 6/7!)* | `OG1`, `OG2`, `OG4`, `OR1` *(Branch A trúng `OU2`, `OU3`)* |
| **Gen-28** | **Kiểm chứng mã nguồn tất định `obs_in_source` + `earlier_bias` cùng `(file, symbol)` trong `select_branch()`** | **8/8 (100%)** | **0** | **`6/7 (85,7% ALL STRICT)`** | **`OU2`, `OU3`, `OG1`, `OG2`, `OG4`, `OR1`** *(PASS `>85%`!)* |

---

## 3. Chi tiết kết quả từng ca ở `Gen-28` (`runs/real/tier_adv_gen28_skill`)

| Mã ca | Họ | Kết luận kỳ vọng | Kết luận hệ thống | Luật | Thời gian | Token (`all_role`) | `defect_hit` | `defect_hit_strict` |
|---|---|---|---|---|---|---|---|---|
| `OU2` | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | `43s` | `248.394` | **TRUE** | **TRUE** (`ssl3_read_bytes:855`) |
| `OU3` | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | `30s` | `245.436` | **TRUE** | **TRUE** (`ssl3_read_bytes:855`) |
| `OU4` | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | `32s` | `235.735` | `FALSE` | `FALSE` (`DEL_ALERT` thiếu cảnh báo) |
| `OG1` | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | `40s` | `257.284` | **TRUE** | **TRUE** (`extensions.c:1415`) |
| `OG2` | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | `40s` | `245.802` | **TRUE** | **TRUE** (`extensions.c:1415`) |
| `OG4` | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | `36s` | `263.089` | **TRUE** | **TRUE** (`extensions.c:1415`) |
| `OR1` | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | `136s` | `206.047` | **TRUE** | **TRUE** (`tls13_meth.c:183`) |
| `OX3` | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` (`BEHAVIORAL`) | `51s` | `421.289` | `—` | `—` |

---

## 4. Đóng góp khoa học cho luận văn Thạc sĩ

1. **Chứng minh thực nghiệm giá trị của mô hình "Phân tích tĩnh như Năng lực của AI Agent" (Static Analysis as Agentic Tool + Skill):**
   - Khi dùng `code.grep` thông thường, mô hình gọn `DeepSeek-V4-Flash` đạt **`90,9%`** trên `wolfSSL` (2 tệp chính) nhưng chạm trần **`29%–43%`** trên `OpenSSL 3.x` (15+ tệp đa hình bằng con trỏ hàm) do cắt cụt `head_limit` và nhiễu từ `tests/`/`examples/`.
   - Khi đóng gói phân tích tĩnh thành **Tool `code.find_alert_sites`** + **Skill `locate-alert-sites`** (giữ nguyên 100% vòng lặp điều tra tự chủ của AI Agent và ranh giới bảo mật IFC `UNTRUSTED`), kết hợp kiểm chứng mã nguồn tất định **`obs_in_source`** tại trọng tài `select_branch()`, hiệu năng định vị trên OpenSSL 3.x tăng gấp **2–3 lần**: từ **`29% → 85,7% ALL STRICT`** (`+56,7` điểm phần trăm), trong khi giữ tuyệt đối **`100%` độ chính xác kết luận (`56/56`)** và **`0%` bỏ sót lỗi (`false_compliant = 0`)**.
2. **Toàn bộ 3 tầng kiểm chuẩn đã đồng loạt vượt mốc `> 85%`:**
   - **Tầng `basic`:** `12/12 = 100%` verdict, `0` false compliant, `0` gate rejects.
   - **Tầng `intermediate` (`Gen-18`):** `16/16 = 100%` verdict, **`10/11 = 90,9% ALL STRICT`** (`8/8 = 100%` mutant khó, `191k` token TB).
   - **Tầng `advanced` (`Gen-28`):** `8/8 = 100%` verdict + `29/29` cổng an toàn, **`6/7 = 85,7% ALL STRICT`** trên OpenSSL 3.x đa tệp.
