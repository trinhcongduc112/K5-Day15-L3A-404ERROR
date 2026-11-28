# Tóm tắt mô phỏng simulate-1@20261128-123906

Do `python run.py simulate` sinh ra — không sửa tay. Chép bảng sang `cost/cost-estimate.md`.

| Persona | Số phiên mô phỏng | Lượt hỏi / phiên | Token vào / phiên | Token ra / phiên | Gọi model / phiên | Gọi công cụ / phiên |
|---|---:|---:|---:|---:|---:|---:|
| dung_it | 13 | 2 | 93 | 4 | 1.0 | 5.4 |
| dung_vua | 16 | 3 | 122 | 6 | 1.3 | 7.9 |
| dung_nhieu | 21 | 4 | 160 | 8 | 1.7 | 10.5 |

Tỉ lệ đạt dùng để tính: 20/20 (100%) — lượt run-2@20261128-051909

- Tỉ lệ đạt lấy từ lượt nhóm chọn: eval/run-2.csv (--rate-from).

| Model (giá) | Chi phí / phiên | Chi phí / task thành công | Chi phí / câu hỏi đạt | Chi phí / tháng — thấp (30 người) | Chi phí / tháng — cơ sở (100 người) | Chi phí / tháng — cao (300 người) | Chi phí / người / tháng (cơ sở) |
|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-5.4-nano (vào 0.2 · ra 1.25 $/1M) | $0.000034 (≈ 1 ₫) | $0.000034 (≈ 1 ₫) | $0.000011 (≈ 0 ₫) | $0.0213 (≈ 541 ₫) | $0.0710 (≈ 1.805 ₫) | $0.2131 (≈ 5.414 ₫) | $0.00071 (≈ 18 ₫) |
| gpt-5.4-mini (vào 0.75 · ra 4.5 $/1M) | $0.00013 (≈ 3 ₫) | $0.00013 (≈ 3 ₫) | $0.000040 (≈ 1 ₫) | $0.0792 (≈ 2.011 ₫) | $0.2639 (≈ 6.704 ₫) | $0.7918 (≈ 20.112 ₫) | $0.0026 (≈ 67 ₫) |

- Chi phí / task thành công = chi phí / phiên ÷ tỉ lệ đạt. Chi phí / câu hỏi đạt = chi phí / phiên ÷ số lượt hỏi trung bình mỗi phiên (3.2) ÷ tỉ lệ đạt — tỉ lệ đạt đo theo từng câu thử.
- Token đo trên model: gpt-5.4-nano-2026-03-17. Giá tính theo từng model trong bảng — model khác bộ tách token thì số token thật có thể lệch; ghi rõ "đo trên model X, tính giá model Y" trong cost/cost-estimate.md.
- Phiên lỗi (không tính vào trung bình): 0/50.
- Tỷ giá: 1 USD = 25.400 ₫ ((tự ước tính) tỷ giá quy đổi tham khảo 25.400 VND/USD).
