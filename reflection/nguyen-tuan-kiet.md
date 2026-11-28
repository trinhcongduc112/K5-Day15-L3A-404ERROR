# Reflection — Nguyễn Tuấn Kiệt

1. **Vai trò + phần mình làm (trỏ tới file / commit):**
   - Phụ trách bằng chứng người dùng, đánh giá và ước tính chi phí của nhóm.
   - Tổng hợp khảo sát 24 người (`evidence/survey/results.csv`, `evidence/summary.md` — `17daff1`), thống kê review công khai (`2e70712`), dựng giao diện giả lập điện thoại theo `spec.md` (`9bdd09b`).
   - Chấm độc lập 5 mẫu CP2 khớp 5/5 với Đức (`eval/README.md` — `f1795ee`), chấm lượt 1 `run-1.csv` (`aede44d`) và lượt 2 `run-2.csv` (`6b5be01`) đạt 20/20.
   - Gom nhóm lỗi từ 40 ảnh MC-OCR vào `eval/report.md` (`98de7bf`, `40304ed`), thiết lập `cost/personas.yaml` từ khảo sát 24 người (`cfcf936`), chạy mô phỏng 50 phiên `simulate-1@20261128-123906` và hoàn thiện `cost/cost-estimate.md` + `spec.md` §7–§8 (`737723d`).

2. **AI hỗ trợ mình thế nào (việc gì, công cụ gì, chỗ nào phải sửa lại output AI):**
   - Dùng AI (Antigravity / Gemini) để đọc đối chiếu file CSV/JSONL, dựng UI giả lập điện thoại, soạn khung `eval/report.md`, `eval/README.md`, `cost/personas.yaml`, và chạy `run.py simulate` / `run.py check` với model thật.
   - Chỗ phải sửa lại output AI: bản kế hoạch và nháp đầu tiên ghi số liệu ảnh trước cải tiến theo ước lượng cũ (24 đúng · 1 sai · 15 Cần đọc lại), tôi phải đối chiếu lại đúng `eval/image-check-before.jsonl` mới nhất (25 đúng · 2 sai · 13 Cần đọc lại) trước khi chốt `eval/report.md`.
   - Ngoài ra, AI từng xếp `mcocr_public_145013niqeq.jpg` (`60.582` vs nhãn `60.500`) vào nhóm hệ thống đọc sai chữ số; sau khi nhóm kiểm tra trực tiếp ảnh gốc mới phát hiện chính nhãn CSV bị sai còn ảnh in `60.582`. Không lấy số AI đoán cho chi phí mà bắt buộc chạy `run.py simulate` 50 phiên thật.

3. **Một câu thử trượt của nhóm và mình học được gì từ nó:**
   - Trên bộ 20 câu chữ, hệ thống đạt 20/20 ở cả hai lượt, nhưng khi đo 40 ảnh hóa đơn thật trước cải tiến (`eval/image-check-before.jsonl`), có tới **13/40 ảnh** rơi vào `Cần đọc lại`, trong đó **11 ảnh có tổng rõ** (như `mcocr_public_145014pevvt.jpg`, `jixhn`, `pkgap`).
   - Nguyên nhân là Tesseract bỏ sót hoặc đọc sai chữ số khiến lớp kiểm chéo chặn lại về `Cần đọc lại`, làm hỏng trải nghiệm "chụp một lần rồi Chốt".
   - Bài học: đánh giá chỉ trên câu thử chữ dễ tạo cảm giác an toàn giả; phải đo trên ảnh thật, gom lỗi theo tác động người dùng để sửa đúng gốc (đổi sang ONNX `ppocrv3-viesvtr-v7` giúp tăng từ 25/40 lên **35/40**, giảm `Cần đọc lại` từ 13 xuống 3 và giảm ~88% token).
