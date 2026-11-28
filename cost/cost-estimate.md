# Chi phí khi dùng thật

> Điền ở guide bước 4.2, nộp ở CP4 14:30 Thứ Bảy 28/11. Ôn lại: ngày 13, ngày 1, ngày 14 · lab ngày 13, lab ngày 14. Chấm ở rubric R6.
> Số **không điền tay**: điền `cost/personas.yaml` → `python run.py simulate` → chép bảng trong `cost/simulate-N-summary.md` vào đây.
> Lúc build dùng gói miễn phí vẫn tính theo **giá gói trả phí** — đây là chi phí cho lúc đưa vào dùng thật.

## 1. Đầu vào

- **Persona** (`cost/personas.yaml`): 3 kiểu chia theo khảo sát 24 người (`evidence/survey/results.csv`):
  - `dung_it` (25% — 6/24 người <10 lượt chi/tuần): `8` phiên/tháng, `2` lượt/phiên *(tự ước tính)*.
  - `dung_vua` (37,5% — 9/24 người 10–20 lượt/tuần): `16` phiên/tháng, `3` lượt/phiên *(kết hợp giả định 12 hóa đơn/tháng ở `spec.md §2`)*.
  - `dung_nhieu` (37,5% — 9/24 người >20 lượt/tuần): `30` phiên/tháng, `4` lượt/phiên *(tự ước tính)*.
  - Trung bình gia quyền: **19,25 phiên/người/tháng**.
- **Số người dùng thật** 3 kịch bản: thấp **30** (nhóm thử nghiệm trong `spec.md §2`) · cơ sở **100** *(tự ước tính)* · cao **300** *(tự ước tính)*.
- **Giá** ≥2 mức model (https://openai.com/api/pricing/, xem ngày 28/11/2026):
  - `gpt-5.4-nano`: **$0.20** / 1M token vào · **$1.25** / 1M token ra.
  - `gpt-5.4-mini`: **$0.75** / 1M token vào · **$4.50** / 1M token ra.
- **Tỉ lệ đạt dùng để tính:**
  - Luồng chữ (tra cứu / chốt / từ chối): **20/20 (100%)** — lượt `run-2@20261128-051909` (`eval/run-2.csv`).
  - Luồng đọc ảnh hóa đơn (ngoài `simulate`): **35/40 (87,5%)** — phép đo sau cải tiến `eval/image-check-after.jsonl` (**không dùng 100%** vì thực tế còn 3 ca `Cần đọc lại`, 1 ca lệch nhãn, 1 ca nhãn khuyết tổng). *Sửa sau CP4:* ca lệch nhãn (`niqeq`) trước ghi là "đọc sai chữ số lẻ", thực ra hệ thống đọc đúng (ảnh in 60.582, nhãn ghi 60.500); vẫn giữ tỉ lệ 87,5% theo nhãn để tính thận trọng.
- **Đo token trên model `gpt-5.4-nano-2026-03-17`, tính giá model `gpt-5.4-nano` và `gpt-5.4-mini`.**

## 2. Kết quả mô phỏng

Lượt mô phỏng: `cost/simulate-1.csv` · run ID `simulate-1@20261128-123906` · **50 phiên** · seed **42** · lỗi: **0/50**.

*(chép từ `cost/simulate-1-summary.md` — phần luồng chữ)*

| Model (giá) | Chi phí / phiên | Chi phí / task thành công | Chi phí / câu hỏi đạt | / tháng — thấp (30 người) | / tháng — cơ sở (100 người) | / tháng — cao (300 người) | / người / tháng (cơ sở) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `gpt-5.4-nano` (vào 0.2 · ra 1.25 $/1M) | $0.000034 (≈ 1 ₫) | $0.000034 (≈ 1 ₫) | $0.000011 (≈ 0 ₫) | $0.0213 (≈ 541 ₫) | $0.0710 (≈ 1.805 ₫) | $0.2131 (≈ 5.414 ₫) | $0.00071 (≈ 18 ₫) |
| `gpt-5.4-mini` (vào 0.75 · ra 4.5 $/1M) | $0.00013 (≈ 3 ₫) | $0.00013 (≈ 3 ₫) | $0.000040 (≈ 1 ₫) | $0.0792 (≈ 2.011 ₫) | $0.2639 (≈ 6.704 ₫) | $0.7918 (≈ 20.112 ₫) | $0.0026 (≈ 67 ₫) |

### Bổ sung chi phí đọc ảnh hóa đơn (từ `eval/image-check-after.jsonl`)

`simulate` chỉ chạy câu chữ nên cộng thêm token đo thật trên 40 ảnh MC-OCR sau cải tiến ONNX: **5,415 token vào / 149 token ra** cho 40 ảnh (trung bình **135 token vào / 4 token ra mỗi ảnh**, nhờ chỉ gọi model khi ONNX chưa ra tổng). Tính với tỉ lệ đọc ảnh thành công **35/40 (87,5%)** và giả định tối đa mỗi phiên đều kèm 1 ảnh hóa đơn (`19,25` ảnh/người/tháng):

| Model | Chi phí / 1 ảnh | Chi phí / 1 hóa đơn đọc thành công (÷ 87,5%) | Chi phí ảnh / người / tháng | Tổng chữ + ảnh / người / tháng | Tổng / tháng — cơ sở (100 người) | Tổng / tháng — cao (300 người) |
|---|---:|---:|---:|---:|---:|---:|
| `gpt-5.4-nano` | $0.000032 (≈ 0,8 ₫) | **$0.000036 (≈ 0,9 ₫)** | $0.00061 (≈ 16 ₫) | **$0.00132 (≈ 34 ₫)** | **$0.132 (≈ 3.356 ₫)** | **$0.396 (≈ 10.068 ₫)** |
| `gpt-5.4-mini` | $0.000118 (≈ 3,0 ₫) | **$0.000135 (≈ 3,4 ₫)** | $0.00228 (≈ 58 ₫) | **$0.00488 (≈ 125 ₫)** | **$0.488 (≈ 12.487 ₫)** | **$1.46 (≈ 37.460 ₫)** |

Chi phí / task thành công = chi phí trung bình mỗi phiên ÷ tỉ lệ đạt — **không coi như đạt 100%** cho tác vụ đọc ảnh (dùng 87,5%).

## 3. So với impact

- Impact / người / tháng (`spec.md` §2): tiết kiệm **7 phút/người/tháng** (210 phút / 30 người ở mức 12 hóa đơn/tháng; lên tới **~11,2 phút/người/tháng** ở mức trung bình 19,25 phiên/tháng).
- Chi phí / người / tháng (cơ sở, model `gpt-5.4-nano`, đã gồm cả chữ + ảnh): **$0.00132 (≈ 34 ₫/người/tháng)** (chỉ bằng ~34 đồng để tiết kiệm 7–11 phút nhập tay và tránh quên/lệch sổ). Nếu dùng `gpt-5.4-mini` cũng chỉ **≈ 125 ₫/người/tháng**.
- **Kết luận một dòng — đáng làm không:** **Rất đáng làm** — chi phí API gần như bằng 0 (~34 ₫/người/tháng, ~3.400 ₫/tháng cho 100 người) nhờ ONNX xử lý cục bộ hầu hết hóa đơn rõ và chỉ gọi model khi cần.

## 4. *(Muốn sâu hơn, không bắt buộc)*

- Bảng độ nhạy: model rẻ hơn · cache · cắt ngữ cảnh · giới hạn bước — mỗi cần gạt đổi chi phí bao nhiêu
- Chi phí ngoài model: hosting, lưu trữ, giờ công người duyệt
- Quy mô nào thì bài toán còn đáng làm
