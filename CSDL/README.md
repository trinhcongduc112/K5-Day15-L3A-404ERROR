# Thư mục `CSDL/` — Lưu trữ cục bộ cho SkyBill

Thư mục này được [codebase/storage.py](../codebase/storage.py) tự động khởi tạo khi chạy `python run.py`:

- `CSDL/images/YYYY-MM-DD/<RecordId>.jpg`: Ảnh hoá đơn người dùng đã chụp hoặc tải lên.
- `CSDL/receipts.json`: Danh sách hoá đơn đã xác nhận lưu vào sổ chi tiêu (nếu chưa có thì tự tạo từ dữ liệu mẫu `data/expenses.json` — cùng nguồn với eval; nút "Khôi phục dữ liệu hoá đơn mẫu" trên web nạp lại file này).
- `CSDL/drafts.json`: Các bản nháp đang chờ người dùng duyệt (`DRAFT_PENDING_USER`).
- `CSDL/settings.json`: Cài đặt của người dùng, hiện có hạn mức chi tiêu tháng (`monthly_budget`, 0 = tắt).

> Để bảo vệ dữ liệu ảnh và hoá đơn cục bộ, các file `CSDL/images/`, `CSDL/receipts.json`, `CSDL/drafts.json` và `CSDL/settings.json` được loại trừ trong `.gitignore`.
