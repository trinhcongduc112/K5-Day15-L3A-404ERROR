# Reflection — Nguyễn Quang Vũ

1. **Vai trò + phần mình làm (trỏ tới file / commit):**
   - Thành viên phụ trách giao diện, luồng nhận ảnh và OCR cục bộ (`TEAMS.md`, `PHAN-CONG.md`).
   - Cập nhật kiến trúc luồng chụp hóa đơn kiểu Locket ở `spec.md` §4 (`03b5592`).
   - Xây dựng giao diện web SkyBill tông xanh da trời (chụp trực tiếp bằng camera / tải ảnh kèm chọn ngày, lịch chi tiêu theo ngày/tháng, hướng dẫn lần đầu và trang hướng dẫn từng bước) trong `codebase/frontend/{index.html,styles.css,app.js}` cùng lưu trữ cục bộ ban đầu ở `codebase/storage.py`, `CSDL/README.md`, `.gitignore`, `codebase/app.py` (`faba264`).
   - Triển khai Quality Gate (kiểm độ phân giải, độ mờ Laplacian, độ lóa HSV) và đóng gói 2 và fine-tune mô hình OCR ONNX cục bộ theo bộ data tìm được (`PP-OCRv3 DBNet` `det.onnx` + `VieSVTR v7` `viesvtr_v7.onnx` tại `backend/weights/ocr-1/ppocrv3-viesvtr-v7/`) vào `codebase/document_ocr.py` và `requirements.txt` (`faba264`, `cdcdb1f`), làm nền để nhóm chuyển hẳn sang OCR ONNX trên `main` (`f1b47fd`).
   - Tiếp tục cải tiến đọc ảnh xoay ngang `±90°`, lọc dòng giảm giá âm trong `codebase/document_ocr.py`, và tinh chỉnh `RECEIPT_IMAGE_PROMPT` cùng chốt ngày trong `codebase/agent.py` trên nhánh làm việc (`382ddb4`, `930f447`).

2. **AI hỗ trợ mình thế nào (việc gì, công cụ gì, chỗ nào phải sửa lại output AI):**
   - Dùng Antigravity để kiểm thử trên các ảnh hóa đơn thực tế lẫn bộ 40 ảnh MC-OCR.
   — **chặn việc nới chốt an toàn và ghi đè bằng chứng:** ở `382ddb4`, AI chạy đo lại khi `.env` trống `API_KEY` (token 0) làm ghi đè `eval/image-check-after.jsonl`, đồng thời lọc năm đọc lỗi `2620` về ngày chụp khiến `uzdqt` qua chốt với ngày sai (`28/11/2026` thay vì `13/08/2020`). Mình yêu cầu khôi phục nguyên trạng `eval/image-check-after.jsonl`, giữ chặt chốt "ngày tương lai → Cần đọc lại" và bỏ luật gượng ép (`930f447`).

3. **Một câu thử trượt của nhóm và mình học được gì từ nó:**
   - Bộ 20 câu chữ đạt 20/20, nhưng trên phép đo 40 ảnh MC-OCR thực tế, ảnh `mcocr_public_145014wbtei.jpg` (hóa đơn xoay ngang 90°, tổng `40.000đ`) và `mcocr_public_145014uzdqt.jpg` (phiếu POS Vietcombank, tổng `229.869đ`, ngày `13/08/2020`) vẫn bị đẩy về **Cần đọc lại** (`eval/image-check-after.jsonl`).
   - Với `wbtei`, nguyên nhân là ảnh xoay ngang nên `det.onnx` chỉ bắt được 5 mảnh nhiễu (`mean_conf = 0.2685`); thêm bước tự thử xoay `±90°` khi đọc ít dòng là sửa đúng gốc (đọc ra đúng `40.000đ`, ngày `2020-08-11`).
   - Với `uzdqt`, OCR cục bộ đọc đúng tổng `229.869đ` nhưng đọc nhầm năm `2020` thành `2620`, kích hoạt chốt "ngày tương lai → Cần đọc lại". Cách sửa thử bằng việc bỏ qua năm lỗi để ép sang `Xem nhanh` tuy làm tăng số đúng tổng tiền nhưng lại gây sai ngày trên sổ chi tiêu.
   - Bài học rút ra: không sửa gượng hay nới chốt an toàn để lấy số đẹp, không ghi đè bằng chứng cũ bằng lần đo chưa chạy model thật; khi gặp ca trượt phải xử lý đúng nguyên nhân kỹ thuật ở gốc (hướng ảnh, OCR, prompt) và đo lại trung thực vào file riêng.
