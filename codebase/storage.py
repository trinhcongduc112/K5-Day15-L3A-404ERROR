"""Quản lý thư mục CSDL cục bộ cho SkyBill (lưu ảnh hoá đơn và dữ liệu JSON dễ đọc)."""

import base64
import datetime
import json
import os
import re
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field

from filelock import FileLock

BaseCodeDirectory = os.path.dirname(os.path.abspath(__file__))
ProjectRootDirectory = os.path.dirname(BaseCodeDirectory)
StorageRootDirectory = os.environ.get("SKYBILL_STORAGE_DIR") or os.path.join(ProjectRootDirectory, "CSDL")
ImagesRootDirectory = os.path.join(StorageRootDirectory, "images")
ReceiptsFilePath = os.path.join(StorageRootDirectory, "receipts.json")
DraftsFilePath = os.path.join(StorageRootDirectory, "drafts.json")
SettingsFilePath = os.path.join(StorageRootDirectory, "settings.json")
StorageLock = FileLock(os.path.join(StorageRootDirectory, "ledger.lock"))


@dataclass(repr=False)
class EvaluationLedger:
    """Bản sổ tạm của một ca eval hoặc simulate."""

    receipts: list[dict]
    drafts: list[dict] = field(default_factory=list)

SeedFilePath = os.path.join(ProjectRootDirectory, "data", "expenses.json")


def LoadSeedReceiptRecords() -> list:
    """Đọc dữ liệu mẫu chung data/expenses.json (cùng nguồn với eval) theo dạng bản ghi của sổ."""
    with open(SeedFilePath, encoding="utf-8") as SeedStream:
        SeedRecords = json.load(SeedStream)["records"]
    return [
        {
            **Record,
            "user_id": Record.get("user_id", "default_user"),
            "source": Record.get("source") or Record.get("source_type") or "manual_note",
            "image_path": Record.get("image_path", ""),
            "items": [
                {"name": Item.get("name", ""), "price": int(Item.get("price", Item.get("amount", 0)) or 0)}
                for Item in Record.get("items", [])
            ],
        }
        for Record in SeedRecords
    ]


SafeDatePattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DataUrlPattern = re.compile(r"^data:image/([a-zA-Z0-9+.-]+);base64,(.+)$", re.DOTALL)


def _WriteJsonAtomic(TargetFilePath: str, PayloadData: object) -> None:
    """Ghi file JSON UTF-8 định dạng dễ đọc qua file tạm để tránh hỏng dữ liệu."""
    TempFilePath = TargetFilePath + ".tmp"
    with open(TempFilePath, "w", encoding="utf-8") as OutputStream:
        json.dump(PayloadData, OutputStream, ensure_ascii=False, indent=2)
    os.replace(TempFilePath, TargetFilePath)


def _ReadJsonList(TargetFilePath: str) -> list:
    """Đọc danh sách JSON từ file; trả về [] nếu lỗi hoặc không phải list."""
    if not os.path.exists(TargetFilePath):
        return []
    try:
        with open(TargetFilePath, "r", encoding="utf-8") as InputStream:
            ParsedData = json.load(InputStream)
        return ParsedData if isinstance(ParsedData, list) else []
    except Exception:
        return []


def LoadUserSettings(UserId: str = "default_user") -> dict:
    """Cài đặt của người dùng (vd hạn mức tháng) trong CSDL/settings.json."""
    try:
        with open(SettingsFilePath, "r", encoding="utf-8") as InputStream:
            AllSettings = json.load(InputStream)
    except (OSError, ValueError):
        return {}
    return AllSettings.get(UserId, {}) if isinstance(AllSettings, dict) else {}


def SaveUserSettings(UserId: str, Changes: dict) -> dict:
    """Gộp thay đổi vào cài đặt của một người dùng và ghi file nguyên tử."""
    with StorageLock:
        try:
            with open(SettingsFilePath, "r", encoding="utf-8") as InputStream:
                AllSettings = json.load(InputStream)
        except (OSError, ValueError):
            AllSettings = {}
        if not isinstance(AllSettings, dict):
            AllSettings = {}
        AllSettings[UserId] = {**AllSettings.get(UserId, {}), **Changes}
        _WriteJsonAtomic(SettingsFilePath, AllSettings)
    return AllSettings[UserId]


def EnsureStorageLayout() -> None:
    """Tạo thư mục CSDL/, CSDL/images/ và các file JSON mặc định nếu chưa có."""
    with StorageLock:
        os.makedirs(ImagesRootDirectory, exist_ok=True)
        if not os.path.exists(ReceiptsFilePath):
            _WriteJsonAtomic(ReceiptsFilePath, LoadSeedReceiptRecords())
        if not os.path.exists(DraftsFilePath):
            _WriteJsonAtomic(DraftsFilePath, [])


def LoadReceiptRecords(UserId: str = "default_user", ledger: EvaluationLedger | None = None) -> list:
    """Nạp hoá đơn đã xác nhận từ sổ thật hoặc sổ tạm theo UserId."""
    if ledger is None:
        EnsureStorageLayout()
    AllRecords = _ReadJsonList(ReceiptsFilePath) if ledger is None else list(ledger.receipts)
    if not UserId:
        return AllRecords
    FilteredRecords = [
        ReceiptItem
        for ReceiptItem in AllRecords
        if ReceiptItem.get("user_id", "default_user") == UserId
    ]
    return FilteredRecords


def SaveReceiptRecords(ReceiptList: list, ledger: EvaluationLedger | None = None) -> None:
    """Lưu toàn bộ danh sách hoá đơn vào CSDL/receipts.json."""
    if ledger is not None:
        ledger.receipts[:] = ReceiptList
        return
    with StorageLock:
        EnsureStorageLayout()
        _WriteJsonAtomic(ReceiptsFilePath, ReceiptList)


def ResetDemoReceiptRecords() -> list:
    """Khôi phục dữ liệu mẫu data/expenses.json vào CSDL/receipts.json và xoá bản nháp cũ."""
    with StorageLock:
        EnsureStorageLayout()
        FreshRecords = LoadSeedReceiptRecords()
        _WriteJsonAtomic(ReceiptsFilePath, FreshRecords)
        _WriteJsonAtomic(DraftsFilePath, [])
        return FreshRecords


def LoadDraftRecords(ledger: EvaluationLedger | None = None) -> list:
    """Nạp danh sách bản nháp từ CSDL/drafts.json."""
    if ledger is not None:
        return list(ledger.drafts)
    EnsureStorageLayout()
    return _ReadJsonList(DraftsFilePath)


def SaveDraftRecords(DraftList: list, ledger: EvaluationLedger | None = None) -> None:
    """Lưu danh sách bản nháp vào CSDL/drafts.json."""
    if ledger is not None:
        ledger.drafts[:] = DraftList
        return
    with StorageLock:
        EnsureStorageLayout()
        _WriteJsonAtomic(DraftsFilePath, DraftList)


def DecodeReceiptImage(image_data_url: str) -> tuple[bytes, str]:
    """Giải mã và giới hạn dữ liệu trước khi chuyển ảnh vào OCR."""
    match = DataUrlPattern.fullmatch(image_data_url)
    if not match:
        raise ValueError("Cần gửi ảnh JPG, PNG hoặc WEBP.")
    extensions = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}
    extension = extensions.get(match[1].lower())
    if extension is None or len(match[2]) > 12_000_000:
        raise ValueError("Định dạng ảnh không hỗ trợ hoặc ảnh quá lớn.")
    image = base64.b64decode(match[2], validate=True)
    if not image:
        raise ValueError("Ảnh rỗng.")
    return image, extension


def SaveReceiptImage(ImageRawBytes: bytes, FileExtension: str, TargetDate: str, RecordId: str) -> str:
    """Lưu ảnh đã kiểm vào CSDL/images/YYYY-MM-DD/<RecordId>.<ext>."""
    SafeDate = TargetDate if SafeDatePattern.match(str(TargetDate or "")) else datetime.date.today().isoformat()
    SafeRecordId = re.sub(r"[^A-Za-z0-9_-]", "", str(RecordId or "")) or uuid.uuid4().hex[:10]

    DateDirectory = os.path.join(ImagesRootDirectory, SafeDate)
    FileName = "%s.%s" % (SafeRecordId, FileExtension)
    TargetAbsolutePath = os.path.join(DateDirectory, FileName)
    with StorageLock:
        os.makedirs(DateDirectory, exist_ok=True)
        temp_path = TargetAbsolutePath + ".tmp"
        with open(temp_path, "wb") as ImageOutputStream:
            ImageOutputStream.write(ImageRawBytes)
        os.replace(temp_path, TargetAbsolutePath)

    return "%s/%s" % (SafeDate, FileName)


def UpsertDraftRecord(DraftRecord: dict, ledger: EvaluationLedger | None = None) -> dict:
    """Lưu hoặc cập nhật một bản nháp vào CSDL/drafts.json."""
    with StorageLock if ledger is None else nullcontext():
        DraftList = LoadDraftRecords(ledger)
        DraftId = DraftRecord.get("draft_id")
        UpdatedList = [Item for Item in DraftList if Item.get("draft_id") != DraftId]
        UpdatedList.append(DraftRecord)
        SaveDraftRecords(UpdatedList, ledger)
    return DraftRecord


def ConfirmDraftToLedger(payload: dict, ledger: EvaluationLedger | None = None) -> tuple[dict, bool]:
    """Chốt bản nháp hợp lệ và trả (khoản đã lưu, có trùng hay không)."""
    with StorageLock if ledger is None else nullcontext():
        records = LoadReceiptRecords("", ledger)
        drafts = LoadDraftRecords(ledger)
        draft_id = str(payload.get("draft_id") or "").strip()
        if not draft_id:
            raise ValueError("Cần bản xem nhanh hợp lệ trước khi Chốt.")
        draft = next((row for row in drafts if row.get("draft_id") == draft_id), None)
        capture_id = str(draft.get("capture_id") or "").casefold() if draft else ""
        for row in records:
            stored_capture_id = str(row.get("capture_id") or "").casefold()
            if row.get("draft_id") == draft_id or (capture_id and stored_capture_id == capture_id):
                if draft:
                    SaveDraftRecords([item for item in drafts if item.get("draft_id") != draft_id], ledger)
                return row, True
        manual = bool(draft and draft.get("manual_entry"))
        if draft is None or not capture_id or not (draft.get("printed_total") or manual):
            raise ValueError("Chưa có bản xem nhanh đủ căn cứ. Hãy chụp lại hóa đơn.")

        # Bản nhập tay: không có số mặc định, người dùng phải tự gõ số thực trả.
        total = payload.get("total") if manual else payload.get("total", draft["printed_total"])
        if type(total) is not int or total <= 0:
            raise ValueError("Số thực trả phải là số nguyên VND lớn hơn 0.")
        date = datetime.date.fromisoformat(payload.get("date") or draft["date"]).isoformat()
        date_source = draft.get("date_source") if date == draft["date"] else "người dùng sửa"
        now = datetime.datetime.now()
        receipt = {
            **{key: draft[key] for key in ("draft_id", "image_path", "source", "items", "user_id", "ocr_engine", "quality_score")},
            "id": "HD-" + uuid.uuid4().hex[:8].upper(),
            "capture_id": capture_id,
            "date": date,
            "date_source": date_source,
            "time": now.strftime("%H:%M"),
            "merchant": str(payload.get("merchant") or draft["merchant"]).strip(),
            "category": str(payload.get("category") or draft["category"]).strip(),
            "note": str(payload.get("note") or "").strip(),
            "total": total,
            "created_at": now.isoformat(timespec="seconds"),
        }
        if manual:
            receipt["items"] = [{"name": receipt["merchant"], "price": total}]
            receipt["entry"] = "người dùng nhập tay"
        records.append(receipt)
        SaveReceiptRecords(records, ledger)
        SaveDraftRecords([row for row in drafts if row.get("draft_id") != draft_id], ledger)
        return receipt, False


def UpdateReceiptRecord(ReceiptId: str, UpdatePayload: dict) -> dict | None:
    """Cập nhật danh mục hoặc ghi chú của một hoá đơn trong CSDL/receipts.json."""
    with StorageLock:
        EnsureStorageLayout()
        AllRecords = _ReadJsonList(ReceiptsFilePath)
        UpdatedRecord = None
        for ReceiptItem in AllRecords:
            if ReceiptItem.get("id") == ReceiptId:
                if "category" in UpdatePayload and UpdatePayload["category"]:
                    ReceiptItem["category"] = str(UpdatePayload["category"]).strip()
                if "note" in UpdatePayload:
                    ReceiptItem["note"] = str(UpdatePayload["note"] or "").strip()
                UpdatedRecord = ReceiptItem
                break
        if UpdatedRecord is not None:
            SaveReceiptRecords(AllRecords)
        return UpdatedRecord


def DeleteReceiptRecord(ReceiptId: str) -> bool:
    """Xoá một hoá đơn khỏi CSDL/receipts.json theo ReceiptId."""
    with StorageLock:
        EnsureStorageLayout()
        AllRecords = _ReadJsonList(ReceiptsFilePath)
        RemainingRecords = [ReceiptItem for ReceiptItem in AllRecords if ReceiptItem.get("id") != ReceiptId]
        if len(RemainingRecords) == len(AllRecords):
            return False
        SaveReceiptRecords(RemainingRecords)
        return True


def ResolveImageAbsolutePath(RelativePath: str) -> str | None:
    """Chuyển đổi đường dẫn tương đối thành đường dẫn tuyệt đối an toàn bên trong CSDL/images/."""
    CleanRelative = str(RelativePath or "").lstrip("/\\")
    if not CleanRelative:
        return None
    CandidatePath = os.path.abspath(os.path.join(ImagesRootDirectory, CleanRelative))
    ImagesRootAbsolute = os.path.abspath(ImagesRootDirectory)
    if not CandidatePath.startswith(ImagesRootAbsolute + os.sep):
        return None
    return CandidatePath if os.path.isfile(CandidatePath) else None
