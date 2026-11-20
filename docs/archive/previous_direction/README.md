# Lưu trữ hướng tiếp cận trước (Snapshot `dev` @ `b433e9d`)

Thư mục này ghi lại tóm tắt hướng tiếp cận giai đoạn trước (đã sao lưu toàn bộ mã nguồn và số đo tại nhánh `dev`, commit `b433e9d` trên `origin/dev`) trước khi chuyển sang hướng nghiên cứu mới ở [Thiết kế tiến hoá AI Agent & quy trình nghiên cứu](../../02_design/agentic_research_evolution_design.md).

## Đặc trưng của giai đoạn trước (tới Nhật ký đo #15)

- **Trọng tâm:** Ưu tiên giảm chi phí token và thời gian bằng cách tất định hoá mạnh các bước điều phối:
  - `Planner` LLM → `PlaybookRunner` tất định.
  - `Tester` LLM → `scenario_synth.py` dựng từ mẫu sẵn.
  - `Verifier` LLM → kiểm toán bằng luật cho ca `COMPLIANT`.
  - Chạy một họ mô hình duy nhất (`fpt-deepseek-flash`), nạp skill động qua `load_capability`.
- **Thành tựu đã đạt (làm Baseline đối chứng `B0`):**
  - Chạy trọn quy trình trên wolfSSL thật (`bug` / `fix` / `head`), phân loại đúng 3/3.
  - Bản đúng giảm từ 1,41 triệu token xuống 34k token; bản lỗi giảm từ 274k xuống 161k token và định vị trúng hunk `c18833f52` (`DoProcessReplyEx`, `disabled_by = HAVE_MAX_FRAGMENT`).
  - Lõi an toàn (`IFC`, `Schema gate`, `Tool gateway`, `Verdict engine V0–V9`, hash-chained `Evidence store`) ổn định và đã có bộ test bất biến.

## Lý do chuyển hướng nghiên cứu

1. **Làm mờ năng lực thật của AI Agent:** Ở chế độ tối ưu #15, ca `COMPLIANT` không còn chạy agent điều tra nào (chỉ chạy Report), chưa chứng minh được đầy đủ sức mạnh của hệ thống đa tác tử AI.
2. **Dễ gãy trên các mô hình nhỏ/nhanh khác nhau:** Còn phụ thuộc `tool_choice` (xung đột thinking mode của DeepSeek/GLM), nạp skill động (`CT-01`), ngữ cảnh `code__read` thiếu nhãn `#ifdef` trực tiếp, Report tốn 34k token cho T3 PASS.
3. **Thiếu độ rộng thực nghiệm:** Mới đo trên 1 yêu cầu (`TLS13-0042`), $n = 1$, 1 họ mô hình (`CT-07`), chưa có cơ chế so sánh đối chứng nhiều kiến trúc agent.

> Các tài liệu thiết kế gốc trong `docs/02_design/` và `docs/04_evaluation/` vẫn được giữ nguyên tại chỗ để bảo toàn liên kết hình ảnh, bản HTML đối chiếu và làm nền tảng cho hướng nâng cấp mới.
