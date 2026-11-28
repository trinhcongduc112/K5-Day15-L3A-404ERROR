# Reflection — Trịnh Công Đức

1. **Vai trò + phần mình làm (trỏ tới file / commit):**
   - Đội trưởng: điều phối 4 người theo từng mốc, rà và ghép code của nhóm, nộp 4 checkpoint.
   - Viết `canvas.md` và `spec.md`: lát cắt Track E và bước **Chốt** trước khi ghi sổ (`9cef839`, `0cea24c`), §7 lượt 1 (`9518da8`), §9 rủi ro và §10 changelog (`3494bb7`). Chấm chéo 5 câu CP2 cùng Kiệt, khớp 5/5 (`287c4be`).
   - Ghép luồng OCR → Xem nhanh → Chốt dùng chung một sổ (`43c98b2`); nối model đọc ảnh, buộc số model đọc phải có trong chữ OCR (`ad0020f`).
   - Cải tiến trước lượt 2: chuyển sang OCR cục bộ ONNX (trọng số do Vũ đóng gói), chỉ gọi model khi OCR chưa ra tổng (`f1b47fd`, `99c0d91`, `c797c7c`).
   - Chạy lượt 1 `run-1@20261128-095527` (`1bfdd3e`), đo lại 40 ảnh sau cải tiến (`bb4a1a2`), làm `demo-slides.pdf` (`3494bb7`).

2. **AI hỗ trợ mình thế nào (việc gì, công cụ gì, chỗ nào phải sửa lại output AI):**
   - CP1 dùng Codex sửa Canvas và spec. Từ CP3 dùng Claude Code trong VS Code để viết code đọc ảnh, chạy phép đo 40 ảnh, soạn nháp spec và slide.
   - Mọi số trong spec và slide lấy từ lần chạy `check_ocr.py`, `check_flow.py`, `python run.py eval/score/simulate` lưu trong repo, không chép số AI tự nói.
   - Chỗ phải sửa: kế hoạch CP4 do AI soạn xếp ảnh `niqeq` vào lỗi "đọc sai chữ số", báo cáo và slide làm theo. Kiểm lại ảnh mới thấy hóa đơn in đúng 60.582 như hệ thống đọc; chính nhãn 60,500 trong `mcocr_sample_40.csv` sai.
   - Ở nhánh thử tính năng phân tích chi tiêu, bản đầu AI gợi ý cắt cả nhóm cố định "Hóa đơn & Nhà ở", phải thêm luật chỉ gợi ý nhóm chi linh hoạt. Mình chốt app không tư vấn đầu tư.

3. **Một câu thử trượt của nhóm và mình học được gì từ nó:**
   - Bộ 20 câu chữ đạt 20/20 ở cả hai lượt, nên ca trượt thật của nhóm nằm ở phép đo 40 ảnh hóa đơn.
   - Ảnh `mcocr_public_145014lukeo.jpg` (tổng 25.000): Tesseract một mình đọc thành 28.000 mà vẫn cho Xem nhanh (`eval/image-check-tesseract.jsonl`).
   - Thêm model đọc ảnh thì hai số lệch nhau, luật kiểm chéo chặn về **Cần đọc lại** nên không ghi sai sổ (`eval/image-check-before.jsonl`). Nhưng chính luật đó làm 13/40 ảnh phải đọc lại, người dùng sẽ thấy phiền.
   - Bài học: không nới luật chặn mà sửa ở gốc. Đổi sang OCR ONNX thì `lukeo` ra đúng 25.000 và chỉ còn 3/40 ảnh phải đọc lại (`eval/image-check-after.jsonl`).
   - Đạt 20/20 trên câu chữ không chứng minh được app đọc ảnh tốt: phải đo trên ảnh thật, và mở ảnh kiểm cả nhãn trước khi kết luận hệ thống sai.
