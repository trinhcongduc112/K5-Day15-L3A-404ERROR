# Báo cáo đánh giá — lượt 1 → một cải tiến → lượt 2

> Điền ở guide bước 4.1. Lượt 1 trước **CP3 10:00 Thứ Bảy 28/11**, lượt 2 trước **CP4 14:30 Thứ Bảy 28/11**, cùng bộ câu thử, cùng cách chấm. Chấm ở rubric R5.
> Số lấy từ `python run.py score eval/run-1.csv` (và `run-2.csv`) sau khi điền cột `pass`. **Kết quả thấp ghi thật vẫn đủ điểm.**
> Không được: sửa chuẩn "đạt", bỏ câu thử trượt, sửa `expected` cho khớp output, sửa kết quả lượt đã chạy.

## 1. Kết quả

| Lượt | Run ID | Đạt / tổng | % | thuong | kho | tu_choi | So với chuẩn "đạt" |
|---|---|---|---|---|---|---|---|
| 1 | `run-1@20261128-095527` | 20/20 | 100% | 8/8 | 8/8 | 4/4 | đạt (chuẩn ≥85%) |
| 2 | `run-2@20261128-051909` | 20/20 | 100% | 8/8 | 8/8 | 4/4 | đạt (chuẩn ≥85%, không vỡ chỗ khác) |

Kết quả từng câu: `eval/run-1.csv`, `eval/run-2.csv`. Trace: `traces/run-1.jsonl`, `traces/run-2.jsonl`.

**Phép đo bổ sung ngoài bộ 20 câu thử (40 ảnh MC-OCR có nhãn, `data/receipts/mcocr_sample_40.csv`):**
- Đường cơ sở Tesseract một mình (`eval/image-check-tesseract.jsonl`): **6/40 đúng** (7 `Xem nhanh`: 6 đúng, 1 sai; 33 `Cần đọc lại`).
- Trước cải tiến — Tesseract + model đọc ảnh `gpt-5.4-nano` (`eval/image-check-before.jsonl`): **25/40 đúng** (27 `Xem nhanh`: 25 đúng, 2 sai; **13 `Cần đọc lại`**; `44,816` token vào / `1,314` token ra).

## 2. Lỗi lượt 1 — gom thành nhóm có tên

> Lượt 1 trên bộ 20 câu chữ đạt 20/20 (0 lỗi). Theo hướng đã chốt cho CP4, các lỗi và nhóm lỗi dưới đây lấy từ **phép đo 40 ảnh MC-OCR** (`eval/image-check-before.jsonl`, đo ngoài bộ câu thử).

| Nhóm lỗi | Số ảnh | Ảnh |
|---|---|---|
| 1. Cần đọc lại oan (OCR cục bộ mất số / không khớp kiểm chéo dù ảnh có tổng) | 11 | `cllbf`, `uexmk`, `ghudu`, `jixhn`, `mppzy`, `pevvt`, `pkgap`, `tzbvy`, `uzdqt` (9 ảnh OCR không ra tổng/không có token khớp) + `skwtp`, `lukeo` (2 ảnh mâu thuẫn OCR–model) |
| 2. Mâu thuẫn giữa tổng OCR cục bộ và model (bị đẩy về Cần đọc lại) | 3 | `skwtp` (OCR đúng `139.200`, model lệch), `lukeo` (OCR sai `28.000` vs `25.000`), `cllbf` (OCR sai `253.000.000` vs `253.000`) |
| 3. ~~Đọc sai chữ số nhưng lọt kiểm chéo (`Xem nhanh` sai)~~ → **Lệch nhãn** *(sửa sau CP4)*: bị chấm sai nhưng hệ thống đọc đúng số in trên ảnh | 2 | `niqeq` (ảnh in `60.582`, nhãn CSV ghi `60,500`), `zxdlo` (`510.760` — nhãn CSV dính `UHD510510.760` nên bị tính `510.510`) |

*(2 ảnh `Cần đọc lại` còn lại là `hpikq` và `wbtei`: nhãn `mcocr_sample_40.csv` không có số tiền tổng nên giữ `Cần đọc lại` là hợp lý.)*

**≥3 lỗi cụ thể:**

| Ảnh | Input | Output | Vì sao sai |
|---|---|---|---|
| `mcocr_public_145014pevvt.jpg` | Ảnh hóa đơn MINIMART ANAN (`thuong`, quality `0.8424`, truth `Tổng cộng \| 75,500`) | `paid_total_vnd: null`, `status: "Cần đọc lại"` | Ảnh rõ nhưng Tesseract không bắt được đúng dòng/token `75500` nên `read_paid_total()` trả `0` và kiểm chéo `_digits_seen_in_ocr()` chặn kết quả model. |
| `mcocr_public_145014lukeo.jpg` | Ảnh hóa đơn MINIMART ANAN (`thuong`, quality `0.7879`, truth `Tổng cộng: \| 25,000`) | `paid_total_vnd: null`, `status: "Cần đọc lại"` (Tesseract một mình ra `28,000`) | Tesseract đọc nhầm `25,000` thành `28,000`; `agent.py` thấy số model đọc khác `ocr_total` (`28000`) nên đánh mâu thuẫn và ép `Cần đọc lại`. |
| `mcocr_public_145013skwtp.jpg` | Ảnh hóa đơn MINIMART ANAN (`thuong`, quality `0.8039`, truth `Tổng cộng: \| 139,200`) | `paid_total_vnd: null`, `status: "Cần đọc lại"` (Tesseract một mình ra `139,200`) | Tesseract đọc đúng `139,200`, nhưng model đọc nhầm sang số khác (vd tiền khách đưa `500,000`) nên bị luật kiểm chéo `total == ocr_total` chặn về `Cần đọc lại`. |
| `mcocr_public_145013niqeq.jpg` | Ảnh hóa đơn VinCommerce (`kho`, quality `0.4410`, truth `TỔNG TIỀN PHẢI T.TOÁN \| 60,500`) | `paid_total_vnd: 60582`, `status: "Xem nhanh"` (`truth_match: false`) | ~~Tesseract và model cùng đọc nhầm chữ số cuối (`60.582` thay vì `60.500`), nên lọt qua kiểm chéo `_digits_seen_in_ocr()` và hiện sai ở `Xem nhanh`.~~ **Sửa sau CP4:** mở ảnh thì dòng `TỔNG TIỀN PHẢI T.TOÁN` in `60.582` (1 món 69.000 ₫/kg × 0,878 kg = 60.582; tiền khách trả cũng `60.582`). Hệ thống đọc **đúng**, nhãn `60,500` trong `mcocr_sample_40.csv` sai. Đây là lỗi nhãn, không phải lỗi đọc; 3 lỗi phía trên vẫn là lỗi thật. |

## 3. Một lần cải tiến

- Nhắm vào nhóm lỗi: **Nhóm 1 — Cần đọc lại oan** (11/40 ảnh có nhãn tổng rõ nhưng bị ép `Cần đọc lại`) — vì sao là nhóm **đau nhất với người dùng**: chiếm tỉ lệ lỗi lớn nhất (11/13 ca `Cần đọc lại`), xảy ra ngay cả trên 5 ảnh rõ (`thuong`, quality 0.79–0.84) và làm hỏng trải nghiệm cốt lõi "chụp một lần, xem nhanh rồi Chốt".
- Đã sửa gì (commit `f1b47fd`, `99c0d91`, `c797c7c`, PR #12 `c9b9f1d`):
  1. Thay OCR cục bộ Tesseract bằng **ONNX `ppocrv3-viesvtr-v7`** (PP-OCRv3 detection + VieSVTR v7 recognition) trong `codebase/document_ocr.py`.
  2. Trong `codebase/agent.py`, chỉ gọi model đọc ảnh khi OCR cục bộ chưa đọc ra tổng (giảm gọi model thừa và tránh mâu thuẫn giả ở các ca OCR đã đọc đúng).
  3. Bổ sung xử lý dòng tổng bị OCR gộp với "Tổng số lượng" trong `document_ocr.py`, giữ nguyên các chốt an toàn (ảnh mờ không gọi model, chỉ ghi khi Chốt).
- Kết quả:
  - **Nhóm lỗi 1 (40 ảnh MC-OCR):** `Cần đọc lại` giảm **13/40 → 3/40** (`image-check-before.jsonl` → `image-check-after.jsonl`); số ảnh đọc đúng tăng **25/40 (62,5%) → 35/40 (87,5%)**; `xem_nhanh_sai` giảm **2 → 1**; token đọc ảnh giảm **44.816 vào / 1.314 ra → 5.415 vào / 149 ra** (giảm ~88%).
    - *Ghi chú sau CP4:* các ca `xem_nhanh_sai` (trước cải tiến: `niqeq`, `zxdlo`; sau cải tiến: `niqeq`) đều do nhãn, hệ thống đọc đúng số in trên ảnh. Đối chiếu với ảnh thì sau cải tiến là **36/40 đúng, 0 ca đọc sai** (3 `Cần đọc lại`; `hpikq` chưa có nhãn tổng để chấm). Số chính thức vẫn giữ theo nhãn (35/40), file đo không sửa.
  - **Bộ 20 câu chữ (`run-2.csv`):** giữ nguyên **20/20 (100%)** (`8/8 thuong · 8/8 kho · 4/4 tu_choi`), chứng minh không làm vỡ luồng ghi sổ, truy vấn hay từ chối.
- Câu nào **tệ đi** sau khi sửa: **0 ảnh tệ đi** trong các ảnh có nhãn tổng (25 ảnh đúng trước đó đều giữ đúng; 10 ảnh chuyển từ sai/`Cần đọc lại` sang đúng). Riêng `mcocr_public_145014hpikq.jpg` chuyển từ `Cần đọc lại` sang `Xem nhanh` (`14.000đ`), nhưng cột `total_cost` trong `mcocr_sample_40.csv` của ảnh này không có số tổng nên `truth_match` là `null`.

## 4. Còn lại

- Lỗi chưa sửa + nguy hiểm thế nào:
  1. ~~**Đọc sai chữ số lẻ (`mcocr_public_145013niqeq.jpg`):** OCR và model cùng ra `60.582đ` thay vì `60.500đ` (lệch 82đ).~~ **Sửa sau CP4:** `niqeq` không phải lỗi đọc (ảnh in `60.582`, nhãn sai). Rủi ro cùng loại vẫn còn: nếu OCR cục bộ đọc nhầm một chữ số ở dòng tổng thì không có model kiểm chéo (model chỉ được gọi khi OCR chưa ra tổng), số sai hiện ở `Xem nhanh`. Nguy hiểm ở mức trung bình: người dùng có thể bấm **Chốt** nhầm số tiền nếu không nhìn kỹ. Trên 40 ảnh chưa gặp ca nào.
  2. **3 ảnh vẫn `Cần đọc lại` (`tzbvy`, `uzdqt`, `wbtei`):** ảnh mờ/nhiễu nặng hoặc thiếu số tổng trên ảnh; hệ thống chọn an toàn (không đoán, yêu cầu chụp lại) nên không ghi sai sổ nhưng người dùng phải nhập tay hoặc chụp lại.
- Nếu có thêm 1 tuần:
  - Thêm đối chiếu chéo tổng các dòng món (`sum(items)`) với `printed_total` để phát hiện ca OCR lệch vài chữ số ở dòng tổng, đẩy về cảnh báo kiểm tra thay vì cho `Xem nhanh` im lặng. *(Sửa sau CP4: bỏ ví dụ `niqeq` vì đó là lỗi nhãn.)*
  - Bổ sung benchmark ảnh thật có nhãn đầy đủ cho 100% ảnh (loại bỏ nhãn khuyết như `hpikq`, nhãn dính ký tự như `zxdlo`, nhãn ghi sai số như `niqeq`).
