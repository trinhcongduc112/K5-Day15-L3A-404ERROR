"""Luồng văn bản OCR và báo cáo dùng chung công cụ tính số của SkyBill."""
import datetime as dt
import hashlib
import io
import json
import re
from pathlib import Path

from PIL import Image, ImageOps

from ai import call_model, call_model_image
from document_ocr import DateValuePattern, normalize_receipt_date, parse_vnd_amount, receipt_has_sensitive_text
import storage
import tools
from tracing import note

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "expenses.json"
RECEIPT_INPUT = re.compile(r"^(chụp (?:hóa|hoá) đơn|(?:hóa|hoá) đơn:|gửi ảnh)", re.IGNORECASE)
PERIOD_KEYS = {
    "week": re.compile(r"\b\d{4}-W\d{2}\b", re.IGNORECASE),
    "month": re.compile(r"\b\d{4}-\d{2}\b(?![-\d])"),
    "year": re.compile(r"\bnăm\s+(\d{4})\b"),
}
PERIOD_LABELS = {"week": "tuần", "month": "tháng", "year": "năm"}


def _money(amount):
    return f"{amount:,}".replace(",", ".") + "đ"


def _blocked(text):
    low = text.casefold()
    if receipt_has_sensitive_text(text):
        return "Từ chối xử lý thông tin bảo mật. Hãy che mã OTP, mật khẩu, số thẻ hoặc mã PIN trước khi gửi."
    if re.search(r"cổ phiếu|chứng khoán|\bcoin\b|crypto|bitcoin|tiền ảo|đầu tư|trái phiếu|lãi suất|vay tiền|ngoại hối", low):
        return "Từ chối tư vấn đầu tư. SkyBill có thể giúp bạn xem lại chi tiêu đã ghi."
    if re.search(r"người (?:dùng )?khác|của bạn tôi|của sếp|của anh ấy|của chị ấy|bỏ qua mọi quy tắc|xuất (?:cho tôi )?toàn bộ", low):
        return "Từ chối truy cập hay xuất nhật ký chi tiêu của người khác."
    if re.search(r"ghi khống|thao túng|(?:ép|giả|sai sự thật).*(?:0\s*(?:đ|đồng)|báo cáo)", low):
        return "Từ chối thao túng số liệu hoặc ghi khống khoản chi. Chưa ghi khoản chi."
    return ""


def _receipt_details(receipt):
    source = " (ngày chụp)" if receipt.get("date_source") == "ngày chụp" else ""
    amount = receipt.get("total", receipt.get("printed_total"))
    return f"ngày {receipt['date']}{source}: {receipt['merchant']} · {_money(amount)} · nhóm {receipt['category']}."


def choose_category(receipt_text: str) -> str:
    """Quy tắc chọn nhóm chi dùng chung cho web (ảnh OCR) và answer() (văn bản).

    Code lọc nhóm có từ khoá làm căn cứ; model chỉ chọn trong danh sách đó, không tự đặt nhóm mới.
    """
    candidates = tools.receipt_categories(receipt_text)
    if not candidates:
        return "không rõ"
    menu = "\n".join(f"{number}. {name}" for number, name in enumerate(candidates, start=1))
    choice = call_model(
        "Chọn nhóm chi đúng với hóa đơn. Chỉ trả đúng số thứ tự trong danh sách.",
        f"Nội dung hóa đơn:\n{receipt_text}\nNhóm có căn cứ:\n{menu}",
    )["text"].strip()
    return {str(index): name for index, name in enumerate(candidates, start=1)}.get(choice, candidates[0])


RECEIPT_IMAGE_PROMPT = (
    "Bạn đọc ảnh hóa đơn tiếng Việt (có thể xoay ngang hoặc là phiếu POS ngân hàng). "
    "Chỉ trả một đối tượng JSON, không giải thích:\n"
    '{"merchant": tên cửa hàng hoặc "", "date": "YYYY-MM-DD" in trên hóa đơn hoặc "", '
    '"paid_total": tổng phải thanh toán (số nguyên VND) hoặc 0, "uncertain": true/false}\n'
    "paid_total lấy ở dòng Tổng cộng / Tổng tiền phải thanh toán / Tổng số thanh toán / Thanh toán / "
    "Cộng tiền hàng / Thành công (chấp nhận số dính ký hiệu tiền như VND229,869 hoặc VNĐ 229.869). "
    "KHÔNG lấy tiền khách đưa, tiền khách trả, tiền thừa, tiền trả lại, tiền đã giảm/chiết khấu, mã số, số điện thoại. "
    "Nếu ngày trên hóa đơn bị mờ, thiếu hoặc năm bất hợp lý, trả date=\"\" để dùng ngày chụp. "
    "Đặt uncertain=true và paid_total=0 khi số thực trả bị mờ, bị che, hoặc có nhiều mức tổng mâu thuẫn. "
    "Không đoán số không nhìn thấy trên ảnh."
)


def _digits_seen_in_ocr(ocr_text: str) -> set[int]:
    """Các số tiền có mặt trong chữ OCR (chấp nhận 35,500 · 35.500 · 35 500 · 35500)."""
    found = set()
    for token in re.findall(r"\d{1,3}(?:[., ]\d{3})+|\d{4,9}", ocr_text):
        found.add(int(re.sub(r"\D", "", token)))
    return found


def _shrink_image(image_bytes: bytes, max_side: int = 1600) -> bytes:
    """Thu ảnh về cạnh dài ≤1600px, JPEG, để giảm token ảnh gửi model."""
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def read_receipt_image(scan: dict, image_bytes: bytes, capture_date: str) -> dict:
    """Model "cứu" ảnh mà OCR cục bộ chưa đọc ra số thực trả; code kiểm số đó có thật trên ảnh.

    - Ảnh không đạt chất lượng (mờ/lóa) hoặc đã bị chặn: giữ nguyên kết quả OCR, không gọi model.
    - OCR cục bộ ONNX đã đọc ra tổng chắc chắn: không gọi model.
    - Số model đọc phải trùng tổng OCR cục bộ đọc được; nếu OCR chưa đọc ra tổng thì số đó phải
      xuất hiện trong chữ OCR của chính ảnh. Không thỏa → Cần đọc lại.
    - Ngày sau ngày chụp → Cần đọc lại. Không có ngày → dùng ngày chụp.
    Hàm không ghi sổ; chỉ người dùng bấm Chốt mới ghi.
    """
    if scan.get("blocked") or scan.get("quality_report", {}).get("quality_status") == "fail":
        return scan
    # Rẻ + chính xác: OCR cục bộ đã đọc ra tổng chắc chắn thì không gọi model (đo trên 40 ảnh mẫu:
    # gọi model cho mọi ảnh không bắt thêm lỗi nào mà còn đẩy 3 ảnh đúng sang Cần đọc lại).
    if scan.get("printed_total") and not scan.get("is_uncertain"):
        note("OCR cục bộ đủ căn cứ, không gọi model đọc ảnh")
        return scan
    try:
        reply = call_model_image("Trích dữ liệu hóa đơn thành JSON.", RECEIPT_IMAGE_PROMPT, _shrink_image(image_bytes))["text"]
        fields = json.loads(re.search(r"\{.*\}", reply, re.DOTALL)[0])
    except (NotImplementedError, RuntimeError, TypeError, ValueError, OSError) as error:
        note(f"Model chưa đọc được ảnh, giữ kết quả OCR cục bộ: {type(error).__name__}")
        return scan

    ocr_text = "\n".join(row["text"] for row in scan.get("logical_rows", []))
    total = fields.get("paid_total")
    total = total if type(total) is int and total > 0 else 0
    ocr_total = scan.get("printed_total") or 0
    # OCR cục bộ đã đọc được tổng mà model đọc số khác → mâu thuẫn, không chọn hộ người dùng.
    grounded = bool(total) and (total == ocr_total if ocr_total else total in _digits_seen_in_ocr(ocr_text))
    date = normalize_receipt_date(str(fields.get("date") or ""))
    future = bool(date and date > capture_date)
    if total and not grounded:
        note(f"Số model đọc ({total}) không có trong chữ OCR của ảnh → Cần đọc lại")
    merchant = str(fields.get("merchant") or "").strip()
    scan_date = scan.get("date") or ""
    valid_scan_date = scan_date if (scan_date and scan_date <= capture_date) else ""
    chosen_date = date or valid_scan_date or capture_date
    chosen_date_source = (
        "hóa đơn"
        if (date or (scan.get("date_source") == "hóa đơn" and chosen_date == valid_scan_date))
        else "ngày chụp"
    )
    return {
        **scan,
        "merchant": merchant or scan.get("merchant") or "không rõ",
        "date": chosen_date,
        "date_source": chosen_date_source,
        "printed_total": total if grounded else 0,
        "is_uncertain": bool(fields.get("uncertain")) or not grounded or future,
        "ocr_engine": f"{scan.get('ocr_engine')} + model đọc ảnh",
    }


def _confirm_receipt(draft, ledger):
    if draft is None:
        return "Chưa có hóa đơn để Chốt."
    payload = {"draft_id": draft["draft_id"], "total": draft.get("total", draft["printed_total"]), "category": draft["category"]}
    try:
        record, duplicate = tools.confirm_receipt(payload, ledger)
    except ValueError as error:
        return str(error)
    status = "Khoản đã có, không ghi trùng" if duplicate else "Đã Chốt và lưu khoản chi"
    summary = tools.get_day_summary("default_user", record["date"], storage.LoadReceiptRecords(ledger=ledger))
    return (
        f"{status} {_receipt_details(record)} Tổng chi ngày {record['date']}: "
        f"{_money(summary['total_spend'])} ({summary['receipt_count']} khoản)."
    )


def _edit_receipt(pending, field, value):
    if pending is None:
        return {"output": "Chưa có bản xem nhanh để sửa."}
    receipt = pending.copy()
    if field == "tiền":
        amount = parse_vnd_amount(value)
        if not amount:
            return {"output": "Số tiền chưa hợp lệ. Nhập theo mẫu Sửa tiền: 55.000đ."}
        receipt["total"] = amount
    else:
        categories = (*tools.StandardCategories, "không rõ")
        category = next((c for c in categories if c.casefold() == value.casefold()), None)
        if category is None:
            return {"output": "Chọn một nhóm chi: " + ", ".join(categories) + "."}
        receipt["category"] = category
    return {"output": f"Đã sửa bản xem nhanh {_receipt_details(receipt)} Chọn Chốt để lưu.", "pending_receipt": receipt}


def _previous_period(kind, key):
    if kind == "year":
        return str(int(key) - 1)
    if kind == "month":
        start = dt.date.fromisoformat(key + "-01")
        return (start - dt.timedelta(days=1)).isoformat()[:7]
    start = dt.date.fromisoformat(key + "-1")
    year, week, _ = (start - dt.timedelta(days=7)).isocalendar()
    return f"{year:04d}-W{week:02d}"


def _report_period(kind, key, compare_key, records):
    label = PERIOD_LABELS[kind]
    try:
        if compare_key:
            comparison = tools.compare_periods("default_user", kind, key, compare_key, records)
            current, previous = comparison["current"], comparison["previous"]
        else:
            current = tools.aggregate_period("default_user", kind, key, records)
            previous = None
    except (ValueError, OverflowError):
        return "Mốc tuần, tháng hoặc năm chưa hợp lệ."

    if not current["receipt_count"]:
        return f"Chưa có dữ liệu chi tiêu {label} {key}."
    total = _money(current["total_spend"])
    if previous is not None:
        if not previous["receipt_count"]:
            return f"{label.title()} {key} tổng chi {total}. Chưa có dữ liệu {compare_key} để so sánh."
        delta = comparison["delta_amount"]
        difference = ("tăng +" if delta > 0 else "giảm " if delta < 0 else "giữ nguyên ") + _money(abs(delta))
        return f"So sánh {label} {key} với {compare_key}: {key} chi {total}, {compare_key} chi {_money(previous['total_spend'])}. Chi tiêu {difference}."

    categories = current["categories"][:4]
    peak = current["peak_day"]
    report = (
        f"Chi tiêu {label} {key}: tổng {total} qua {current['receipt_count']} khoản. "
        + "Các nhóm chi: " + ", ".join(f"{row['category']} ({_money(row['amount'])})" for row in categories)
        + f". Ngày chi cao nhất: {peak['date']} ({_money(peak['total'])})."
    )
    # Model chọn một hướng phân tích. Văn bản hiển thị vẫn dùng số liệu từ công cụ.
    options = {
        "NHOM": f"Có thể mở nhóm {categories[0]['category']} để xem các khoản chi lớn nhất.",
        "NGAY": f"Có thể mở ngày {peak['date']} để xem chi tiết các khoản chi trong ngày đó.",
    }
    choice = call_model(
        "Bạn chọn một gợi ý điều hướng cho báo cáo chi tiêu. Chỉ trả đúng NHOM hoặc NGAY.",
        f"Câu hỏi: {label} {key}. Nhóm cao nhất: {categories[0]}. Ngày cao nhất: {peak}.",
    )["text"].strip().upper()
    return report + (" " + options[choice] if choice in options else "")


def _report(text, records):
    low = text.casefold()
    today = dt.date.today()
    date_match = DateValuePattern.search(low)
    date = normalize_receipt_date(date_match[1]) if date_match else ""
    if date_match and not date:
        return "Ngày chưa hợp lệ. Hãy cho biết ngày theo YYYY-MM-DD."
    if "hôm nay" in low:
        date = today.isoformat()
    elif "hôm qua" in low:
        date = (today - dt.timedelta(days=1)).isoformat()
    if date:
        day = tools.get_day_summary("default_user", date, records)
        lines = [f"- {row['merchant']} ({row['category']}): {_money(row['total'])}" for row in day["receipts"]]
        if any(row["category"].casefold() == "không rõ" for row in day["receipts"]):
            lines.append("Bạn có thể gắn lại nhóm cho khoản chưa phân loại trong lịch.")
        return f"Chi tiêu ngày {date}: {_money(day['total_spend'])} ({day['receipt_count']} khoản)." + (
            "\n" + "\n".join(lines) if lines else " Chưa ghi nhận khoản chi nào."
        )

    for kind, pattern in PERIOD_KEYS.items():
        keys = [key.upper() for key in pattern.findall(low)]
        if kind == "month" and not keys:
            keys = [f"{year or today.year}-{int(month):02d}" for month, year in re.findall(r"tháng\s+(\d{1,2})(?:\s*(?:/|năm)\s*(\d{4}))?\b(?!\d)", low)]
        label = PERIOD_LABELS[kind]
        if not keys and (f"{label} này" in low or f"{label} nay" in low or f"{label} trước" in low):
            key = {"week": today.strftime("%G-W%V"), "month": today.strftime("%Y-%m"), "year": str(today.year)}[kind]
            keys = [_previous_period(kind, key) if f"{label} trước" in low else key]
        if keys:
            try:
                previous = keys[1] if len(keys) > 1 else _previous_period(kind, keys[0]) if "so sánh" in low or "kỳ trước" in low else None
            except (ValueError, OverflowError):
                return "Mốc tuần, tháng hoặc năm chưa hợp lệ."
            return _report_period(kind, keys[0], previous, records)
    return "Bạn muốn xem chi tiêu ngày hay tháng nào? Hãy cho biết ngày, tuần ISO, tháng hoặc năm cụ thể."


def answer(text: str, *, live: bool = False, pending_receipt: dict | None = None, allow_receipt: bool = True) -> dict:
    """Dùng sổ CSDL khi live=True, hoặc sổ seed mới cho mỗi câu eval/simulate."""
    text = text.strip()
    blocked = _blocked(text)
    if blocked:
        note("Từ chối trước khi gọi model hoặc ghi sổ")
        return {"output": blocked, "pending_receipt": None}
    ledger = None
    if not live:
        with FIXTURE.open(encoding="utf-8") as file:
            ledger = storage.EvaluationLedger(json.load(file)["records"])
    if not allow_receipt:
        if RECEIPT_INPUT.match(text) or text.casefold() == "chốt":
            return {"output": "Mở tab Chụp HĐ để đọc hóa đơn và xem nhanh trước khi Chốt."}
        return {"output": _report(text, storage.LoadReceiptRecords(ledger=ledger))}
    if text.casefold() == "chốt":
        return {"output": _confirm_receipt(pending_receipt, ledger), "pending_receipt": None}
    edit = re.fullmatch(r"sửa\s+(tiền|nhóm)\s*:\s*(.+)", text, flags=re.IGNORECASE)
    if edit:
        return _edit_receipt(pending_receipt, edit[1].casefold(), edit[2].strip())
    if not RECEIPT_INPUT.match(text):
        return {"output": _report(text, storage.LoadReceiptRecords(ledger=ledger))}

    receipt_text, separator, action = text.rpartition("\n")
    confirm = bool(not live and separator and action.strip().casefold() == "chốt")
    receipt_text = receipt_text if confirm else text
    receipt = tools.parse_receipt_text(receipt_text, dt.date.today().isoformat() if live else None)
    receipt["capture_id"] = receipt.get("capture_id") or hashlib.sha256(receipt_text.casefold().encode()).hexdigest()
    receipt["printed_total"] = receipt.pop("total")
    receipt["source"] = "ocr_text"
    receipt.pop("category_candidates")
    readable = receipt["date"] and receipt["printed_total"] and not receipt["is_uncertain"]
    receipt["category"] = choose_category(receipt_text) if readable else "không rõ"
    validation, draft = tools.prepare_receipt(receipt, ledger)
    if draft is None:
        labels = {"date": "ngày hợp lệ", "paid_total": "số tiền thực trả"}
        missing = ", ".join(labels[field] for field in validation["missing_fields"])
        return {"output": f"Cần đọc lại hóa đơn: {missing or 'dữ liệu chưa đủ căn cứ'}. Chưa ghi khoản chi. Hãy chụp lại.", "pending_receipt": None}
    preview = f"Xem nhanh {_receipt_details(draft)} Chưa ghi khoản chi. Chọn Chốt để lưu."
    if confirm:
        return {"output": preview + "\n" + _confirm_receipt(draft, ledger), "pending_receipt": None}
    return {"output": preview, "pending_receipt": draft}
