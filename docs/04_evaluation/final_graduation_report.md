# Báo cáo Nghiệm thu Tốt nghiệp Toàn hệ thống — RFC-Audit (`Gen-1` → `Gen-33`)

Ngày hoàn tất: 2026-11-22 · Nhánh: `feat/nextgen-agent-research` · Mô hình: `DeepSeek-V4-Flash` (`fpt-deepseek-flash`).
Bộ dữ liệu phân tầng: [tiered_benchmark.yaml](../../backend/eval/dataset/tiered_benchmark.yaml) · Nhật ký tiến hoá đầy đủ 33 thế hệ: [evolution_log.jsonl](../../backend/eval/evolution/evolution_log.jsonl) · [knowledge_base.md](../../backend/eval/evolution/knowledge_base.md).

---

## 1. Bảng Tổng kết Nghiệm thu Toàn bộ 4 Tầng (`50/50` ca Docker thật + `5` mô phỏng + `29` cổng an toàn)

> [!IMPORTANT]
> **TỔNG KẾT TỐT NGHIỆP XUẤT SẮC (100% KẾT LUẬN CHÍNH XÁC, 0% BỎ SÓT LỖI, 100% TỔNG QUÁT HOÁ TRÊN `held_out`):**
> Trên toàn bộ **50 ca Docker thật** (trải dài cả 2 thư viện TLS công nghiệp **wolfSSL** và **OpenSSL 3.x**, gồm cả 7 commit lỗi thật từ lịch sử Git của wolfSSL và 19 ca đóng băng `held_out` chưa từng chạm):
> - **Độ chính xác phân loại (`verdict_acc`):** **`50/50 = 100,0%`** (`0` bỏ sót lỗi `false_compliant`, `0` báo nhầm `false_violation`).
> - **Tập đóng băng `held_out` (19 ca — chạy 1 lần nghiệm thu cuối, chứng minh không overfit):**
>   - **`verdict_acc` = `19/19 = 100,0%`** (`G: 9/9`, `R: 7/7`, `U: 3/3`)
>   - **`defect_hit` = `5/5 = 100,0% ALL STRICT`** (`R9`, `U14`, `G8`, `G9`, `G12`)
>   - **Chi phí trung bình:** `117.638` token/ca · `37,9s`/ca.
> - **Toàn bộ cổng kỹ thuật & an toàn (`eval_score.py`):** `266/266 pytest`, `ruff` ✅, `pyright` (0 errors) ✅, `lint-imports` (6/6 contracts) ✅, `adversarial_safe` (`CT08-injection`, `CT26-bad-rbs`: `29/29 passed`) ✅.

| Tầng kiểm chuẩn | Tập mẫu | Verdict Accuracy | `false_compliant` | `false_violation` | `defect_hit` (`strict`) | Trạng thái Graduation Gate |
|---|---|---|---|---|---|---|
| **Tầng 1: `basic`** (`Gen-7` / `Gen-31`) | `5` sim + `7` Docker (`M5, U2, G2, R14, OR3, M6, G4`) | **`12/12 (100%)`** | **`0`** | **`0`** | **`4/5 (80,0% ALL STRICT)`** *(tăng 2x từ `40%` ở `Gen-7`)* | **PASS (100%)** |
| **Tầng 2: `intermediate`** (`Gen-18` / `Gen-32b`) | `16` Docker (`7` lỗi thật wolfSSL + `9` mutant khó wolfSSL/OpenSSL) | **`16/16 (100%)`** *(96/96 qua 6 lượt)* | **`0`** | **`0`** | **`10/11 (90,9% ALL STRICT)`** ở `Gen-18` · **`9/11 (81,8%)`** bản thống nhất `Gen-32b` | **PASS (7/7 — 100%)** |
| **Tầng 3: `advanced`** (`Gen-28`..`Gen-30`) | `8` OpenSSL 3.x đa tệp + `2` cổng an toàn (`CT08`, `CT26`) | **`8/8 (100%)`** *(72/72 qua 9 lượt)* + `29/29` gates | **`0`** | **`0`** | **`6/7 (85,7% ALL STRICT)`** *(3 lượt liên tiếp `Gen-28/29/30`!)* | **PASS (`≥70%` & `repeats=3` — 100%)** |
| **Tập đóng băng `held_out`** (`Gen-33`) | `19` Docker chưa từng chạm (`16` wolfSSL + `3` OpenSSL) | **`19/19 (100,0%)`** | **`0/5 (0%)`** | **`0/14 (0%)`** | **`5/5 (100,0% ALL STRICT)`** (`R9, U14, G8, G9, G12`) | **PASS TUYỆT ĐỐI (100%)** |
| **TỔNG HỢP 50 CA DOCKER THẬT** | **31 dev/eval + 19 `held_out`** | **`50/50 (100,0%)`** | **`0/28 (0,0%)`** | **`0/22 (0,0%)`** | **`25/28 = 89,3%`** *(đỉnh theo tầng)* · **`24/28 = 85,7%`** *(1 bản mã thống nhất)* · **`5/5 = 100%` trên `held_out`** | **TỐT NGHIỆP TOÀN PHẦN** |

---

## 2. Chi tiết Kết quả Nghiệm thu Tập Đóng băng `held_out` (`Gen-33`, `runs/real/tier_heldout_gen33_final`)

| Mã ca | Thư viện | Họ | Kỳ vọng | Kết luận | Luật | Vòng | Thời gian | Token (`all_role`) | `defect_hit` | `defect_hit_strict` |
|---|---|---|---|---|---|---|---|---|---|---|
| `R9` | wolfSSL | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | 2 | `68s` | `210.318` | **TRUE** | **TRUE** |
| `U14` | wolfSSL | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | 2 | `31s` | `244.801` | **TRUE** | **TRUE** |
| `G8` | wolfSSL | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | 2 | `43s` | `230.905` | **TRUE** | **TRUE** |
| `G9` | wolfSSL | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | 2 | `46s` | `241.325` | **TRUE** | **TRUE** |
| `G12` | wolfSSL | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | 2 | `45s` | `239.542` | **TRUE** | **TRUE** |
| `M7` | wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `96s` | `25.036` | — | — |
| `M8` | wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `37s` | `34.097` | — | — |
| `U8` | wolfSSL | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 5 | `61s` | `414.507` | — | — |
| `G5` | wolfSSL | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `14s` | `9.863` | — | — |
| `G6` | wolfSSL | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `9s` | `9.903` | — | — |
| `G7` | wolfSSL | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `8s` | `9.772` | — | — |
| `R12` | wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `38s` | `33.948` | — | — |
| `U13` | wolfSSL | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 5 | `57s` | `400.899` | — | — |
| `G11` | wolfSSL | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `10s` | `9.805` | — | — |
| `R16` | wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `37s` | `33.668` | — | — |
| `R17` | wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `38s` | `34.191` | — | — |
| `OG3` | OpenSSL | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `14s` | `9.836` | — | — |
| `OX1` | OpenSSL | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `9s` | `9.839` | — | — |
| `OX2` | OpenSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | 1 | `69s` | `32.870` | — | — |

---

## 3. Kiến trúc Đa trụ cột đã Tiến hoá qua 33 Thế hệ (Đóng góp Khoa học Chính)

1. **Giải đấu Chuyên gia Định tuyến theo Chữ ký Lỗi (Signature-Routed Best-of-2 Specialist Tournament + Adaptive Rescue)** ([execution_loop.py](../../backend/src/rfcv/core/execution_loop.py), [handler.py](../../backend/agents/code_reader/handler.py)):
   - Phá vỡ hoàn toàn hiệu ứng đường hầm (tunnel vision) của đơn-agent (`Gen-9`: `18%` → `Gen-18`: `90,9%` trên `intermediate`) đồng thời giảm **39% token** nhờ ngân sách gọn `110k–130k`/nhánh và cứu hộ thích nghi chỉ kích hoạt khi chưa có nhánh nào sạch.
2. **Đóng gói Phân tích tĩnh thành Năng lực của AI Agent (Static Analysis as Agentic Tool + Skill):**
   - **Tool `code.find_alert_sites`** ([code_tools.py](../../backend/src/rfcv/gates/code_tools.py)) + **Skill `locate-alert-sites`** ([SKILL.md](../../backend/skills/core/locate-alert-sites/SKILL.md)): quét toàn kho mã C/H không bị cắt cụt `head_limit`, xếp hạng theo từ khoá RBS, gắn `[symbol]` & `[DISABLED]`, nén gọn `cap=6144` byte để tối ưu cho cả tệp đơn 48k dòng (`wolfSSL`) lẫn kiến trúc đa hình 15+ tệp (`OpenSSL 3.x`), đồng thời giữ nguyên 100% ranh giới bảo mật IFC (`TrustLabel.UNTRUSTED`) và `SchemaGate`.
3. **Cổng Phản hồi Tự sửa (`precheck()`) & Kiểm chứng Mã nguồn Tất định (`obs_in_source`):**
   - Phát hiện tức thời các sai lệch có hệ thống (`MISMATCH_REQUIRED_ON_VIOLATION`, `WRONG_PROTOCOL_DIRECTION`, `WRONG_RECORD_STAGE`, `WRONG_OBSERVED_ALERT`, `HINT_SYMBOL_FILE`, `HINT_ENCLOSING_SYMBOL`) và kiểm chứng trực tiếp nguồn C tại trọng tài `select_branch()` (`obs_in_source`), nâng OpenSSL 3.x từ `29% → 85,7% ALL STRICT` (ổn định 3 lượt liên tiếp) và `held_out` đạt **`100,0% ALL STRICT`**.
