# 404ERROR · Nhật ký chi tiêu từ ảnh

**Lớp L3A · Track E (Tài chính).** [Thành viên](TEAMS.md) · [Lát cắt CP1](#cp1) · [Canvas cập nhật CP2](canvas.md)

**Bài toán dự kiến.** Người muốn theo dõi chi tiêu hằng ngày phải nhập lại thông tin từ từng hóa đơn, nên dễ bỏ sót khoản chi và mất thời gian khi xem lại đã tiêu vào đâu.

**Lát cắt hiện tại (Track E).** Khi người ghi chi tiêu cá nhân chụp một hóa đơn, AI chọn nhóm chi dựa trên nội dung hóa đơn để họ có một khoản chi trên lịch sau khi bấm Chốt. [Canvas dòng 5](canvas.md) · [Thiết kế chi tiết trong spec §4](spec.md#lat-cat)

**Trải nghiệm demo.** **Chụp hóa đơn → xem nhanh số tiền, ngày và nhóm chi → bấm Chốt.** App lưu và cập nhật lịch sau khi chốt. Chạm một ngày để xem tổng; chọn **Xem thêm** để mở từng khoản. **+** mở camera để ghi khoản mới. Kết quả tháng tính từ các khoản đã ghi.

**Thiết kế giao diện.** Lịch tháng ưu tiên điện thoại với ô ngày hiện số tiền. Chạm ngày mở bảng tổng hợp và nút **Xem thêm**. Dùng bố cục và nhận diện riêng cho nhật ký chi tiêu.

**Lịch sử chọn track.** Nhóm chọn Track D (Thương mại điện tử) ban đầu rồi cập nhật CP1 sang Track E (Tài chính cá nhân).

**Chạy thử (CP3).** Web và `answer()` dùng chung quy tắc (`tools.py`, `agent.choose_category`) và chung một sổ `CSDL/receipts.json` (khởi tạo từ `data/expenses.json`). Eval/simulate dùng sổ tạm riêng, mỗi câu một bản sao `data/expenses.json`, nên không đụng sổ thật.

Cách 1 — Docker (khuyên dùng, đủ thư viện OCR):

```bash
docker compose up --build                                   # web: http://localhost:8080
docker compose run --rm app python run.py eval --try        # mọi lệnh run.py chạy được như vậy
docker compose run --rm app sh -c "cd codebase && python check_ocr.py --truth ../data/receipts/mcocr_sample_40.csv ../data/receipts/images/*.jpg"
```

Cách 2 — máy có sẵn Python 3.10+: `pip install -r requirements.txt` rồi `python run.py`.

Model thật: tạo `.env` (`MODEL_PROVIDER`, `MODEL_NAME`, `API_KEY` — xem `docs/connect-model.md`), không commit. Đọc ảnh: OCR cục bộ ONNX (PP-OCRv3 + VieSVTR v7, trọng số trong `backend/weights/ocr-1/ppocrv3-viesvtr-v7/` — nguồn, SHA-256 và giấy phép trong `manifest.json`; VieSVTR là **CC-BY-NC-4.0, chỉ dùng học thuật/phi thương mại**). Model chỉ được gọi để đọc lại ảnh mà OCR cục bộ chưa ra số thực trả, và số đó phải có trong chữ OCR. Đo trên 40 ảnh mẫu: `python codebase/check_ocr.py --model --truth data/receipts/mcocr_sample_40.csv data/receipts/images/*.jpg`.

Kiểm 3 ca ghép luồng (ảnh rõ → Chốt lưu đúng · ảnh mờ → Cần đọc lại, không đổi tổng · chụp lại cùng ảnh → không cộng trùng):

```bash
SKYBILL_STORAGE_DIR=/tmp/csdl-thu SKYBILL_NO_BROWSER=1 python run.py &
python codebase/check_flow.py http://127.0.0.1:8080 data/receipts/images/mcocr_public_145013tupze.jpg
```

**Phân tích chi tiêu (tính năng phát triển, nhánh `feat/spending-insight`):** tab **Thống kê** có ô đặt hạn mức tháng, thanh % đã dùng, dự báo cuối tháng và cảnh báo; thông báo nổi bật hiện trên lịch và sau mỗi lần Chốt. Mọi con số do code tính (`codebase/insights.py`); nút **AI phân tích chi tiêu** gửi bảng số tổng (không tên cửa hàng, không ảnh) cho model để viết nhận xét và gợi ý tiết kiệm, câu nào có số không khớp sổ bị bỏ. Kiểm không cần mạng: `cd codebase && python check_insights.py`.

CLI văn bản (`python codebase/app.py --cli`) nhận `Chụp hóa đơn: … | Tổng thanh toán: 55.000đ`, `Sửa tiền: 50.000đ`, `Sửa nhóm: Ăn uống`, `Chốt`, `Ấn xem ngày 2026-11-27`, `Xem tuần 2026-W47`, `So sánh tuần 2026-W47 với kỳ trước`.

## Dùng AI vào việc gì

Nhóm dùng Codex để soạn lại hồ sơ theo lát cắt chụp hóa đơn, xem nhanh và bấm Chốt và kiểm tra định dạng. Đội trưởng rà phạm vi, giả thuyết và phân công trước khi nộp. [Khai báo chi tiết](docs/ai-usage.md)

---

## Đề hackathon AI20K khoá 5 · L3

> **[README]** → [01-challenge-brief](01-challenge-brief.md) → [tracks/](tracks/README.md) → [02-guide](02-guide.md) → [03-rubric](03-rubric.md)

**Tìm một chỗ đau thật của người dùng, thiết kế một giải pháp AI cho nó, rồi chứng minh bằng số.**

Bài của nhóm phải cân bằng hai nửa: **tư duy sản phẩm** (đúng người dùng, đúng chỗ đau, đáng làm) và **giải pháp AI** (thiết kế công nghệ ra sao, AI dựa vào dữ liệu và công cụ nào, chạy thật được). Ba câu phải trả lời, mỗi câu bằng số:

1. **Pain & impact:** ai đang đau, đau thế nào, bao nhiêu người, mỗi tháng mất bao nhiêu?
2. **Giải pháp AI:** AI quyết định gì, dựa trên dữ liệu và công cụ nào, chọn workflow hay agent và vì sao, chặn rủi ro ở đâu, người duyệt ở đâu? Bản chạy thử phải gọi AI thật.
3. **Đánh giá & chi phí:** giải pháp đúng được bao nhiêu trên bộ câu thử? Dùng thật ở quy mô thật của sản phẩm thì tốn bao nhiêu mỗi tháng?

- Nhóm **3–5 người**, tự ghép, bầu một đội trưởng.
- Khoảng **10 giờ làm thật**: chiều tối Thứ Sáu 27/11 và sáng Thứ Bảy 28/11.
- **6 track:** A EdTech (chính khoá AI20K) · B Y tế · C Du lịch · D Thương mại điện tử · E Tài chính · F Làn khác (lĩnh vực bất kỳ, có insight từ người dùng thật).
- BTC **không cấp API key**. Nhóm dùng gói miễn phí hoặc tài khoản của nhóm.
- Mọi kỹ thuật cần dùng, nhóm đã học trong 15 ngày giai đoạn 1. [02-guide.md](02-guide.md) chỉ rõ bước nào ôn lại ngày nào.

---

## Đọc theo thứ tự này

| # | File | Đọc khi nào | Trong đó có gì |
|---|---|---|---|
| 1 | **README.md** *(file này)* | Đầu buổi Zoom | Tổng quan · checkpoint · chấm điểm · luật |
| 2 | [01-challenge-brief.md](01-challenge-brief.md) | Lúc chọn track | Đề bài: bối cảnh, 6 track, 7 hạng mục bắt buộc, dữ liệu |
| 3 | [tracks/](tracks/README.md): **file của track nhóm chọn** | Ngay sau file 2 | Bối cảnh · người dùng · định hướng ý tưởng · data · công cụ gợi ý |
| 4 | [**02-guide.md**](02-guide.md) | **Mở suốt hai ngày** | Làm từng bước: câu hỏi phải trả lời → làm gì → ra file nào → nộp mốc nào |
| 5 | [03-rubric.md](03-rubric.md) | Trước mỗi checkpoint | Chấm từng phần thế nào |

Đi kèm:
- [starter-repo/](starter-repo/README.md): khung repo nộp bài. Có sẵn thư mục, file mẫu, và lệnh `run.py` chạy bộ câu thử và mô phỏng chi phí.
- [data/](01-challenge-brief.md#data): dữ liệu BTC cấp cho track A (EdTech). Track B–F nhóm tự tìm data.
- [further-reading/](further-reading/README.md): JTBD, phỏng vấn người dùng, HAX, PAIR, bảng giá model.

---

<a id="checkpoint"></a>
## CHECKPOINT

**Mỗi checkpoint, đội trưởng nộp 1 lần qua link nộp, thay cả nhóm**, cả 4 mốc dùng cùng một mã học viên.
- Đúng hạn và đủ phần → đủ điểm mốc. Muộn hoặc thiếu → 0 điểm mốc đó.
- Vẫn nộp phần đã có và khai thật phần còn thiếu.
- Tự soát trước khi nộp: bước guide ghi ở từng mốc.

<a id="cp1"></a>
### CP1 · 17:00 Thứ Sáu 27/11 · 3 điểm

**Lát cắt dự kiến ở CP1 (Track E, Canvas dòng 5 tại commit `9cef839`).** Khi người dùng chụp một hóa đơn, AI đọc ngày mua và số tiền thực trả rồi phân loại khoản chi để ứng dụng tự lưu khoản chi vào lịch, giúp người dùng xem tổng tiền và từng khoản theo ngày.

- `TEAMS.md` điền đủ thành viên + mã học viên, **đúng format** (đội trưởng ở dòng 1).
- Track (A–F) + bài toán của nhóm trong 1–2 câu: ai, đang làm gì, vướng ở đâu. Không viết chữ AI. Track F kèm thẻ đề.
- Lát cắt dự kiến (1 câu).
- Canvas 7 dòng (`canvas.md`).
- Link repo GitHub công khai, mở được bằng cửa sổ ẩn danh.

Tự soát: [guide 1.4](02-guide.md#b1-4) · **Link nộp CP1:** `________` *(BTC cập nhật)*

### CP2 · 19:30 Thứ Sáu 27/11 · 4 điểm

Nhóm thêm bước xem nhanh và bấm **Chốt** trước khi lưu khoản chi. [Canvas CP2](canvas.md)

- Canvas cập nhật + 1–3 dòng "đã đổi gì so với CP1".
- Nguồn bằng chứng đang làm (đào data / phỏng vấn / khảo sát) và đã làm đến đâu.
- Link `spec.md`, trong §4 có sơ đồ kiến trúc giải pháp.
- Link `eval/benchmark.csv`, ≥10 câu thử. Đã có `eval/metric_spec.yaml` và `data/DATA_CARD.md` bản đầu.
- **Chuẩn "đạt" bằng số**, chép từ `spec.md` §7. **Chốt tại mốc này, không sửa về sau.**
- Bản chạy thử dạng khung: `python run.py` đi hết luồng với AI giả.

Tự soát: [guide 2.5](02-guide.md#b2-5) · **Link nộp CP2:** `________` *(BTC cập nhật)*

### CP3 · 10:00 Thứ Bảy 28/11 · 4 điểm

- Bằng chứng pain đạt ngưỡng ở ≥1 nguồn + ≥5 trích dẫn / ví dụ nguyên văn. Link `evidence/summary.md`.
- Bộ câu thử 20–30 câu: ≥5 câu `kho`, ≥2 câu `tu_choi`.
- **Video 30 giây:** bản chạy thử gọi AI thật. YouTube để "Không công khai", hoặc Google Drive để "Bất kỳ ai có đường liên kết". Mở thử bằng cửa sổ ẩn danh.
- Kết quả lượt 1 (x/N câu đạt) + run ID.
- Link `spec.md` đã có §0–§7.
- Phần chưa xong, nếu có.

Tự soát: [guide 3.4](02-guide.md#b3-4) · **Link nộp CP3:** `________` *(BTC cập nhật)*

### CP4 · 14:30 Thứ Bảy 28/11 · 4 điểm

- Phòng demo + link repo.
- Tích 7 hạng mục bắt buộc đã có ([01-challenge-brief](01-challenge-brief.md#7-hang-muc)).
- Kết quả lượt 1 → lượt 2 (ví dụ 14/24 → 18/24).
- Chi phí / task thành công ở kịch bản cơ sở, kèm tên model.
- `demo-slides.pdf` ở thư mục gốc repo + link video demo dự phòng.
- Phần chưa xong, nếu có.

Tự soát: [guide 4.4](02-guide.md#b4-4) · **Link nộp CP4:** `________` *(BTC cập nhật)*

### Hạn chót · 23:59 Thứ Bảy 28/11 · không nộp form

Khoá repo bản cuối:
- Sửa theo góp ý ở buổi demo, mọi thay đổi sau 14:30 ghi vào `spec.md` §10.
- Mỗi người 1 file `reflection/`.

Hướng dẫn: [guide 5.3](02-guide.md#b5-3).

---

## Lịch hai ngày

| Khi nào | Ở đâu | Việc |
|---|---|---|
| Sáng Thứ Sáu 27/11 | Zoom | Khai mạc. **Sau buổi:** ghép nhóm · chọn track · nháp Canvas · hẹn người phỏng vấn / gửi khảo sát |
| 16:00–19:30 Thứ Sáu 27/11 | L3A: H209 + H210 · L3B: C401 | Làm tại lớp · **CP1 17:00** · **CP2 19:30** |
| Tối Thứ Sáu → 10:00 Thứ Bảy 28/11 | Nhóm tự làm | Nối model thật, nên xong trước khi ngủ · **CP3 10:00**. Sáng Thứ Bảy không có lớp |
| 14:00 Thứ Bảy 28/11 | L3A: H209 + H210 + H201 · L3B: C401 + E403 | Vào phòng · **CP4 14:30** |
| 14:30–16:00 | Theo zone | **Demo Zone:** mọi nhóm demo trong zone của mình |
| 16:00–18:00 | Cả phòng | **Demo Phòng:** các nhóm top của mỗi zone demo trước cả phòng |
| 23:59 Thứ Bảy 28/11 | — | **Hạn chót** |

---

## Chấm điểm

**100 = 15 điểm nộp (4 checkpoint) + 85 điểm chấm bài + 5 điểm bonus**, tổng tối đa 100.

| Phần | Điểm |
|---|---|
| Bằng chứng pain (data / phỏng vấn / khảo sát) | 14 |
| Impact có số | 11 |
| **Giải pháp AI: thiết kế + bản chạy thử** | **16** |
| Định nghĩa "tốt": bộ câu thử + metric | 14 |
| Báo cáo đánh giá | 8 |
| Mô phỏng chi phí khi dùng thật | 12 |
| Slide & demo | 10 |
| *Bonus:* người dùng thử | +5 |

- **Không xét giải** nếu thiếu: bản chạy thử gọi AI thật · bằng chứng pain ≥1 nguồn · bộ câu thử ≥20 câu có % đạt · slide PDF.
- **Kết quả thấp mà trung thực vẫn được đủ điểm.** Số bị sửa hoặc giấu (ví dụ đổi chuẩn "đạt" sau CP2, bỏ câu thử trượt) → phần đó 0 điểm.
- Chi tiết từng tiêu chí: [03-rubric.md](03-rubric.md).

## Thể thức và giải

Công bố sau.

---

## Luật chung

1. **Dùng AI để build thoải mái**, nhưng mỗi người phải giải thích được phần có tên mình. Không giải thích được thì phần đó 0 điểm. Ghi 2–3 dòng "dùng AI vào việc gì" trong `docs/ai-usage.md`.
2. **Chuẩn "đạt" chốt tại CP2**, giữ nguyên đến hạn chót.
3. **Sau CP4** được sửa code, báo cáo, slide, và ghi changelog (`spec.md` §10). **Không** sửa chuẩn "đạt", câu thử trong bộ, số liệu bằng chứng, kết quả các lượt đã chạy. Chạy thêm thì ghi thành lượt mới.
4. **Giải** xét trên bản CP4 + phần demo. **Điểm lab** chấm trên commit cuối trước 23:59 Thứ Bảy 28/11.
5. **Đổi track** được trước CP2: báo lab coach và ghi trong lần nộp CP2. Sau CP2 chỉ được thu hẹp lát cắt.
6. **Không commit API key** (để trong `.env`). Repo có API key hoặc dữ liệu cá nhân thật → **trừ 10 điểm**, gỡ ngay. Thông tin thành viên trong `TEAMS.md` là bắt buộc, không tính vào lỗi này. Luật dùng dữ liệu: [01-challenge-brief → Dữ liệu](01-challenge-brief.md#data).

## Nộp bài

1. **Tạo repo công khai, chép thư mục [starter-repo/](starter-repo/README.md) vào.**
2. **Tên repo:** `K5-Day15-<lớp>-<tên nhóm>`, ví dụ `K5-Day15-L3A-StudyPulse`. Tên nhóm viết liền, không dấu.
3. **Kiểm công khai:** mở link repo bằng cửa sổ ẩn danh, mở được mới đúng.
4. **`TEAMS.md` ở thư mục gốc repo:** ghi đầy đủ thành viên, mã học viên, vai trò, phần việc, theo đúng mẫu có sẵn trong [starter-repo/TEAMS.md](starter-repo/TEAMS.md). **Khi chấm và đánh giá, BTC quét file này để ghép điểm cho từng người, nên phải làm đúng format.** Kiểm bằng `python run.py check`.

## Kẹt thì hỏi ai

- Tại lớp (chiều Thứ Sáu, buổi demo Thứ Bảy): **lab coach của zone**.
- Ngoài giờ lớp, kể cả sáng Thứ Bảy: kênh hỗ trợ, BTC thông báo lúc khai mạc.
- Kẹt kỹ thuật quá **20 phút** thì hỏi ngay, đừng ngồi một mình.
- Câu hỏi hay gặp: [02-guide → Hỏi nhanh](02-guide.md#hoi-nhanh).

---

**Đọc tiếp:** [01-challenge-brief.md](01-challenge-brief.md) → chọn track ở [tracks/](tracks/README.md) → làm theo [02-guide.md](02-guide.md).
