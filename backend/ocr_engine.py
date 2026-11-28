"""Quality Gate và ONNX OCR tiếng Việt cho hoá đơn (trọng số đặt tại backend/weights/).

Kế thừa thuật toán từ P-163 (quality.py + ocr.py):
- det.onnx (PaddleOCR PP-OCRv3 DBNet)
- viesvtr_v7.onnx (VieSVTR v7 CTC trên bảng chữ cái VietOCR 229 ký tự)
"""

import io
import math
import os
import re
import threading
import unicodedata

try:
    import cv2 as OpenCvLib
    import numpy as NumpyLib
    import onnxruntime as OnnxRuntime
    from PIL import Image
    OcrDependenciesAvailable = True
    OcrImportErrorMessage = ""
except Exception as ImportException:
    OpenCvLib = None
    NumpyLib = None
    OnnxRuntime = None
    Image = None
    OcrDependenciesAvailable = False
    OcrImportErrorMessage = "%s: %s" % (type(ImportException).__name__, ImportException)

BackendDirectory = os.path.dirname(os.path.abspath(__file__))
RepoWeightsDirectory = os.path.join(BackendDirectory, "weights", "ocr-1", "ppocrv3-viesvtr-v7")


def _ResolveWeightsDirectory() -> str:
    """Ưu tiên SKYBILL_OCR_WEIGHTS_DIR, mặc định dùng trọng số trong backend/weights/ của repo."""
    EnvDirectory = str(os.environ.get("SKYBILL_OCR_WEIGHTS_DIR") or "").strip()
    if EnvDirectory:
        return EnvDirectory
    return RepoWeightsDirectory


DefaultWeightsDirectory = _ResolveWeightsDirectory()

# Bảng chữ cái VietOCR 229 ký tự (index 0 là CTC blank, ký tự thật bắt đầu từ index 1)
VietOcrVocabulary = (
    "aAàÀảẢãÃáÁạẠăĂằẰẳẲẵẴắẮặẶâÂầẦẩẨẫẪấẤậẬbBcCdDđĐeEèÈẻẺẽẼéÉẹẸêÊềỀểỂễỄếẾệỆ"
    "fFgGhHiIìÌỉỈĩĨíÍịỊjJkKlLmMnNoOòÒỏỎõÕóÓọỌôÔồỒổỔỗỖốỐộỘơƠờỜởỞỡỠớỚợỢpPqQrR"
    "sStTuUùÙủỦũŨúÚụỤưƯừỪửỬữỮứỨựỰvVwWxXyYỳỲỷỶỹỸýÝỵỴzZ0123456789"
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ "
)

# Tham số Quality Gate
QualityCanonicalMaxSide = 960
BlurSaturationVariance = 250.0
MaxGlareAreaRatio = 0.05
MinGlareBlobShare = 0.004
GlareAboveMedianLuminance = 12.0
MinReadableSidePixels = 200
QualityPassThreshold = 0.35

# Tham số PP-OCRv3 DBNet & VieSVTR v7
DetectionMaxSide = 960
DetectionBinaryThreshold = 0.3
DetectionBoxThreshold = 0.5
DetectionUnclipRatio = 1.65
RecognitionHeight = 64
RecognitionWidthStride = 4
RecognitionWidthMin = 32
RecognitionWidthMax = 1600

SessionLock = threading.Lock()
CachedDetectionSession = None
CachedRecognitionSession = None

# Regex phân tích hoá đơn tiếng Việt (tách riêng tiền chuẩn chấm/phẩy/nguyên và tiền có đơn vị triệu/nghìn/tỷ)
ScaledPricePattern = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(tỷ|ty|triệu|trieu|tr|nghìn|nghin|ngàn|ngan)\b(?:\s*(?:vnđ|vnd|đồng|dong|đ|d))?",
    re.IGNORECASE,
)
FormattedPricePattern = re.compile(
    r"(?<!\d)(\d{1,3}(?:\.\d{3})+|\d{1,3}(?:,\d{3})+|\d{4,7})(?!\d)"
)
SpaceSeparatedPricePattern = re.compile(r"(?<!\d)(\d{1,3}\s+\d{3})(?!\d)")
DateValuePattern = re.compile(r"(?<!\d)(\d{2}[/.\-]\d{2}[/.\-]\d{4}|\d{4}-\d{2}-\d{2})(?!\d)")
MonthYearValuePattern = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])/((?:19|20)\d{2})(?!\d)")
TimeTokenPattern = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
UrlDomainPattern = re.compile(r"(?:https?://|www\.|ww\.)\S+|\b[a-z0-9\-]+\.(?:com|vn|net|org|info)\b\S*", re.IGNORECASE)
EmailAddressPattern = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
LongCodeOrPhonePattern = re.compile(
    r"(?:\+84|84)[\s.\-]?\d{2,3}[\s.\-]?\d{3}[\s.\-]?\d{3,4}"
    r"|\b0\d{8,10}\b|\b[A-Za-z]*\d{8,}[A-Za-z0-9]*\b|\b(?:1800|1900)\s*\d{4}\b"
)
UnitQuantityPattern = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:g|kg|ml|l|m|cm|mm|kwh)\b", re.IGNORECASE)
LeadingQuantityPattern = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s+")
GenericDocTitleSuffixPattern = re.compile(
    r"\b(?:hoa\s*don\s*ban\s*hang|hoa\s*don|phieu\s*thanh\s*toan|bien\s*lai)\b",
    re.IGNORECASE,
)

HighPriorityTotalPattern = re.compile(
    r"(phai\s*thanh\s*toan|tong\s*cong|tong\s*so\s*thanh\s*toan|tong\s*tien\s*phai\s*t\.?\s*toan|"
    r"tong\s*tien\s*phai\s*thanh\s*toan|tien\s*thanh\s*toan|tong\s*tien\b(?!\s*hang)|grand\s*total|\btotal\b)",
    re.IGNORECASE,
)
MediumPriorityTotalPattern = re.compile(
    r"(cong\s*tien\s*hang|cong\s*tien|thanh\s*toan(?!\s*cho\b))",
    re.IGNORECASE,
)
LowPriorityTotalPattern = re.compile(r"(tong\s*tien\s*hang)", re.IGNORECASE)

ElectricBillIndicatorPattern = re.compile(
    r"(dien\s*luc|evn|dien\s*nang\s*tieu\s*thu|shbt|tien\s*dien\s*tt)",
    re.IGNORECASE,
)
ElectricEnergyAmountPattern = re.compile(r"(tien\s*dien\s*tt)", re.IGNORECASE)
ElectricTaxAmountPattern = re.compile(r"(tien\s*thue)", re.IGNORECASE)
ElectricTierLinePattern = re.compile(r"(shbt\s*kt|shbt)", re.IGNORECASE)
DiscountLinePattern = re.compile(r"(chiet\s*khau|giam\s*gia|khuyen\s*mai|diem\s*su\s*dung)", re.IGNORECASE)
NegativeDiscountPattern = re.compile(r"(chiet\s*khau|giam\s*gia|khuyen\s*mai)", re.IGNORECASE)
TableHeaderPattern = re.compile(
    r"(don\s*gia|thanh\s*tien|ten\s*hang|gia\s*ban|mo\s*ta\s+so\s*luong|sl\s*dvt|^sl\b|^khau$|^chiet\s*khau$)",
    re.IGNORECASE,
)
IgnoreLinePattern = re.compile(
    r"(tien\s*khach|tien\s*dua|tien\s*thua|tien\s*mat|tien\s*ca\s*the|\bca\s*the\b|quet\s*the|"
    r"chuyen\s*khoan|thanh\s*toan\s*the|vi\s*dien\s*tu|\bmomo\b|zalopay|vnpay|da\s*lam\s*tron|"
    r"tra\s*lai|change|cash|cam\s*on|xin\s*cam\s*on|vui\s*long\s*email|neu\s*ban\s*co\s*cau\s*hoi|"
    r"hen\s*gap|wifi|mat\s*khau|hotline|dia\s*chi|sdt|dien\s*thoai|tai\s*quay|nhan\s*vien|"
    r"so\s*ct\s*:|ngay\s*ct\s*:|hoa\s*don\s*cho\s*:|thanh\s*toan\s*cho\s*:|"
    r"tong\s*da[il]?|gop\s*y|khieu\s*nai|doanh\s*so\s*tich|ma\s*tra\s*cuu|hoa\s*don\s*tich\s*diem|"
    r"hd\s*vat|chinh\s*sach\s*xu|khach\s*hang|csm|csc|pmax|dien\s*nang\s*tieu\s*thu|"
    r"quy\s*khach|luu\s*y|^[-=*_.]{3,}$)",
    re.IGNORECASE,
)

CategoryKeywordMap = {
    "Ăn uống": (
        "ca phe", "cafe", "coffee", "tra sua", "tra dao", "tra chanh", "tra vai", "hong tra", "luc tra", "tra da",
        "banh", "banh gio", "banh mi", "com", "bun", "pho", "lau", "nuong", "quan an", "an uong", "nha hang", "bep",
        "highlands", "phuc long", "bach hoa xanh", "heo", "thit", "cam sanh", "trung vit", "dui toi ga",
        "cai be", "bi xanh", "bap cai", "chanh", "muoi hat", "gia song", "xa lach", "kho qua", "bau sao",
    ),
    "Di chuyển": ("grab", "be", "xanh sm", "taxi", "xang", "gui xe", "ve xe", "bus", "metro", "cuoc xe"),
    "Mua sắm": (
        "sieu thi", "mart", "minimart", "vincommerce", "vinmart", "nha sach", "sach",
        "quan ao", "quan tay", "vay", "ao so mi", "ao khoac", "thoi trang", "giay",
        "my pham", "dien may", "tap hoa", "bim bim", "giay ve sinh",
    ),
    "Hóa đơn & Nhà ở": (
        "dien luc", "evn", "tien dien", "tien thue", "hoa don dien", "tien nuoc",
        "tien tro", "tien phong", "internet", "wifi", "vien thong", "chung cu",
    ),
    "Giải trí": (
        "rap", "phim", "cinema", "cgv", "lotte", "ve xem", "game", "du lich", "karaoke",
        "khach san", "hotel", "resort", "homestay",
    ),
    "Sức khỏe": ("thuoc", "nha thuoc", "benh vien", "phong kham", "kham", "y te", "vitamin", "nha khoa"),
}


def _StripVietnameseAccents(SourceText: str) -> str:
    """Chuyển tiếng Việt có dấu sang không dấu viết thường để đối chiếu từ khoá OCR ổn định."""
    ReplacedText = str(SourceText or "").replace("đ", "d").replace("Đ", "D")
    Decomposed = unicodedata.normalize("NFD", ReplacedText)
    StrippedChars = [CharItem for CharItem in Decomposed if unicodedata.category(CharItem) != "Mn"]
    return "".join(StrippedChars).lower()


def GetOcrEnvironmentStatus() -> dict:
    """Kiểm tra trạng thái thư viện và file trọng số ONNX trên thiết bị hiện tại."""
    ResolvedWeightsDir = _ResolveWeightsDirectory()
    DetectionModelPath = os.path.join(ResolvedWeightsDir, "det.onnx")
    RecognitionModelPath = os.path.join(ResolvedWeightsDir, "viesvtr_v7.onnx")
    DetectionWeightExists = os.path.isfile(DetectionModelPath)
    RecognitionWeightExists = os.path.isfile(RecognitionModelPath)
    return {
        "dependencies_available": OcrDependenciesAvailable,
        "import_error": OcrImportErrorMessage,
        "weights_directory": ResolvedWeightsDir,
        "det_model_exists": DetectionWeightExists,
        "rec_model_exists": RecognitionWeightExists,
        "engine_ready": bool(OcrDependenciesAvailable and DetectionWeightExists and RecognitionWeightExists),
        "engine_version": "ppocrv3-viesvtr-v7",
    }


def _GetOnnxSessions() -> tuple:
    """Nạp và lưu cache singleton cho 2 mô hình ONNX trên CPU."""
    global CachedDetectionSession, CachedRecognitionSession
    if not OcrDependenciesAvailable:
        raise RuntimeError("Thiếu thư viện OCR/CV: %s" % OcrImportErrorMessage)
    ResolvedWeightsDir = _ResolveWeightsDirectory()
    with SessionLock:
        if CachedDetectionSession is not None and CachedRecognitionSession is not None:
            return CachedDetectionSession, CachedRecognitionSession
        DetectionModelPath = os.path.join(ResolvedWeightsDir, "det.onnx")
        RecognitionModelPath = os.path.join(ResolvedWeightsDir, "viesvtr_v7.onnx")
        if not os.path.isfile(DetectionModelPath) or not os.path.isfile(RecognitionModelPath):
            raise FileNotFoundError(
                "Không tìm thấy trọng số det.onnx hoặc viesvtr_v7.onnx tại: %s" % ResolvedWeightsDir
            )
        SessionOptions = OnnxRuntime.SessionOptions()
        SessionOptions.graph_optimization_level = OnnxRuntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        CachedDetectionSession = OnnxRuntime.InferenceSession(
            DetectionModelPath, sess_options=SessionOptions, providers=["CPUExecutionProvider"]
        )
        CachedRecognitionSession = OnnxRuntime.InferenceSession(
            RecognitionModelPath, sess_options=SessionOptions, providers=["CPUExecutionProvider"]
        )
        return CachedDetectionSession, CachedRecognitionSession


def _ResizeKeepAspectMaxSide(RgbImageArray, MaxSidePixels: int):
    """Đưa cạnh lớn nhất của ảnh về tối đa MaxSidePixels để đo độ nét/loá đồng nhất."""
    OriginalHeight, OriginalWidth = RgbImageArray.shape[:2]
    LongestSide = max(OriginalHeight, OriginalWidth)
    if LongestSide <= MaxSidePixels or LongestSide == 0:
        return RgbImageArray
    ScaleFactor = float(MaxSidePixels) / float(LongestSide)
    NewWidth = max(1, int(round(OriginalWidth * ScaleFactor)))
    NewHeight = max(1, int(round(OriginalHeight * ScaleFactor)))
    return OpenCvLib.resize(RgbImageArray, (NewWidth, NewHeight), interpolation=OpenCvLib.INTER_AREA)


def MeasureReceiptBlur(GrayImageArray) -> tuple:
    """Đo độ nét qua phương sai Laplacian (P-163 quality.py), trả về (BlurScore, LaplacianVariance)."""
    LaplacianArray = OpenCvLib.Laplacian(GrayImageArray, OpenCvLib.CV_64F)
    LaplacianVariance = float(LaplacianArray.var())
    RawBlurScore = min(1.0, LaplacianVariance / BlurSaturationVariance)
    ClippedBlurScore = float(NumpyLib.clip(RawBlurScore, 0.0, 1.0))
    return ClippedBlurScore, LaplacianVariance


def MeasureReceiptGlare(RgbImageArray) -> tuple:
    """Đo vùng loá sáng cục bộ bằng HSV + connected components (P-163 quality.py)."""
    HsvImageArray = OpenCvLib.cvtColor(RgbImageArray, OpenCvLib.COLOR_RGB2HSV)
    ValueChannel = HsvImageArray[:, :, 2].astype(NumpyLib.float32)
    SaturationChannel = HsvImageArray[:, :, 1].astype(NumpyLib.float32)
    MinChannelArray = RgbImageArray.min(axis=2).astype(NumpyLib.float32)

    MedianValue = float(NumpyLib.median(ValueChannel))
    MedianMinChannel = float(NumpyLib.median(MinChannelArray))
    ValueCutoff = max(248.0, MedianValue + GlareAboveMedianLuminance)
    MinChannelCutoff = max(240.0, MedianMinChannel + GlareAboveMedianLuminance * 0.8)

    RawGlareMask = (
        (ValueChannel >= ValueCutoff)
        & (MinChannelArray >= MinChannelCutoff)
        & (SaturationChannel <= 25.0)
    ).astype(NumpyLib.uint8)

    TotalPixelCount = int(ValueChannel.size)
    if not NumpyLib.any(RawGlareMask):
        return 1.0, 0.0

    ComponentCount, UnusedLabels, ComponentStats, UnusedCentroids = OpenCvLib.connectedComponentsWithStats(
        RawGlareMask, connectivity=8
    )
    MinBlobPixels = max(16, int(round(MinGlareBlobShare * TotalPixelCount)))
    GlarePixelCount = 0
    for ComponentIndex in range(1, ComponentCount):
        ComponentArea = int(ComponentStats[ComponentIndex, OpenCvLib.CC_STAT_AREA])
        if ComponentArea >= MinBlobPixels:
            GlarePixelCount += ComponentArea

    GlareRatio = float(GlarePixelCount / max(1, TotalPixelCount))
    RawGlareScore = max(0.0, 1.0 - (GlareRatio / MaxGlareAreaRatio))
    ClippedGlareScore = float(NumpyLib.clip(RawGlareScore, 0.0, 1.0))
    return ClippedGlareScore, GlareRatio


def AssessReceiptQuality(ImageBytes: bytes) -> dict:
    """Đánh giá chất lượng ảnh hoá đơn (độ phân giải, độ nét, độ loá sáng)."""
    if not OcrDependenciesAvailable:
        return {
            "available": False,
            "quality_status": "unavailable",
            "overall_score": None,
            "blur_score": None,
            "laplacian_var": None,
            "glare_score": None,
            "glare_ratio": None,
            "image_width": None,
            "image_height": None,
            "reasons": ["QUALITY_DEPENDENCIES_MISSING"],
        }

    PilImage = Image.open(io.BytesIO(ImageBytes)).convert("RGB")
    ImageWidth, ImageHeight = PilImage.size
    RgbOriginal = NumpyLib.asarray(PilImage, dtype=NumpyLib.uint8)
    RgbCanonical = _ResizeKeepAspectMaxSide(RgbOriginal, QualityCanonicalMaxSide)
    GrayCanonical = OpenCvLib.cvtColor(RgbCanonical, OpenCvLib.COLOR_RGB2GRAY)

    MinSide = min(ImageWidth, ImageHeight)
    ResolutionScore = (
        1.0
        if MinSide >= MinReadableSidePixels
        else float(NumpyLib.clip(MinSide / float(MinReadableSidePixels), 0.0, 0.45))
    )
    BlurScore, LaplacianVariance = MeasureReceiptBlur(GrayCanonical)
    GlareScore, GlareRatio = MeasureReceiptGlare(RgbCanonical)

    OverallScore = float(min(ResolutionScore, BlurScore, GlareScore))
    FailureReasons = []
    if ResolutionScore < QualityPassThreshold:
        FailureReasons.append("LOW_RESOLUTION")
    if BlurScore < QualityPassThreshold:
        FailureReasons.append("RECEIPT_BLURRED")
    if GlareScore < QualityPassThreshold:
        FailureReasons.append("GLARE_DETECTED")

    QualityStatus = "pass" if OverallScore >= QualityPassThreshold else "fail"
    return {
        "available": True,
        "quality_status": QualityStatus,
        "overall_score": round(OverallScore, 4),
        "blur_score": round(BlurScore, 4),
        "laplacian_var": round(LaplacianVariance, 2),
        "glare_score": round(GlareScore, 4),
        "glare_ratio": round(GlareRatio, 4),
        "image_width": int(ImageWidth),
        "image_height": int(ImageHeight),
        "reasons": FailureReasons,
    }


def SuppressRedOverlay(RgbImageArray):
    """Lọc nhiễu dấu đỏ/watermark đè lên chữ tối (từ P-163 ocr.py)."""
    RedChannel = RgbImageArray[:, :, 0].astype(NumpyLib.int16)
    GreenChannel = RgbImageArray[:, :, 1].astype(NumpyLib.int16)
    BlueChannel = RgbImageArray[:, :, 2].astype(NumpyLib.int16)
    RedMask = (RedChannel - NumpyLib.maximum(GreenChannel, BlueChannel) > 35) & (RedChannel > 130)
    if not NumpyLib.any(RedMask):
        return RgbImageArray
    CleanedRgb = RgbImageArray.copy()
    CleanedRgb[RedMask, 1] = CleanedRgb[RedMask, 0]
    CleanedRgb[RedMask, 2] = CleanedRgb[RedMask, 0]
    return CleanedRgb


def PreprocessDetectionImage(RgbImageArray) -> tuple:
    """Chuẩn hoá ảnh RGB thành tensor BGR (1, 3, H, W) cho PP-OCRv3 DBNet."""
    DetectionMean = NumpyLib.array([0.485, 0.456, 0.406], dtype=NumpyLib.float32)
    DetectionStd = NumpyLib.array([0.229, 0.224, 0.225], dtype=NumpyLib.float32)
    OriginalHeight, OriginalWidth = RgbImageArray.shape[:2]
    ScaleRatio = min(1.0, DetectionMaxSide / float(max(OriginalHeight, OriginalWidth)))
    TargetHeight = max(32, int(round(OriginalHeight * ScaleRatio / 32.0)) * 32)
    TargetWidth = max(32, int(round(OriginalWidth * ScaleRatio / 32.0)) * 32)
    ResizedRgb = OpenCvLib.resize(RgbImageArray, (TargetWidth, TargetHeight), interpolation=OpenCvLib.INTER_LINEAR)
    BgrImage = ResizedRgb[:, :, ::-1]
    NormalizedImage = (BgrImage.astype(NumpyLib.float32) / 255.0 - DetectionMean) / DetectionStd
    TensorBlob = NumpyLib.ascontiguousarray(NormalizedImage.transpose(2, 0, 1)[NumpyLib.newaxis, ...])
    ScaleX = OriginalWidth / float(TargetWidth)
    ScaleY = OriginalHeight / float(TargetHeight)
    return TensorBlob, ScaleX, ScaleY


def PostprocessDetectionBoxes(
    ProbabilityMap, ScaleX: float, ScaleY: float, OriginalWidth: int, OriginalHeight: int
) -> list:
    """Tách khung chữ từ bản đồ xác suất DBNet và sắp xếp theo thứ tự đọc."""
    ProbArray = NumpyLib.asarray(ProbabilityMap, dtype=NumpyLib.float32)
    while ProbArray.ndim > 2:
        ProbArray = ProbArray[0]
    BinaryMap = (ProbArray > DetectionBinaryThreshold).astype(NumpyLib.uint8)
    ContourList, UnusedHierarchy = OpenCvLib.findContours(BinaryMap, OpenCvLib.RETR_LIST, OpenCvLib.CHAIN_APPROX_SIMPLE)

    MaxLineHeight = max(60, int(round(0.20 * OriginalHeight)))
    RawBoxes = []
    for ContourItem in ContourList:
        if len(ContourItem) < 3:
            continue
        BoxX, BoxY, BoxWidth, BoxHeight = OpenCvLib.boundingRect(ContourItem)
        if BoxWidth < 4 or BoxHeight < 4:
            continue
        RoiMask = NumpyLib.zeros((BoxHeight, BoxWidth), dtype=NumpyLib.uint8)
        ShiftedContour = ContourItem - NumpyLib.array([[[BoxX, BoxY]]])
        OpenCvLib.fillPoly(RoiMask, [ShiftedContour], 1)
        RoiProb = ProbArray[BoxY : BoxY + BoxHeight, BoxX : BoxX + BoxWidth]
        MeanBoxScore = float(OpenCvLib.mean(RoiProb, mask=RoiMask)[0])
        if MeanBoxScore < DetectionBoxThreshold:
            continue

        ContourArea = float(OpenCvLib.contourArea(ContourItem))
        ContourPerimeter = float(OpenCvLib.arcLength(ContourItem, True))
        if ContourPerimeter < 1.0:
            continue
        ExpandDistance = ContourArea * DetectionUnclipRatio / ContourPerimeter
        PadX = max(2.0, ExpandDistance * 0.9)
        PadY = max(3.0, ExpandDistance * 1.15)
        LeftX = max(0, int(math.floor((BoxX - PadX) * ScaleX)))
        TopY = max(0, int(math.floor((BoxY - PadY) * ScaleY)))
        RightX = min(OriginalWidth, int(math.ceil((BoxX + BoxWidth + PadX) * ScaleX)))
        BottomY = min(OriginalHeight, int(math.ceil((BoxY + BoxHeight + PadY) * ScaleY)))
        if RightX - LeftX >= 8 and 8 <= (BottomY - TopY) <= MaxLineHeight:
            RawBoxes.append((LeftX, TopY, RightX, BottomY))

    if not RawBoxes:
        return []

    BoxHeights = [BoxTuple[3] - BoxTuple[1] for BoxTuple in RawBoxes]
    RowTolerance = max(8.0, 0.5 * float(NumpyLib.median(BoxHeights)))
    RawBoxes.sort(key=lambda BoxTuple: (BoxTuple[1], BoxTuple[0]))

    VisualRows = []
    for BoxTuple in RawBoxes:
        CenterY = 0.5 * (BoxTuple[1] + BoxTuple[3])
        WasPlaced = False
        for ExistingRow in VisualRows:
            RowMeanY = float(NumpyLib.mean([0.5 * (MemberBox[1] + MemberBox[3]) for MemberBox in ExistingRow]))
            if abs(CenterY - RowMeanY) <= RowTolerance:
                ExistingRow.append(BoxTuple)
                WasPlaced = True
                break
        if not WasPlaced:
            VisualRows.append([BoxTuple])

    OrderedBoxes = []
    for VisualRow in sorted(VisualRows, key=lambda RowList: min(MemberBox[1] for MemberBox in RowList)):
        VisualRow.sort(key=lambda MemberBox: MemberBox[0])
        OrderedBoxes.extend(VisualRow)
    return OrderedBoxes


def PreprocessRecognitionCrop(CropRgbArray):
    """Chuẩn hoá crop dòng chữ về `(1, 3, 64, W)` trong dải `[-1, 1]` cho VieSVTR v7."""
    CropHeight, CropWidth = CropRgbArray.shape[:2]
    ScaledWidth = int(math.ceil(RecognitionHeight * float(CropWidth) / max(1.0, float(CropHeight))))
    AlignedWidth = int(math.ceil(ScaledWidth / RecognitionWidthStride) * RecognitionWidthStride)
    TargetWidth = max(RecognitionWidthMin, min(AlignedWidth, RecognitionWidthMax))
    InterpolationMode = OpenCvLib.INTER_AREA if CropHeight > RecognitionHeight else OpenCvLib.INTER_LINEAR
    ResizedCrop = OpenCvLib.resize(CropRgbArray, (TargetWidth, RecognitionHeight), interpolation=InterpolationMode)
    FloatTensor = ResizedCrop.astype(NumpyLib.float32).transpose(2, 0, 1)[NumpyLib.newaxis, ...] / 255.0
    return NumpyLib.ascontiguousarray((FloatTensor - 0.5) / 0.5)


def DecodeCtcGreedy(LogitsArray) -> tuple:
    """Giải mã CTC logits `(T, V)` của VieSVTR thành `(Text, MeanConfidence)`."""
    LogitsFloat = NumpyLib.asarray(LogitsArray, dtype=NumpyLib.float32)
    if LogitsFloat.ndim == 3:
        LogitsFloat = LogitsFloat[0]
    if LogitsFloat.ndim != 2 or LogitsFloat.shape[0] == 0:
        return "", 0.0
    ShiftedLogits = LogitsFloat - LogitsFloat.max(axis=-1, keepdims=True)
    ExpValues = NumpyLib.exp(ShiftedLogits)
    Probabilities = ExpValues / ExpValues.sum(axis=-1, keepdims=True)
    TokenIds = Probabilities.argmax(axis=-1)
    TokenConfs = Probabilities.max(axis=-1)

    DecodedChars = []
    PreviousToken = -1
    VocabLength = len(VietOcrVocabulary)
    for TokenId in TokenIds.tolist():
        if TokenId != PreviousToken and TokenId != 0 and 1 <= TokenId <= VocabLength:
            DecodedChars.append(VietOcrVocabulary[TokenId - 1])
        PreviousToken = TokenId

    NonBlankMask = TokenIds != 0
    MeanConfidence = float(TokenConfs[NonBlankMask].mean()) if bool(NumpyLib.any(NonBlankMask)) else 0.0
    NormalizedText = unicodedata.normalize("NFC", "".join(DecodedChars)).strip()
    return NormalizedText, float(NumpyLib.clip(MeanConfidence, 0.0, 1.0))


def EstimateReceiptSkewAngle(ProbabilityMap) -> float:
    """Ước lượng góc nghiêng (độ) của dòng chữ trên hoá đơn từ bản đồ xác suất DBNet."""
    ProbArray = NumpyLib.asarray(ProbabilityMap, dtype=NumpyLib.float32)
    while ProbArray.ndim > 2:
        ProbArray = ProbArray[0]
    BinaryMap = (ProbArray > DetectionBinaryThreshold).astype(NumpyLib.uint8)
    ContourList, UnusedHierarchy = OpenCvLib.findContours(BinaryMap, OpenCvLib.RETR_LIST, OpenCvLib.CHAIN_APPROX_SIMPLE)

    MeasuredAngles = []
    for ContourItem in ContourList:
        if len(ContourItem) < 5:
            continue
        UnusedX, UnusedY, BoxWidth, BoxHeight = OpenCvLib.boundingRect(ContourItem)
        if BoxWidth < 40 or float(BoxWidth) / max(1.0, float(BoxHeight)) < 3.0:
            continue
        FittedLine = OpenCvLib.fitLine(ContourItem, OpenCvLib.DIST_L2, 0, 0.01, 0.01)
        VectorX = float(FittedLine[0][0])
        VectorY = float(FittedLine[1][0])
        if VectorX < 0.0:
            VectorX = -VectorX
            VectorY = -VectorY
        AngleDegrees = math.degrees(math.atan2(VectorY, VectorX))
        if abs(AngleDegrees) <= 15.0:
            MeasuredAngles.append(AngleDegrees)

    if len(MeasuredAngles) < 3:
        return 0.0
    return float(NumpyLib.median(MeasuredAngles))


def DeskewReceiptImage(RgbImageArray, SkewAngleDegrees: float):
    """Xoay nhẹ ảnh hoá đơn về phương ngang để không bị lệch hàng tên món - giá tiền."""
    ImageHeight, ImageWidth = RgbImageArray.shape[:2]
    CenterPoint = (ImageWidth * 0.5, ImageHeight * 0.5)
    RotationMatrix = OpenCvLib.getRotationMatrix2D(CenterPoint, SkewAngleDegrees, 1.0)
    return OpenCvLib.warpAffine(
        RgbImageArray,
        RotationMatrix,
        (ImageWidth, ImageHeight),
        flags=OpenCvLib.INTER_LINEAR,
        borderMode=OpenCvLib.BORDER_REPLICATE,
    )


def ExtractOcrLinesFromBytes(ImageBytes: bytes) -> dict:
    """Chạy thật PP-OCRv3 DBNet + VieSVTR v7 trên ảnh hoá đơn và trả về danh sách dòng."""
    if not OcrDependenciesAvailable:
        return {
            "engine_available": False,
            "engine_version": "unavailable",
            "lines": [],
            "mean_confidence": 0.0,
            "error_message": OcrImportErrorMessage,
        }

    try:
        DetectionSession, RecognitionSession = _GetOnnxSessions()
        PilImage = Image.open(io.BytesIO(ImageBytes)).convert("RGB")
        RgbOriginal = SuppressRedOverlay(NumpyLib.asarray(PilImage, dtype=NumpyLib.uint8))
        OriginalHeight, OriginalWidth = RgbOriginal.shape[:2]

        DetectionBlob, ScaleX, ScaleY = PreprocessDetectionImage(RgbOriginal)
        DetectionInputName = DetectionSession.get_inputs()[0].name
        DetectionOutputs = DetectionSession.run(None, {DetectionInputName: DetectionBlob})
        ProbabilityMap = DetectionOutputs[0]

        SkewAngleDegrees = EstimateReceiptSkewAngle(ProbabilityMap)
        if 1.5 <= abs(SkewAngleDegrees) <= 15.0:
            RgbOriginal = DeskewReceiptImage(RgbOriginal, SkewAngleDegrees)
            DetectionBlob, ScaleX, ScaleY = PreprocessDetectionImage(RgbOriginal)
            DetectionOutputs = DetectionSession.run(None, {DetectionInputName: DetectionBlob})
            ProbabilityMap = DetectionOutputs[0]

        DetectedBoxes = PostprocessDetectionBoxes(
            NumpyLib.asarray(ProbabilityMap), ScaleX, ScaleY, OriginalWidth, OriginalHeight
        )

        RecognitionInputName = RecognitionSession.get_inputs()[0].name
        RecognizedLines = []
        for BoxCoords in DetectedBoxes:
            LeftX, TopY, RightX, BottomY = BoxCoords
            LineCrop = RgbOriginal[TopY:BottomY, LeftX:RightX]
            if LineCrop.size == 0:
                continue
            RecognitionBlob = PreprocessRecognitionCrop(LineCrop)
            RecognitionOutputs = RecognitionSession.run(None, {RecognitionInputName: RecognitionBlob})
            LogitsTensor = RecognitionOutputs[0]
            LineText, LineConfidence = DecodeCtcGreedy(NumpyLib.asarray(LogitsTensor))
            if LineText:
                RecognizedLines.append(
                    {
                        "text": LineText,
                        "confidence": round(LineConfidence, 4),
                        "box": [int(LeftX), int(TopY), int(RightX), int(BottomY)],
                    }
                )

        MeanConf = (
            sum(LineItem["confidence"] for LineItem in RecognizedLines) / float(len(RecognizedLines))
            if RecognizedLines
            else 0.0
        )
        return {
            "engine_available": True,
            "engine_version": "ppocrv3-viesvtr-v7",
            "lines": RecognizedLines,
            "mean_confidence": round(MeanConf, 4),
            "error_message": "",
        }
    except Exception as RuntimeErrorDetail:
        return {
            "engine_available": False,
            "engine_version": "error",
            "lines": [],
            "mean_confidence": 0.0,
            "error_message": "%s: %s" % (type(RuntimeErrorDetail).__name__, RuntimeErrorDetail),
        }


def _GroupOcrLinesIntoVisualRows(OcrLines: list) -> list:
    """Gộp các hộp văn bản nằm trên cùng một dòng ngang (siết theo chồng lấp chiều dọc)."""
    if not OcrLines:
        return []
    SortedLines = sorted(OcrLines, key=lambda LineObj: (LineObj["box"][1], LineObj["box"][0]))
    Heights = [max(8, LineObj["box"][3] - LineObj["box"][1]) for LineObj in SortedLines]
    SortedHeights = sorted(Heights)
    MedianHeight = SortedHeights[len(SortedHeights) // 2]
    RowTolerance = max(6.0, 0.45 * float(MedianHeight))

    GroupedRows = []
    for LineObj in SortedLines:
        CenterY = 0.5 * (LineObj["box"][1] + LineObj["box"][3])
        BoxHeight = max(1, LineObj["box"][3] - LineObj["box"][1])
        PlacedInRow = False
        for RowBucket in GroupedRows:
            RowMeanY = sum(0.5 * (Member["box"][1] + Member["box"][3]) for Member in RowBucket) / float(len(RowBucket))
            FirstMember = RowBucket[0]
            OverlapTop = max(LineObj["box"][1], FirstMember["box"][1])
            OverlapBottom = min(LineObj["box"][3], FirstMember["box"][3])
            OverlapHeight = max(0, OverlapBottom - OverlapTop)
            MinMemberHeight = max(1, min(BoxHeight, FirstMember["box"][3] - FirstMember["box"][1]))
            OverlapRatio = float(OverlapHeight) / float(MinMemberHeight)
            if OverlapRatio >= 0.55 and abs(CenterY - RowMeanY) <= max(14.0, 0.70 * float(MedianHeight)):
                RowBucket.append(LineObj)
                PlacedInRow = True
                break
            if abs(CenterY - RowMeanY) <= RowTolerance:
                RowBucket.append(LineObj)
                PlacedInRow = True
                break
        if not PlacedInRow:
            GroupedRows.append([LineObj])

    JoinedRowTexts = []
    for RowBucket in GroupedRows:
        RowBucket.sort(key=lambda Member: Member["box"][0])
        CombinedText = " ".join(Member["text"] for Member in RowBucket).strip()
        MeanRowConf = sum(Member["confidence"] for Member in RowBucket) / float(len(RowBucket))
        if CombinedText:
            JoinedRowTexts.append({"text": CombinedText, "confidence": round(MeanRowConf, 4)})
    return JoinedRowTexts


def _ParseVietnameseMoneyToken(RawDigits: str) -> int:
    """Chuyển chuỗi số tiền VN (45.000 / 45,000 / 39 000 / 45000) thành số nguyên VND."""
    DigitsOnly = re.sub(r"[^\d]", "", str(RawDigits or ""))
    return int(DigitsOnly) if DigitsOnly else 0


def _ParseScaledMoneyToken(NumberPart: str, UnitPart: str) -> int:
    """Chuyển chuỗi tiền có đơn vị (70 triệu VNĐ, 2.5 tr, 50 nghìn) thành số nguyên VND."""
    try:
        BaseFloat = float(str(NumberPart or "0").replace(",", "."))
    except ValueError:
        return 0
    NormalizedUnit = _StripVietnameseAccents(UnitPart).strip()
    MultiplierValue = 1
    if NormalizedUnit in ("ty",):
        MultiplierValue = 1_000_000_000
    elif NormalizedUnit in ("trieu", "tr"):
        MultiplierValue = 1_000_000
    elif NormalizedUnit in ("nghin", "ngan"):
        MultiplierValue = 1_000
    return int(round(BaseFloat * MultiplierValue))


def _SanitizeTextForPriceExtraction(SourceText: str) -> str:
    """Loại bỏ ngày, giờ, email, URL, SĐT, mã hoá đơn dài và đơn vị đo trước khi tách số tiền."""
    CleanedText = EmailAddressPattern.sub(" ", str(SourceText or ""))
    CleanedText = UrlDomainPattern.sub(" ", CleanedText)
    CleanedText = DateValuePattern.sub(" ", CleanedText)
    CleanedText = MonthYearValuePattern.sub(" ", CleanedText)
    CleanedText = TimeTokenPattern.sub(" ", CleanedText)
    CleanedText = LongCodeOrPhonePattern.sub(" ", CleanedText)
    CleanedText = UnitQuantityPattern.sub(" ", CleanedText)
    return CleanedText


def _ExtractPriceEntriesFromRow(RowText: str, AllowSpaceSeparated: bool = False) -> list:
    """Trích danh sách giá tiền (gồm cả dạng triệu/nghìn/tỷ và dạng số chuẩn) kèm vị trí trên dòng."""
    CleanedText = _SanitizeTextForPriceExtraction(RowText)
    PriceEntries = []
    MaskedChars = list(CleanedText)

    for ScaledMatch in ScaledPricePattern.finditer(CleanedText):
        ScaledAmount = _ParseScaledMoneyToken(ScaledMatch.group(1), ScaledMatch.group(2))
        if ScaledAmount >= 1000:
            PriceEntries.append(
                {
                    "amount": ScaledAmount,
                    "start": ScaledMatch.start(),
                    "end": ScaledMatch.end(),
                }
            )
            for CharPos in range(ScaledMatch.start(), ScaledMatch.end()):
                MaskedChars[CharPos] = " "

    RemainingText = "".join(MaskedChars)
    FormattedMatches = list(FormattedPricePattern.finditer(RemainingText))
    if not FormattedMatches and not PriceEntries and AllowSpaceSeparated:
        FormattedMatches = list(SpaceSeparatedPricePattern.finditer(RemainingText))

    for NumberMatch in FormattedMatches:
        ParsedAmount = _ParseVietnameseMoneyToken(NumberMatch.group(1))
        if ParsedAmount >= 1000:
            PriceEntries.append(
                {
                    "amount": ParsedAmount,
                    "start": NumberMatch.start(),
                    "end": NumberMatch.end(),
                }
            )

    PriceEntries.sort(key=lambda EntryObj: EntryObj["start"])
    return PriceEntries


def _CleanMerchantName(RawMerchant: str) -> str:
    """Làm sạch tên cửa hàng: bỏ từ khoá tiêu đề hoá đơn và ký tự logo nhiễu ở đầu."""
    CandidateText = str(RawMerchant or "").strip(" .:-–|")
    if not CandidateText:
        return ""
    StrippedWords = []
    Tokens = CandidateText.split()
    IndexCursor = 0
    while IndexCursor < len(Tokens):
        WindowThree = " ".join(Tokens[IndexCursor : IndexCursor + 4])
        WindowTwo = " ".join(Tokens[IndexCursor : IndexCursor + 2])
        if _StripVietnameseAccents(WindowThree) in ("hoa don ban hang", "phieu thanh toan"):
            IndexCursor += 4
            continue
        if _StripVietnameseAccents(WindowTwo) in ("hoa don", "bien lai"):
            IndexCursor += 2
            continue
        StrippedWords.append(Tokens[IndexCursor])
        IndexCursor += 1
    CleanedText = " ".join(StrippedWords).strip(" .:-–|")
    CleanedText = re.sub(r"^(?:[A-Z][a-z]|[^A-Za-zÀ-ỹĐđ0-9]+)\s+(?=[A-ZÀ-ỸĐ]{2,})", "", CleanedText)
    return CleanedText.strip(" .:-–|")


def _InferCategoryFromText(MerchantText: str, ItemsText: str, FullReceiptText: str = "") -> str:
    """Chấm điểm từ khoá theo ranh giới từ (trọng số nơi mua x2) để xếp nhóm chi chuẩn xác."""
    CleanedMerchant = EmailAddressPattern.sub(" ", UrlDomainPattern.sub(" ", str(MerchantText or "")))
    CleanedItems = EmailAddressPattern.sub(" ", UrlDomainPattern.sub(" ", str(ItemsText or "")))
    CleanedFull = EmailAddressPattern.sub(" ", UrlDomainPattern.sub(" ", str(FullReceiptText or "")))
    NormMerchant = _StripVietnameseAccents(CleanedMerchant)
    NormItems = _StripVietnameseAccents(CleanedItems)
    NormFull = _StripVietnameseAccents(CleanedFull)

    BestCategory = "Chưa phân loại"
    BestScore = 0
    for CategoryLabel, KeywordTuple in CategoryKeywordMap.items():
        ScoreValue = 0
        for KeywordItem in KeywordTuple:
            WordBoundaryRegex = r"(?<!\w)" + re.escape(KeywordItem) + r"(?!\w)"
            if re.search(WordBoundaryRegex, NormMerchant):
                ScoreValue += 3
            if re.search(WordBoundaryRegex, NormItems):
                ScoreValue += 2
            elif NormFull and re.search(WordBoundaryRegex, NormFull):
                ScoreValue += 1
        if ScoreValue > BestScore:
            BestScore = ScoreValue
            BestCategory = CategoryLabel
    return BestCategory


def _NormalizeExtractedDate(RawDate: str, FallbackDate: str) -> str:
    """Chuẩn hoá DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY hoặc YYYY-MM-DD về YYYY-MM-DD."""
    if not RawDate:
        return FallbackDate
    if "-" in RawDate and len(RawDate) == 10 and RawDate[:4].isdigit():
        return RawDate
    Parts = re.split(r"[/.\-]", RawDate)
    if len(Parts) == 3 and len(Parts[2]) == 4:
        DayPart, MonthPart, YearPart = Parts
        if DayPart.isdigit() and MonthPart.isdigit() and YearPart.isdigit():
            DayInt = int(DayPart)
            MonthInt = int(MonthPart)
            if 1 <= MonthInt <= 12 and 1 <= DayInt <= 31:
                return "%s-%02d-%02d" % (YearPart, MonthInt, DayInt)
    return FallbackDate


def _DetectTotalPriority(NormalizedRowText: str) -> int:
    """Trả về mức ưu tiên của từ khoá tổng tiền (3 cao nhất -> 1 thấp nhất -> 0 không phải tổng)."""
    if HighPriorityTotalPattern.search(NormalizedRowText):
        return 3
    if MediumPriorityTotalPattern.search(NormalizedRowText):
        return 2
    if LowPriorityTotalPattern.search(NormalizedRowText):
        return 1
    return 0


def ParseReceiptFromOcrLines(OcrLines: list, QualityReport: dict, FallbackDate: str) -> dict:
    """Phân tích các dòng OCR thành ngày, nơi mua, số thực trả, nhóm chi và trạng thái 'Cần đọc lại'."""
    LogicalRows = _GroupOcrLinesIntoVisualRows(OcrLines)
    FullNormalizedText = _StripVietnameseAccents(" ".join(RowItem["text"] for RowItem in LogicalRows))
    IsElectricBill = bool(ElectricBillIndicatorPattern.search(FullNormalizedText))

    MerchantName = ""
    MerchantFromUrl = False
    ExtractedDate = ""
    ExtractedMonthYear = ""
    BestTotalPriority = 0
    BestTotalAmount = 0
    ExpectNextRowTotalPriority = 0
    PendingDiscountRow = False
    PendingItemName = ""
    ParsedItems = []
    ElectricEnergyCost = 0
    ElectricTaxCost = 0

    for RowIndex, RowItem in enumerate(LogicalRows):
        RowText = RowItem["text"]
        NormalizedRowText = _StripVietnameseAccents(RowText)

        if not ExtractedDate:
            DateMatch = DateValuePattern.search(RowText)
            if DateMatch:
                ExtractedDate = _NormalizeExtractedDate(DateMatch.group(1), FallbackDate)
        if not ExtractedMonthYear:
            MonthMatch = MonthYearValuePattern.search(RowText)
            if MonthMatch:
                ExtractedMonthYear = "%s-%02d-01" % (MonthMatch.group(2), int(MonthMatch.group(1)))

        if UrlDomainPattern.search(RowText) and len(RowText.split()) <= 2:
            if RowIndex <= 2 and not MerchantName and "/" in RowText:
                ShopSlug = RowText.rsplit("/", 1)[-1].strip(" .:-")
                if len(ShopSlug) >= 4:
                    MerchantName = ShopSlug
                    MerchantFromUrl = True
            ExpectNextRowTotalPriority = 0
            continue

        if IgnoreLinePattern.search(NormalizedRowText) or TableHeaderPattern.search(NormalizedRowText):
            ExpectNextRowTotalPriority = 0
            PendingItemName = ""
            continue

        TotalPriority = _DetectTotalPriority(NormalizedRowText)
        PriceEntries = _ExtractPriceEntriesFromRow(
            RowText, AllowSpaceSeparated=(TotalPriority > 0 or ExpectNextRowTotalPriority > 0)
        )

        if ExpectNextRowTotalPriority > 0 and PriceEntries:
            NextCandidate = PriceEntries[-1]["amount"]
            if NextCandidate >= 1000 and ExpectNextRowTotalPriority >= BestTotalPriority:
                BestTotalPriority = ExpectNextRowTotalPriority
                BestTotalAmount = NextCandidate
            ExpectNextRowTotalPriority = 0
            PendingItemName = ""
            continue
        ExpectNextRowTotalPriority = 0

        if TotalPriority > 0:
            PendingItemName = ""
            HasNegativeDiscount = bool(
                NegativeDiscountPattern.search(NormalizedRowText)
                or PendingDiscountRow
                or re.search(r"(?:\d+\s*%|[-–]\s*)\d{1,3}(?:[.,]\d{3})+", RowText)
            )
            PendingDiscountRow = False
            if PriceEntries and not HasNegativeDiscount:
                CandidateTotal = PriceEntries[-1]["amount"]
                if CandidateTotal >= 1000 and TotalPriority >= BestTotalPriority:
                    BestTotalPriority = TotalPriority
                    BestTotalAmount = CandidateTotal
            else:
                ExpectNextRowTotalPriority = TotalPriority
            continue

        if DiscountLinePattern.search(NormalizedRowText):
            PendingItemName = ""
            PendingDiscountRow = bool(NegativeDiscountPattern.search(NormalizedRowText) and not PriceEntries)
            continue
        PendingDiscountRow = False

        if IsElectricBill:
            if ElectricEnergyAmountPattern.search(NormalizedRowText) and PriceEntries:
                ElectricEnergyCost = max(EntryObj["amount"] for EntryObj in PriceEntries)
                continue
            if ElectricTaxAmountPattern.search(NormalizedRowText) and PriceEntries:
                ElectricTaxCost = max(EntryObj["amount"] for EntryObj in PriceEntries)
                continue
            if ElectricTierLinePattern.search(NormalizedRowText):
                continue

        if not PriceEntries:
            CleanedCandidate = _SanitizeTextForPriceExtraction(RowText).strip(" .:-–")
            HasAlphabetic = bool(re.search(r"[A-Za-zÀ-ỹĐđ]{2,}", CleanedCandidate))
            IsGenericTitle = bool(re.search(r"^(hoa\s*don\s*ban\s*hang|phieu\s*thanh\s*toan|hoa\s*don)$", NormalizedRowText))
            if "bach hoa xanh" in NormalizedRowText:
                MerchantName = "Bách Hóa Xanh"
                MerchantFromUrl = False
            elif RowIndex <= 3 and (not MerchantName or MerchantFromUrl) and HasAlphabetic and not IsGenericTitle and not re.search(r"\b(ban|ngay|gio)\s*:", NormalizedRowText):
                CleanedBrand = _CleanMerchantName(CleanedCandidate or RowText)
                if CleanedBrand:
                    MerchantName = CleanedBrand
                    MerchantFromUrl = False
            elif HasAlphabetic and not IsGenericTitle and not re.search(r"\b(ban|ngay|gio)\s*:", NormalizedRowText):
                PendingItemName = CleanedCandidate
            continue

        FirstEntry = PriceEntries[0]
        LastEntry = PriceEntries[-1]
        ItemPrice = LastEntry["amount"]
        SanitizedRow = _SanitizeTextForPriceExtraction(RowText)
        RawPrefix = SanitizedRow[: FirstEntry["start"]]
        CleanedLabel = re.sub(r"^\d+[.)]\s*", "", RawPrefix)
        CleanedLabel = re.sub(r"\b\d+(?:[.,]\d+)?\b", " ", CleanedLabel)
        CleanedLabel = re.sub(r"\s+", " ", CleanedLabel).strip(" .:-–,/")

        HasTextInPrefix = bool(re.search(r"[A-Za-zÀ-ỹĐđ]{2,}", CleanedLabel))
        if ItemPrice >= 1000:
            if HasTextInPrefix:
                ParsedItems.append({"name": CleanedLabel, "price": ItemPrice})
                PendingItemName = ""
            elif PendingItemName:
                ResolvedLinePrice = ItemPrice
                if len(PriceEntries) == 1:
                    PrefixBeforePrice = SanitizedRow[: FirstEntry["start"]]
                    QuantityMatch = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*", PrefixBeforePrice)
                    if QuantityMatch:
                        try:
                            ParsedQuantity = float(QuantityMatch.group(1).replace(",", "."))
                            if 0.0 < ParsedQuantity <= 99.0 and ParsedQuantity != 1.0:
                                ResolvedLinePrice = int(round(ParsedQuantity * ItemPrice))
                        except ValueError:
                            pass
                ParsedItems.append({"name": PendingItemName, "price": ResolvedLinePrice})
                PendingItemName = ""

    if IsElectricBill:
        MerchantName = "Hóa đơn tiền điện (EVN)"
        if BestTotalAmount > ElectricTaxCost > 0 and (ElectricEnergyCost <= 0 or ElectricEnergyCost + ElectricTaxCost != BestTotalAmount):
            ElectricEnergyCost = BestTotalAmount - ElectricTaxCost
        if ElectricEnergyCost > 0:
            ParsedItems = [{"name": "Tiền điện tiêu thụ", "price": ElectricEnergyCost}]
            if ElectricTaxCost > 0:
                ParsedItems.append({"name": "Tiền thuế GTGT", "price": ElectricTaxCost})

    PrintedTotalVnd = BestTotalAmount
    ItemsSumVnd = sum(int(ItemObj["price"]) for ItemObj in ParsedItems)
    ActualPaidVnd = PrintedTotalVnd if PrintedTotalVnd > 0 else ItemsSumVnd
    MissingPrintedTotal = bool(PrintedTotalVnd <= 0)

    QualityStatus = QualityReport.get("quality_status", "unknown")
    MeanConfidence = (
        sum(LineItem["confidence"] for LineItem in LogicalRows) / float(len(LogicalRows))
        if LogicalRows
        else 0.0
    )

    HasNoReadableTotal = ActualPaidVnd <= 0
    HasLowQualityOrConf = bool(QualityStatus == "fail" or len(LogicalRows) == 0 or MeanConfidence < 0.45)
    NeedsReread = bool(HasNoReadableTotal or HasLowQualityOrConf or MissingPrintedTotal)
    ReviewStatus = "Cần đọc lại" if NeedsReread else "Sẵn sàng Chốt"
    ReviewNote = ""
    if MissingPrintedTotal and ItemsSumVnd > 0:
        ReviewNote = "Không thấy dòng tổng cộng trên ảnh (có thể bị cắt phần cuối) — đang tạm tính từ tổng các món đọc được."
    elif HasNoReadableTotal:
        ReviewNote = "Chưa đọc được số tiền thanh toán — vui lòng chụp lại rõ nét hơn hoặc nhập tay."
    elif HasLowQualityOrConf:
        ReviewNote = "Chất lượng ảnh hoặc độ tin cậy OCR thấp — cần kiểm tra lại trước khi chốt."

    if not MerchantName:
        MerchantName = "không rõ" if NeedsReread else "Cửa hàng trên hoá đơn"

    if not ParsedItems:
        if PrintedTotalVnd > 0 and not NeedsReread:
            ParsedItems = [{"name": "%s (Tổng thực trả)" % MerchantName, "price": PrintedTotalVnd}]
        else:
            ParsedItems = [{"name": "không rõ (cần bạn nhập hoặc chụp lại rõ nét hơn)", "price": ActualPaidVnd}]

    ItemsCombinedText = " ".join(ItemObj["name"] for ItemObj in ParsedItems)
    SuggestedCategory = _InferCategoryFromText(MerchantName, ItemsCombinedText, FullNormalizedText)
    ResolvedDate = FallbackDate or ExtractedDate or ExtractedMonthYear
    DateSourceNote = (
        "Ngày chụp/tải lên"
        if FallbackDate
        else ("Ngày trên hoá đơn" if (ExtractedDate or ExtractedMonthYear) else "không rõ")
    )

    return {
        "merchant": MerchantName,
        "date": ResolvedDate,
        "date_source": DateSourceNote,
        "extracted_date_in_image": ExtractedDate or ExtractedMonthYear,
        "category": SuggestedCategory,
        "items": ParsedItems,
        "printed_total": PrintedTotalVnd,
        "actual_paid_vnd": ActualPaidVnd,
        "missing_printed_total": MissingPrintedTotal,
        "review_note": ReviewNote,
        "logical_rows": LogicalRows,
        "mean_confidence": round(MeanConfidence, 4),
        "is_uncertain": NeedsReread,
        "needs_reread": NeedsReread,
        "review_status": ReviewStatus,
    }


def ScanReceiptImageBytes(
    ImageBytes: bytes,
    TargetDate: str,
    SourceMode: str = "camera",
    FileName: str = "",
) -> dict:
    """Chạy trọn bộ Quality Gate + ONNX OCR + Parser trên bytes ảnh hoá đơn."""
    QualityReport = AssessReceiptQuality(ImageBytes)
    OcrOutput = ExtractOcrLinesFromBytes(ImageBytes)
    ParsedReceipt = ParseReceiptFromOcrLines(OcrOutput.get("lines", []), QualityReport, TargetDate)
    ParsedReceipt["source"] = SourceMode
    ParsedReceipt["filename"] = FileName
    ParsedReceipt["quality_report"] = QualityReport
    ParsedReceipt["ocr_engine"] = OcrOutput.get("engine_version", "unavailable")
    ParsedReceipt["ocr_engine_available"] = OcrOutput.get("engine_available", False)
    ParsedReceipt["ocr_error"] = OcrOutput.get("error_message", "")
    ParsedReceipt["ocr_lines"] = OcrOutput.get("lines", [])
    ParsedReceipt["weights_directory"] = _ResolveWeightsDirectory()
    return ParsedReceipt


def ScanReceiptImageFile(ImageFilePath: str, TargetDate: str = "", SourceMode: str = "file") -> dict:
    """Đọc file ảnh từ đĩa và chạy ScanReceiptImageBytes."""
    with open(ImageFilePath, "rb") as ImageStream:
        ImageBytes = ImageStream.read()
    FileName = os.path.basename(ImageFilePath)
    return ScanReceiptImageBytes(ImageBytes, TargetDate=TargetDate, SourceMode=SourceMode, FileName=FileName)
