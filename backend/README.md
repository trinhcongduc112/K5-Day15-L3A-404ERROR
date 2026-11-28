# Backend SkyBill (`backend/`) — Bàn giao CP3 (Nguyễn Quang Vũ)

Thư mục `backend/` đóng gói trọn bộ **mã xử lý Python** và **trọng số mô hình ONNX OCR** để mọi máy trong nhóm chạy được suy luận thật trên CPU, đồng thời được [codebase/document_ocr.py](../codebase/document_ocr.py) tái sử dụng trực tiếp cho [codebase/app.py](../codebase/app.py).

## 1. Cấu trúc thư mục `backend/`

| Thành phần | Vai trò |
|---|---|
| `backend/weights/ocr-1/ppocrv3-viesvtr-v7/det.onnx` | Trọng số phát hiện dòng chữ PaddleOCR PP-OCRv3 DBNet (~2.4 MB) |
| `backend/weights/ocr-1/ppocrv3-viesvtr-v7/viesvtr_v7.onnx` | Trọng số nhận diện tiếng Việt VieSVTR v7 CTC 229 ký tự (~30.6 MB) |
| `backend/weights/ocr-1/ppocrv3-viesvtr-v7/manifest.json` | Nguồn, bản quyền và mã SHA-256 của 2 file trọng số |
| [backend/ocr_engine.py](ocr_engine.py) | Quality Gate (độ phân giải, Laplacian blur, HSV glare) + ONNX OCR + Parser trích ngày, nơi mua, số thực trả, nhóm chi và trạng thái `Cần đọc lại` |
| [backend/storage_service.py](storage_service.py) | Lưu ảnh chụp/tải vào `CSDL/images/YYYY-MM-DD/`, lưu bản nháp vào `CSDL/drafts.json` và chốt vào `CSDL/receipts.json` (có chống cộng trùng theo `capture_id`) |
| [backend/api_server.py](api_server.py) | Máy chủ HTTP độc lập phục vụ giao diện `codebase/frontend/`, ảnh `/csdl/images/*` và REST API |
| [backend/cli_ocr.py](cli_ocr.py) | Lệnh CLI chạy lại được để kiểm tra Quality Gate & ONNX OCR trên từng ảnh hoặc cặp ảnh mẫu Đạt cấp |

## 2. Lệnh cài đặt & chạy kiểm OCR thật

```powershell
# 1. Cài 4 gói backend (numpy, opencv-python-headless, pillow, onnxruntime)
python -m pip install -r requirements.txt

# 2. Chạy kiểm OCR thật trên cặp ảnh mẫu rõ & khó (data/receipts/images/)
python backend/cli_ocr.py --sample-pair

# Hoặc kiểm tra một ảnh bất kỳ:
python backend/cli_ocr.py data/receipts/images/mcocr_public_145014pevvt.jpg

# 3. Chạy Web UI + Backend từ thư mục gốc (mặc định mở http://127.0.0.1:8080)
python run.py
# Hoặc chạy trực tiếp server trong backend/:
python backend/api_server.py
```

### Dấu hiệu xác nhận suy luận thật (không phải model giả)
- Terminal hoặc `/api/health` báo `engine_ready: true`, `weights_directory` trỏ về `backend/weights/ocr-1/ppocrv3-viesvtr-v7`, `engine_version: "ppocrv3-viesvtr-v7"`.
- `POST /api/receipts/scan` trả về `ocr_engine_available: true`, `ocr_lines` khác rỗng và `quality_report` có `laplacian_var`, `blur_score`, `glare_score` đo trực tiếp từ OpenCV.

## 3. Kết quả chạy thật đã kiểm chứng trên ảnh MC-OCR (`data/receipts/images/`)

Chạy bằng `backend/cli_ocr.py --sample-pair` trên CPU:

| Ảnh mẫu | Độ nét (`laplacian_var`) | Số vùng chữ (`ocr_lines_count`) | Độ tin cậy TB | Ngày đọc được | Nơi mua | Thực trả (VND) | Nhóm chi | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| `mcocr_public_145014pevvt.jpg` *(rõ)* | `400.24` (`pass`, `1.0`) | `42` | `0.9872` | `2020-08-10` | `MINIMART ANAN` | `75,500` | `Mua sắm` | `Sẵn sàng Chốt` |
| `mcocr_public_145014zxdlo.jpg` *(khó)* | `436.52` (`pass`, `1.0`) | `73` | `0.8487` | `2020-04-10` | `Vietcombank` | `510,760` | `Chưa phân loại` | `Sẵn sàng Chốt` |

*(Ghi chú: Khi gặp ảnh mờ, loá sáng, `laplacian_var` dưới ngưỡng `QualityPassThreshold = 0.35`, độ tin cậy trung bình `< 0.45` hoặc không xác định được `actual_paid_vnd`, parser tự đánh dấu `needs_reread: true` và `review_status: "Cần đọc lại"` để không cộng nhầm vào sổ.)*
