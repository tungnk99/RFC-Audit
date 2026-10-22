"""Các agent của miền RFC giao thức: mỗi agent một thư mục, gồm hồ sơ vai trò, lời nhắc, schema đầu ra và handler.

    <agent>/
      role.yaml    hồ sơ vai trò: vùng tin cậy, ngữ cảnh được thấy, công cụ, ngân sách, schema đầu ra
      prompt.md    lời nhắc hệ thống (khung tám phần), có hash ghi vào bản kê lần chạy
      schema.py    schema đầu ra của agent (nếu agent có kiểu đầu ra riêng của miền)
      handler.py   biến đầu ra của agent thành bằng chứng qua cổng tất định (nếu agent được giao nhiệm vụ)
      __init__.py  `SPEC`: khai báo agent, nhiệm vụ nó nhận, schema nó trả, và đã nối vào luồng chạy chưa

`__init__.py` của gói này cố ý rỗng: danh sách agent nằm ở `agents.registry` (nhập muộn) để tránh vòng nhập với `schemas.py`.
"""
