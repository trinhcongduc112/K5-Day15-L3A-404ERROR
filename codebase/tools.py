"""Các công cụ nghiệp vụ của SkyBill khớp spec.md §4 (bản chạy thử Track E).

Mỗi công cụ đều dùng @tool từ tracing.py và có docstring đủ 4 ý:
    tên · input · output · có tác động ra ngoài không.
Toàn bộ phép cộng, lọc, tổng hợp, so sánh kỳ chạy 100% bằng code trên CSDL/receipts.json.
"""

import calendar
import datetime
import hashlib
import re

from document_ocr import DateValuePattern, normalize_receipt_date, read_paid_total, receipt_has_sensitive_text
import storage as StorageModule
from tracing import tool, TOOLS  # noqa: F401

CATEGORY_KEYWORDS = {
    "Ăn uống": ("highlands", "cà phê", "ca phe", "phin", "trà sữa", "tra sua", "cơm", "com", "phở", "pho", "bún", "bun", "bánh", "banh", "ăn", "an", "bach hoa xanh", "nước", "nuoc"),
    "Di chuyển": ("grab", "xanh sm", "be ", "xăng", "xang", "xe ", "taxi", "gửi xe", "gui xe", "cuốc", "cuoc"),
    "Mua sắm": ("circle k", "siêu thị", "sieu thi", "áo", "ao", "quần", "quan", "giày", "giay", "shopee", "lazada", "nồi", "noi"),
    "Hóa đơn & Nhà ở": ("tiền trọ", "tien tro", "tiền phòng", "tien phong", "điện", "dien", "nước sinh hoạt", "internet", "wifi"),
    "Sức khỏe": ("thuốc", "thuoc", "khám", "kham", "vitamin", "bệnh viện", "benh vien", "nhà thuốc", "nha thuoc"),
    "Giải trí": ("phim", "rạp", "rap", "sách", "sach", "vé", "ve ", "game", "nhạc", "nhac"),
}
# Danh sách nhóm chuẩn duy nhất (khớp data/expenses.json, bộ câu thử và giao diện web).
StandardCategories = [*CATEGORY_KEYWORDS, "Khác"]


def receipt_categories(text: str) -> list[str]:
    low = (text or "").lower()
    return [
        cat for cat, kws in CATEGORY_KEYWORDS.items()
        if any(re.search(r'(?<!\w)' + re.escape(k.strip()) + r'(?!\w)', low) for k in kws)
    ]


@tool
def parse_receipt_text(raw_input: str, capture_date: str | None = None) -> dict:
    """Kiểm văn bản hóa đơn mô phỏng OCR; nhận chuỗi và ngày chụp, trả ngày, tiền, nhóm và lỗi. Chỉ đọc."""
    text = raw_input.strip()
    low = text.lower()
    capture_id = re.search(r"(?:mã lượt chụp|capture_id)\s*:\s*([a-zA-Z0-9_-]+)", text, flags=re.IGNORECASE)
    capture_marker = re.search(r"ngày chụp\s*:\s*(20\d{2}-\d{2}-\d{2})", low)
    receipt_text = re.sub(r"ngày chụp\s*:\s*20\d{2}-\d{2}-\d{2}", "", text, flags=re.IGNORECASE)
    date_match = DateValuePattern.search(receipt_text)
    fallback = normalize_receipt_date(capture_marker[1] if capture_marker else capture_date)
    chosen_date = normalize_receipt_date(date_match[1]) if date_match else fallback

    merchant = re.sub(
        r"^(?:chụp|gửi ảnh)?\s*hóa đơn(?: bị [^:]+)?\s*:\s*",
        "", text.split("|", 1)[0].splitlines()[0] if text else "", flags=re.IGNORECASE,
    ).strip()
    if not merchant or merchant.lower().startswith(("tổng", "ngày", "gửi ảnh hóa đơn", "hóa đơn")):
        merchant = "Không rõ"

    return {
        "merchant": merchant,
        "capture_id": capture_id.group(1).upper() if capture_id else None,
        "date": chosen_date,
        "date_source": "hóa đơn" if date_match else "ngày chụp",
        "total": read_paid_total(re.split(r"[|\n]", receipt_text)),
        "is_uncertain": "bị mờ" in low or bool(chosen_date and fallback and chosen_date > fallback),
        "category_candidates": receipt_categories(receipt_text),
    }



def _CalculateWeekBounds(AnchorDateIso: str) -> tuple:
    """Tính ngày đầu tuần (Thứ Hai) và cuối tuần (Chủ Nhật) cho mốc ngày YYYY-MM-DD."""
    AnchorDateObj = datetime.date.fromisoformat(AnchorDateIso)
    WeekdayOffset = AnchorDateObj.weekday()
    StartDateObj = AnchorDateObj - datetime.timedelta(days=WeekdayOffset)
    EndDateObj = StartDateObj + datetime.timedelta(days=6)
    return StartDateObj.isoformat(), EndDateObj.isoformat()


def _ResolvePeriodBounds(PeriodType: str, PeriodKey: str) -> tuple:
    """Quy đổi (PeriodType, PeriodKey) thành (StartIso, EndIso, PeriodLabel)."""
    NormalizedType = str(PeriodType or "month").strip().lower()
    CleanKey = str(PeriodKey or "").strip()

    if NormalizedType == "week":
        AnchorDate = datetime.date.fromisoformat(CleanKey + "-1").isoformat() if "-W" in CleanKey else (
            CleanKey or datetime.date.today().isoformat()
        )
        StartIso, EndIso = _CalculateWeekBounds(AnchorDate)
        return StartIso, EndIso, "Tuần %s → %s" % (StartIso, EndIso)

    if NormalizedType == "year":
        TargetYear = int(CleanKey[:4]) if len(CleanKey) >= 4 and CleanKey[:4].isdigit() else datetime.date.today().year
        return "%04d-01-01" % TargetYear, "%04d-12-31" % TargetYear, "Năm %04d" % TargetYear

    # Mặc định: month (chấp nhận YYYY-MM hoặc YYYY-MM-DD)
    if len(CleanKey) >= 7 and CleanKey[:4].isdigit() and CleanKey[5:7].isdigit():
        TargetYear = int(CleanKey[:4])
        TargetMonth = int(CleanKey[5:7])
    else:
        TodayDate = datetime.date.today()
        TargetYear = TodayDate.year
        TargetMonth = TodayDate.month
    LastDayOfMonth = calendar.monthrange(TargetYear, TargetMonth)[1]
    StartIso = "%04d-%02d-01" % (TargetYear, TargetMonth)
    EndIso = "%04d-%02d-%02d" % (TargetYear, TargetMonth, LastDayOfMonth)
    return StartIso, EndIso, "Tháng %02d/%04d" % (TargetMonth, TargetYear)


@tool
def validate_receipt(ReceiptPayload: dict, ledger: StorageModule.EvaluationLedger | None = None) -> dict:
    """validate_receipt: Kiểm tra số học, trường thiếu và trùng lặp của hoá đơn trích xuất.
    Input: ReceiptPayload (dict). Output: dict {valid, missing_fields, total_mismatch, duplicate_flag, warnings, calculated_total}. Không tác động ra ngoài."""
    MissingFields = []
    WarningsList = []

    ReceiptDate = str(ReceiptPayload.get("date") or "").strip()
    LineItems = ReceiptPayload.get("items") or []
    PrintedTotal = int(round(float(ReceiptPayload.get("printed_total") or 0)))

    if not normalize_receipt_date(ReceiptDate):
        MissingFields.append("date")
    if PrintedTotal <= 0:
        MissingFields.append("paid_total")
        WarningsList.append("Chưa xác định được số tiền thực trả. Hãy chụp lại phần thanh toán.")

    CalculatedTotal = sum(int(LineItem.get("price") or 0) for LineItem in LineItems)
    TotalMismatch = PrintedTotal > 0 and CalculatedTotal > 0 and PrintedTotal != CalculatedTotal
    if TotalMismatch:
        WarningsList.append(
            "Tổng các món (%s đ) lệch với tổng in trên hoá đơn (%s đ)."
            % (format(CalculatedTotal, ","), format(PrintedTotal, ","))
        )

    QualityReport = ReceiptPayload.get("quality_report") or {}
    if QualityReport.get("quality_status") == "fail":
        WarningsList.append(
            "Ảnh hoá đơn chưa đạt chất lượng (%s) — khuyến nghị kiểm tra hoặc chụp lại."
            % ", ".join(QualityReport.get("reasons") or ["LOW_QUALITY"])
        )

    capture_id = str(ReceiptPayload.get("capture_id") or "").casefold()
    ExistingReceipts = StorageModule.LoadReceiptRecords(str(ReceiptPayload.get("user_id") or "default_user"), ledger)
    DuplicateFlag = bool(capture_id and any(
        str(record.get("capture_id") or "").casefold() == capture_id for record in ExistingReceipts
    ))
    if DuplicateFlag:
        WarningsList.append("Mã lượt chụp đã có trong sổ. Chốt lại sẽ giữ nguyên tổng.")

    IsValid = not (MissingFields or ReceiptPayload.get("is_uncertain") or QualityReport.get("quality_status") == "fail")
    return {
        "valid": IsValid,
        "missing_fields": MissingFields,
        "total_mismatch": TotalMismatch,
        "duplicate_flag": DuplicateFlag,
        "warnings": WarningsList,
        "calculated_total": CalculatedTotal,
        "printed_total": PrintedTotal,
    }


@tool
def draft_save_receipt(ReceiptPayload: dict, ledger: StorageModule.EvaluationLedger | None = None) -> dict:
    """draft_save_receipt: Tạo bản nháp hoá đơn chờ người dùng xác nhận lưu vào sổ ngày.
    Input: hóa đơn đã kiểm và sổ tạm nếu có. Output: dict bản nháp DRAFT_PENDING_USER. Chỉ ghi bản nháp chờ người duyệt."""
    capture_id = ReceiptPayload["capture_id"].casefold()
    draft_id = "DRAFT-" + hashlib.sha256(capture_id.encode()).hexdigest()[:24]
    LineItems = ReceiptPayload.get("items") or []
    CalculatedTotal = sum(int(round(float(LineItem.get("price") or 0))) for LineItem in LineItems)
    QualityReport = ReceiptPayload.get("quality_report") or {}

    DraftRecord = {
        "draft_id": draft_id,
        "status": "DRAFT_PENDING_USER",
        "requires_user_approval": True,
        "user_id": ReceiptPayload.get("user_id") or "default_user",
        "date": ReceiptPayload["date"],
        "date_source": ReceiptPayload.get("date_source") or "ngày chụp",
        "capture_id": capture_id,
        "merchant": str(ReceiptPayload.get("merchant") or "không rõ").strip(),
        "category": str(ReceiptPayload.get("category") or "không rõ").strip(),
        "source": str(ReceiptPayload.get("source") or "camera"),
        "note": str(ReceiptPayload.get("note") or "").strip(),
        "image_path": str(ReceiptPayload.get("image_path") or ""),
        "items": [
            {
                "name": str(LineItem.get("name") or "").strip(),
                "price": int(round(float(LineItem.get("price") or 0))),
            }
            for LineItem in LineItems
        ],
        "calculated_total": CalculatedTotal,
        "printed_total": int(round(float(ReceiptPayload.get("printed_total") or 0))),
        "ocr_engine": str(ReceiptPayload.get("ocr_engine") or ""),
        "quality_score": QualityReport.get("overall_score"),
        "manual_entry": bool(ReceiptPayload.get("manual_entry")),
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    StorageModule.UpsertDraftRecord(DraftRecord, ledger)
    return DraftRecord


def prepare_receipt(payload: dict, ledger: StorageModule.EvaluationLedger | None = None, *, image: tuple | None = None):
    """Kiểm lần chụp trước khi cho web hoặc answer() xem bản nháp có thể Chốt."""
    validation = validate_receipt(payload, ledger)
    if not validation["valid"]:
        return validation, None
    if image is not None:
        image_bytes, extension = image
        image_id = hashlib.sha256(image_bytes).hexdigest()
        path = StorageModule.SaveReceiptImage(image_bytes, extension, payload["date"], image_id)
        payload = {**payload, "image_path": path}
    return validation, draft_save_receipt(payload, ledger)


def prepare_manual_receipt(payload: dict, ledger: StorageModule.EvaluationLedger | None = None, *, image: tuple | None = None):
    """Ảnh không chắc số thực trả (Cần đọc lại): lưu ảnh và bản nháp không có số tiền.
    AI không đoán số; người dùng tự gõ số thực trả rồi mới Chốt được."""
    if payload.get("blocked") or not payload.get("capture_id") or not normalize_receipt_date(str(payload.get("date") or "")):
        return None
    if image is not None:
        image_bytes, extension = image
        path = StorageModule.SaveReceiptImage(image_bytes, extension, payload["date"], hashlib.sha256(image_bytes).hexdigest())
        payload = {**payload, "image_path": path}
    return draft_save_receipt(
        {**payload, "printed_total": 0, "items": [], "category": "không rõ", "manual_entry": True}, ledger
    )


@tool
def confirm_receipt(payload: dict, ledger: StorageModule.EvaluationLedger | None = None) -> tuple[dict, bool]:
    """Input: bản nháp và chỉnh sửa đã duyệt. Output: khoản đã ghi và cờ trùng. Chỉ ghi khi người dùng Chốt."""
    if receipt_has_sensitive_text(" ".join(str(payload.get(key) or "") for key in ("merchant", "category", "note"))):
        raise ValueError("Hãy bỏ thông tin bảo mật trước khi Chốt.")
    return StorageModule.ConfirmDraftToLedger(payload, ledger)


@tool
def get_day_summary(UserId: str, TargetDate: str, records: list | None = None) -> dict:
    """get_day_summary: Đọc và tổng kết hoá đơn của một ngày cụ thể từ CSDL bằng code.
    Input: UserId (str), TargetDate (str YYYY-MM-DD). Output: dict số hoá đơn, danh sách chi tiết, tổng tiền và bảng theo danh mục. Không tác động ra ngoài."""
    AllReceipts = StorageModule.LoadReceiptRecords(UserId) if records is None else records
    DayReceipts = [ReceiptItem for ReceiptItem in AllReceipts if ReceiptItem.get("date") == TargetDate]
    DayTotal = sum(int(ReceiptItem.get("total") or 0) for ReceiptItem in DayReceipts)

    CategoryTotals = {}
    for ReceiptItem in DayReceipts:
        CategoryName = str(ReceiptItem.get("category") or "Khác")
        CategoryTotals[CategoryName] = CategoryTotals.get(CategoryName, 0) + int(ReceiptItem.get("total") or 0)

    CategoryBreakdown = [
        {
            "category": CategoryName,
            "amount": AmountValue,
            "share_pct": round((AmountValue / float(DayTotal)) * 100.0, 1) if DayTotal > 0 else 0.0,
        }
        for CategoryName, AmountValue in sorted(CategoryTotals.items(), key=lambda PairItem: PairItem[1], reverse=True)
    ]

    return {
        "date": TargetDate,
        "receipt_count": len(DayReceipts),
        "total_spend": DayTotal,
        "category_breakdown": CategoryBreakdown,
        "receipts": DayReceipts,
    }


@tool
def aggregate_period(UserId: str, PeriodType: str, PeriodKey: str, records: list | None = None) -> dict:
    """aggregate_period: Tổng hợp chi tiêu theo tuần, tháng hoặc năm bằng code từ CSDL.
    Input: UserId (str), PeriodType ('week'|'month'|'year'), PeriodKey (str). Output: dict tổng chi, số hoá đơn, tỷ trọng danh mục và top khoản chi. Không tác động ra ngoài."""
    StartIso, EndIso, PeriodLabel = _ResolvePeriodBounds(PeriodType, PeriodKey)
    AllReceipts = StorageModule.LoadReceiptRecords(UserId) if records is None else records
    PeriodReceipts = [
        ReceiptItem
        for ReceiptItem in AllReceipts
        if StartIso <= str(ReceiptItem.get("date") or "") <= EndIso
    ]

    TotalSpend = sum(int(ReceiptItem.get("total") or 0) for ReceiptItem in PeriodReceipts)
    day_totals = {}

    CategoryTotals = {CategoryName: 0 for CategoryName in StandardCategories}
    for ReceiptItem in PeriodReceipts:
        CategoryName = str(ReceiptItem.get("category") or "Khác")
        if CategoryName not in CategoryTotals:
            CategoryTotals[CategoryName] = 0
        amount = int(ReceiptItem.get("total") or 0)
        CategoryTotals[CategoryName] += amount
        day = ReceiptItem["date"]
        day_totals[day] = day_totals.get(day, 0) + amount

    CategorySummary = [
        {
            "category": CategoryName,
            "amount": AmountValue,
            "share_pct": round((AmountValue / float(TotalSpend)) * 100.0, 1) if TotalSpend > 0 else 0.0,
        }
        for CategoryName, AmountValue in sorted(CategoryTotals.items(), key=lambda PairItem: PairItem[1], reverse=True)
        if AmountValue > 0
    ]

    TopExpenses = sorted(PeriodReceipts, key=lambda ReceiptItem: int(ReceiptItem.get("total") or 0), reverse=True)[:3]
    TopExpensesCompact = [
        {
            "id": ExpenseItem.get("id"),
            "date": ExpenseItem.get("date"),
            "merchant": ExpenseItem.get("merchant"),
            "category": ExpenseItem.get("category"),
            "total": ExpenseItem.get("total"),
        }
        for ExpenseItem in TopExpenses
    ]

    peak_day = min(day_totals, key=lambda day: (-day_totals[day], day)) if day_totals else None
    DailyAverage = int(round(TotalSpend / len(day_totals))) if day_totals else 0
    return {
        "period_type": PeriodType,
        "period_key": PeriodKey,
        "period_label": PeriodLabel,
        "start_date": StartIso,
        "end_date": EndIso,
        "receipt_count": len(PeriodReceipts),
        "active_days": len(day_totals),
        "peak_day": {"date": peak_day, "total": day_totals[peak_day]} if peak_day else None,
        "total_spend": TotalSpend,
        "daily_average": DailyAverage,
        "categories": CategorySummary,
        "top_expenses": TopExpensesCompact,
    }


@tool
def compare_periods(UserId: str, PeriodType: str, CurrentKey: str, PreviousKey: str, records: list | None = None) -> dict:
    """compare_periods: So sánh chi tiêu giữa kỳ hiện tại và kỳ trước đó bằng code.
    Input: UserId (str), PeriodType ('week'|'month'|'year'), CurrentKey (str), PreviousKey (str). Output: dict chênh lệch tổng tiền, % tăng/giảm và biến động theo từng danh mục. Không tác động ra ngoài."""
    AllReceipts = StorageModule.LoadReceiptRecords(UserId) if records is None else records
    CurrentSummary = aggregate_period(UserId, PeriodType, CurrentKey, AllReceipts)
    PreviousSummary = aggregate_period(UserId, PeriodType, PreviousKey, AllReceipts)

    CurrentTotal = int(CurrentSummary["total_spend"])
    PreviousTotal = int(PreviousSummary["total_spend"])
    DeltaAmount = CurrentTotal - PreviousTotal
    DeltaPct = round((DeltaAmount / float(PreviousTotal)) * 100.0, 1) if PreviousTotal > 0 else None

    CurrentCategoryMap = {Row["category"]: Row["amount"] for Row in CurrentSummary["categories"]}
    PreviousCategoryMap = {Row["category"]: Row["amount"] for Row in PreviousSummary["categories"]}
    AllCategoryNames = sorted(set(CurrentCategoryMap.keys()) | set(PreviousCategoryMap.keys()))

    CategoryDeltas = []
    for CategoryName in AllCategoryNames:
        CurrentAmount = int(CurrentCategoryMap.get(CategoryName, 0))
        PreviousAmount = int(PreviousCategoryMap.get(CategoryName, 0))
        CategoryDeltas.append(
            {
                "category": CategoryName,
                "current_amount": CurrentAmount,
                "previous_amount": PreviousAmount,
                "delta_amount": CurrentAmount - PreviousAmount,
            }
        )
    CategoryDeltas.sort(key=lambda DeltaRow: abs(DeltaRow["delta_amount"]), reverse=True)

    StrongestShift = CategoryDeltas[0] if CategoryDeltas else None
    return {
        "period_type": PeriodType,
        "current": CurrentSummary,
        "previous": PreviousSummary,
        "delta_amount": DeltaAmount,
        "delta_pct": DeltaPct,
        "category_deltas": CategoryDeltas,
        "strongest_shift": StrongestShift,
    }
