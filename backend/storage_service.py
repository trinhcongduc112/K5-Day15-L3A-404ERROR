"""Dịch vụ lưu trữ CSDL cục bộ cho backend (lưu ảnh hoá đơn và tệp JSON, chống cộng trùng khi Chốt)."""

import base64
import copy
import datetime
import json
import os
import re
import uuid

BackendDirectory = os.path.dirname(os.path.abspath(__file__))
ProjectRootDirectory = os.path.dirname(BackendDirectory)
StorageRootDirectory = os.path.join(ProjectRootDirectory, "CSDL")
ImagesRootDirectory = os.path.join(StorageRootDirectory, "images")
ReceiptsFilePath = os.path.join(StorageRootDirectory, "receipts.json")
DraftsFilePath = os.path.join(StorageRootDirectory, "drafts.json")

SafeDatePattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DataUrlPattern = re.compile(r"^data:image/([a-zA-Z0-9+.-]+);base64,(.+)$", re.DOTALL)


def _WriteJsonAtomic(TargetFilePath: str, PayloadData: object) -> None:
    """Ghi file JSON UTF-8 qua file tạm để đảm bảo toàn vẹn dữ liệu."""
    TempFilePath = TargetFilePath + ".tmp"
    with open(TempFilePath, "w", encoding="utf-8") as OutputStream:
        json.dump(PayloadData, OutputStream, ensure_ascii=False, indent=2)
    os.replace(TempFilePath, TargetFilePath)


def _ReadJsonList(TargetFilePath: str) -> list:
    """Đọc danh sách JSON từ file; trả về [] nếu chưa có hoặc lỗi định dạng."""
    if not os.path.exists(TargetFilePath):
        return []
    try:
        with open(TargetFilePath, "r", encoding="utf-8") as InputStream:
            ParsedData = json.load(InputStream)
        return ParsedData if isinstance(ParsedData, list) else []
    except Exception:
        return []


def EnsureStorageLayout(SeedRecords: list = None) -> None:
    """Khởi tạo thư mục CSDL/, CSDL/images/ và 2 file JSON lưu thông tin hoá đơn."""
    os.makedirs(ImagesRootDirectory, exist_ok=True)
    if not os.path.exists(ReceiptsFilePath):
        InitialRecords = copy.deepcopy(SeedRecords) if isinstance(SeedRecords, list) else []
        _WriteJsonAtomic(ReceiptsFilePath, InitialRecords)
    if not os.path.exists(DraftsFilePath):
        _WriteJsonAtomic(DraftsFilePath, [])


def LoadReceiptRecords(UserId: str = "default_user") -> list:
    """Đọc danh sách hoá đơn đã Chốt từ CSDL/receipts.json."""
    EnsureStorageLayout()
    AllRecords = _ReadJsonList(ReceiptsFilePath)
    if not UserId:
        return AllRecords
    return [Item for Item in AllRecords if Item.get("user_id", "default_user") == UserId]


def SaveBase64ReceiptImage(ImageDataUrl: str, TargetDate: str, RecordId: str) -> tuple:
    """Lưu ảnh chụp/tải lên vào CSDL/images/YYYY-MM-DD/<RecordId>.<ext>."""
    EnsureStorageLayout()
    SafeDate = TargetDate if SafeDatePattern.match(str(TargetDate or "")) else datetime.date.today().isoformat()
    SafeRecordId = re.sub(r"[^A-Za-z0-9_-]", "", str(RecordId or "")) or uuid.uuid4().hex[:10]

    MatchResult = DataUrlPattern.match(str(ImageDataUrl or "").strip())
    if MatchResult:
        ImageSubtype = MatchResult.group(1).lower()
        Base64Body = MatchResult.group(2)
    else:
        ImageSubtype = "jpeg"
        Base64Body = str(ImageDataUrl or "").strip()

    ExtensionMap = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}
    FileExtension = ExtensionMap.get(ImageSubtype, "jpg")
    ImageRawBytes = base64.b64decode(Base64Body)

    DateDirectory = os.path.join(ImagesRootDirectory, SafeDate)
    os.makedirs(DateDirectory, exist_ok=True)
    FileName = "%s.%s" % (SafeRecordId, FileExtension)
    TargetAbsolutePath = os.path.join(DateDirectory, FileName)
    with open(TargetAbsolutePath, "wb") as ImageOutputStream:
        ImageOutputStream.write(ImageRawBytes)

    return "%s/%s" % (SafeDate, FileName), ImageRawBytes


def UpsertDraftRecord(DraftRecord: dict) -> dict:
    """Lưu bản nháp vào CSDL/drafts.json."""
    EnsureStorageLayout()
    DraftList = _ReadJsonList(DraftsFilePath)
    DraftId = DraftRecord.get("draft_id")
    UpdatedList = [Item for Item in DraftList if Item.get("draft_id") != DraftId]
    UpdatedList.append(DraftRecord)
    _WriteJsonAtomic(DraftsFilePath, UpdatedList)
    return DraftRecord


def ConfirmDraftToLedger(ConfirmPayload: dict) -> dict:
    """Chốt bản nháp vào CSDL/receipts.json, chống cộng trùng nếu bấm Chốt nhiều lần cùng capture_id/draft_id."""
    EnsureStorageLayout()
    AllRecords = _ReadJsonList(ReceiptsFilePath)
    DraftList = _ReadJsonList(DraftsFilePath)

    DraftId = str(ConfirmPayload.get("draft_id") or "").strip()
    CaptureId = str(ConfirmPayload.get("capture_id") or DraftId).strip()

    if CaptureId:
        for ExistingRecord in AllRecords:
            if ExistingRecord.get("capture_id") == CaptureId:
                ExistingRecord["duplicate_prevented"] = True
                return ExistingRecord

    MatchedDraft = None
    if DraftId:
        for DraftItem in DraftList:
            if DraftItem.get("draft_id") == DraftId:
                MatchedDraft = DraftItem
                break

    RawItems = ConfirmPayload.get("items") or (MatchedDraft.get("items") if MatchedDraft else []) or []
    NormalizedItems = []
    CalculatedTotal = 0
    for ItemEntry in RawItems:
        ItemName = str(ItemEntry.get("name") or "").strip()
        ItemPrice = int(round(float(ItemEntry.get("price") or 0)))
        if ItemName:
            NormalizedItems.append({"name": ItemName, "price": ItemPrice})
            CalculatedTotal += ItemPrice

    TargetDate = str(
        ConfirmPayload.get("date")
        or (MatchedDraft.get("date") if MatchedDraft else "")
        or datetime.date.today().isoformat()
    )
    NewReceipt = {
        "id": "HD-" + uuid.uuid4().hex[:6].upper(),
        "capture_id": CaptureId,
        "user_id": str(ConfirmPayload.get("user_id") or "default_user"),
        "date": TargetDate,
        "time": str(ConfirmPayload.get("time") or datetime.datetime.now().strftime("%H:%M")),
        "merchant": str(ConfirmPayload.get("merchant") or "Chưa rõ cửa hàng").strip(),
        "category": str(ConfirmPayload.get("category") or "Chưa phân loại").strip(),
        "source": str(ConfirmPayload.get("source") or (MatchedDraft.get("source") if MatchedDraft else "camera")),
        "note": str(ConfirmPayload.get("note") or "").strip(),
        "image_path": str(ConfirmPayload.get("image_path") or (MatchedDraft.get("image_path") if MatchedDraft else "")),
        "items": NormalizedItems,
        "total": CalculatedTotal,
        "ocr_engine": (MatchedDraft or {}).get("ocr_engine", ""),
        "quality_score": (MatchedDraft or {}).get("quality_score"),
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }

    AllRecords.append(NewReceipt)
    _WriteJsonAtomic(ReceiptsFilePath, AllRecords)

    if DraftId:
        RemainingDrafts = [Item for Item in DraftList if Item.get("draft_id") != DraftId]
        _WriteJsonAtomic(DraftsFilePath, RemainingDrafts)

    return NewReceipt


def ResolveImageAbsolutePath(RelativePath: str) -> str | None:
    """Trả về đường dẫn tuyệt đối an toàn bên trong CSDL/images/."""
    CleanRelative = str(RelativePath or "").lstrip("/\\")
    if not CleanRelative:
        return None
    CandidatePath = os.path.abspath(os.path.join(ImagesRootDirectory, CleanRelative))
    ImagesRootAbsolute = os.path.abspath(ImagesRootDirectory)
    if not CandidatePath.startswith(ImagesRootAbsolute + os.sep):
        return None
    return CandidatePath if os.path.isfile(CandidatePath) else None
