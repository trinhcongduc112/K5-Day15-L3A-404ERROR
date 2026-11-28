"""Kiểm tra chất lượng ảnh và đọc hóa đơn tiếng Việt bằng OCR cục bộ.

Kế thừa trực tiếp thuật toán từ P-163 (quality.py + ocr.py) với trọng số:
- det.onnx (PaddleOCR PP-OCRv3 DBNet)
- viesvtr_v7.onnx (VieSVTR v7 CTC trên bảng chữ cái VietOCR 229 ký tự)
"""

import collections
import datetime
import io
import math
import os
import re
import threading
import unicodedata

from PIL import Image, ImageOps

try:
    import cv2 as OpenCvLib
    import numpy as NumpyLib
    import onnxruntime as OnnxRuntime
    OcrDependenciesAvailable = True
    OcrImportErrorMessage = ""
except Exception as ImportException:
    OpenCvLib = None
    NumpyLib = None
    OnnxRuntime = None
    OcrDependenciesAvailable = False
    OcrImportErrorMessage = "%s: %s" % (type(ImportException).__name__, ImportException)

# Trọng số do Vũ đóng gói (nguồn, giấy phép, SHA-256: backend/weights/ocr-1/ppocrv3-viesvtr-v7/manifest.json).
DefaultWeightsDirectory = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "weights", "ocr-1", "ppocrv3-viesvtr-v7"
)

# Bảng chữ cái VietOCR 229 ký tự (index 0 là CTC blank, ký tự thật bắt đầu từ index 1)
VietOcrVocabulary = (
    "aAàÀảẢãÃáÁạẠăĂằẰẳẲẵẴắẮặẶâÂầẦẩẨẫẪấẤậẬbBcCdDđĐeEèÈẻẺẽẼéÉẹẸêÊềỀểỂễỄếẾệỆ"
    "fFgGhHiIìÌỉỈĩĨíÍịỊjJkKlLmMnNoOòÒỏỎõÕóÓọỌôÔồỒổỔỗỖốỐộỘơƠờỜởỞỡỠớỚợỢpPqQrR"
    "sStTuUùÙủỦũŨúÚụỤưƯừỪửỬữỮứỨựỰvVwWxXyYỳỲỷỶỹỸýÝỵỴzZ0123456789"
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ "
)

# Tham số Quality Gate (từ P-163 quality.py, thích nghi tỉ lệ ảnh hoá đơn dọc/ngang)
QualityCanonicalMaxSide = 960
BlurSaturationVariance = 250.0
MaxGlareAreaRatio = 0.05
MinGlareBlobShare = 0.004
GlareAboveMedianLuminance = 12.0
MinReadableSidePixels = 200
QualityPassThreshold = 0.35

# Tham số PP-OCRv3 DBNet & VieSVTR v7 (từ P-163 ocr.py)
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
CachedSessionError = ""

# Regex phân tích hoá đơn tiếng Việt
PriceTokenPattern = re.compile(
    r"(?:(?<!\d)(\d{1,3}(?:[.,]\d{3})+|\d{4,7})\s*(?:đ|vnđ|vnd|d)?\b)",
    re.IGNORECASE,
)
PaymentAmountPattern = re.compile(r"(?<![\w.,])\d+(?:(?:[.,]| (?=\d{3}(?!\d)))\d{3})*(?:\s*(?:k|nghìn|ngàn|đ|d|vnđ|vnd))?(?![\w.,])", re.IGNORECASE)
DateValuePattern = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})(?!\d)")
TotalKeywordPattern = re.compile(
    r"^(?:(?:tong\s*(?:so\s*)?(?:cong|tien|bill|thanh\s*toan|phai\s*tra)|(?:so\s*)?(?:tien\s*)?(?:can|phai)\s*tra"
    r"|(?:so\s*)?(?:tien\s*)?thanh\s*toan|grand\s*total|total)\b|tong\s*:)",
    re.IGNORECASE,
)
PaidPattern = re.compile(r"^(?:so tien )?(?:thuc tra|da thanh toan|da tra|paid)\b")
TenderPattern = re.compile(r"^(?:tien )?khach (?:dua|tra)\b")
ChangePattern = re.compile(r"^(?:(?:tien )?thua|(?:tien )?tra lai|change)\b")
SubtotalPattern = re.compile(r"^(?:tam tinh|cong tien(?: hang)?|subtotal|tong tien hang)\b")
PaymentFields = (("paid", PaidPattern), ("tender", TenderPattern), ("change", ChangePattern), ("total", TotalKeywordPattern))
CredentialPattern = re.compile(r"\b(?:otp|cvv|cvc|mat khau|ma pin|so the)\b")
# Số thẻ: 4 nhóm x 4 số (4111 2222 3333 4444) hoặc dãy 15-19 số đầu 2-6 qua kiểm Luhn.
# Không dùng ngưỡng 13 số vì mã vạch EAN-13 và mã số thuế trên hoá đơn siêu thị bị chặn nhầm.
CardGroupedPattern = re.compile(r"(?<!\d)\d{4}(?:[ -]\d{4}){3}(?![\d])")
CardDigitsPattern = re.compile(r"(?<![\d-])[2-6]\d{14,18}(?![\d-])")  # đầu số thẻ (IIN) chỉ 2-6


def _passes_luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char) * (2 if index % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0
IgnoreLinePattern = re.compile(
    r"(tien\s*khach|tien\s*thua|tien\s*mat|tra\s*lai|change|cash|cam\s*on|xin\s*cam\s*on|"
    r"hen\s*gap|wifi|mat\s*khau|hotline|dia\s*chi|sdt|dien\s*thoai|ngay[:\s]|gio[:\s]|ma\s*hd|^[-=*_.]{3,}$)",
    re.IGNORECASE,
)

def _StripVietnameseAccents(SourceText: str) -> str:
    """Chuyển tiếng Việt có dấu sang không dấu viết thường để đối chiếu từ khoá OCR ổn định."""
    ReplacedText = str(SourceText or "").replace("đ", "d").replace("Đ", "D")
    Decomposed = unicodedata.normalize("NFD", ReplacedText)
    StrippedChars = [CharItem for CharItem in Decomposed if unicodedata.category(CharItem) != "Mn"]
    return "".join(StrippedChars).lower()


def receipt_has_sensitive_text(text: str) -> bool:
    normalized = _StripVietnameseAccents(text)
    if CredentialPattern.search(normalized) or CardGroupedPattern.search(normalized):
        return True
    return any(_passes_luhn(match) for match in CardDigitsPattern.findall(normalized))


def GetOcrEnvironmentStatus() -> dict:
    """Kiểm tra trạng thái thư viện và file trọng số ONNX trên thiết bị hiện tại."""
    weights = os.environ.get("SKYBILL_OCR_WEIGHTS_DIR") or DefaultWeightsDirectory
    DetectionModelPath = os.path.join(weights, "det.onnx")
    RecognitionModelPath = os.path.join(weights, "viesvtr_v7.onnx")
    DetectionWeightExists = os.path.isfile(DetectionModelPath)
    RecognitionWeightExists = os.path.isfile(RecognitionModelPath)
    onnx_ready = bool(OcrDependenciesAvailable and DetectionWeightExists and RecognitionWeightExists)
    return {
        "dependencies_available": OcrDependenciesAvailable,
        "import_error": OcrImportErrorMessage,
        "weights_directory": weights,
        "det_model_exists": DetectionWeightExists,
        "rec_model_exists": RecognitionWeightExists,
        "onnx_ready": onnx_ready,
        "engine_ready": onnx_ready,
        "engine_version": "ppocrv3-viesvtr-v7" if onnx_ready else "unavailable",
    }


def _GetOnnxSessions() -> tuple:
    """Nạp và lưu cache singleton cho 2 mô hình ONNX trên CPU."""
    global CachedDetectionSession, CachedRecognitionSession, CachedSessionError
    if not OcrDependenciesAvailable:
        raise RuntimeError("Thiếu thư viện OCR/CV: %s" % OcrImportErrorMessage)
    with SessionLock:
        if CachedDetectionSession is not None and CachedRecognitionSession is not None:
            return CachedDetectionSession, CachedRecognitionSession
        weights = os.environ.get("SKYBILL_OCR_WEIGHTS_DIR") or DefaultWeightsDirectory
        DetectionModelPath = os.path.join(weights, "det.onnx")
        RecognitionModelPath = os.path.join(weights, "viesvtr_v7.onnx")
        if not os.path.isfile(DetectionModelPath) or not os.path.isfile(RecognitionModelPath):
            raise FileNotFoundError(
                "Không tìm thấy trọng số det.onnx hoặc viesvtr_v7.onnx tại: %s" % weights
            )
        SessionOptions = OnnxRuntime.SessionOptions()
        SessionOptions.graph_optimization_level = OnnxRuntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        CachedDetectionSession = OnnxRuntime.InferenceSession(
            DetectionModelPath, sess_options=SessionOptions, providers=["CPUExecutionProvider"]
        )
        CachedRecognitionSession = OnnxRuntime.InferenceSession(
            RecognitionModelPath, sess_options=SessionOptions, providers=["CPUExecutionProvider"]
        )
        CachedSessionError = ""
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
    ResolutionScore = 1.0 if MinSide >= MinReadableSidePixels else float(NumpyLib.clip(MinSide / float(MinReadableSidePixels), 0.0, 0.45))
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


def _RunOnnxPassOnRgb(RgbImageArray, DetectionSession, RecognitionSession) -> tuple:
    """Chạy một lượt phát hiện + nhận dạng ONNX trên ảnh RGB đã chọn hướng."""
    OriginalHeight, OriginalWidth = RgbImageArray.shape[:2]
    DetectionBlob, ScaleX, ScaleY = PreprocessDetectionImage(RgbImageArray)
    DetectionInputName = DetectionSession.get_inputs()[0].name
    DetectionOutputs = DetectionSession.run(None, {DetectionInputName: DetectionBlob})
    ProbabilityMap = DetectionOutputs[0]
    DetectedBoxes = PostprocessDetectionBoxes(
        NumpyLib.asarray(ProbabilityMap), ScaleX, ScaleY, OriginalWidth, OriginalHeight
    )

    RecognitionInputName = RecognitionSession.get_inputs()[0].name
    RecognizedLines = []
    for BoxCoords in DetectedBoxes:
        LeftX, TopY, RightX, BottomY = BoxCoords
        LineCrop = RgbImageArray[TopY:BottomY, LeftX:RightX]
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
    return RecognizedLines, MeanConf


def _extract_onnx_lines(ImageBytes: bytes) -> dict:
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
        RecognizedLines, MeanConf = _RunOnnxPassOnRgb(RgbOriginal, DetectionSession, RecognitionSession)

        # Nếu ảnh bị chụp xoay ngang 90° khiến OCR đọc được rất ít dòng hoặc độ tin cậy thấp, thử xoay ±90°.
        if len(RecognizedLines) < 8 or MeanConf < 0.50:
            BestLines = RecognizedLines
            BestMeanConf = MeanConf
            BestScore = float(len(RecognizedLines)) * MeanConf
            for RotateCode in (OpenCvLib.ROTATE_90_CLOCKWISE, OpenCvLib.ROTATE_90_COUNTERCLOCKWISE):
                RotatedRgb = OpenCvLib.rotate(RgbOriginal, RotateCode)
                CandLines, CandMeanConf = _RunOnnxPassOnRgb(RotatedRgb, DetectionSession, RecognitionSession)
                CandScore = float(len(CandLines)) * CandMeanConf
                if CandMeanConf >= 0.55 and CandScore > BestScore * 1.5:
                    BestLines = CandLines
                    BestMeanConf = CandMeanConf
                    BestScore = CandScore
            RecognizedLines, MeanConf = BestLines, BestMeanConf

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


def ExtractOcrLinesFromBytes(image_bytes: bytes) -> dict:
    """Đọc dòng chữ bằng ONNX (PP-OCRv3 + VieSVTR v7); thiếu thư viện/trọng số thì báo OCR chưa sẵn sàng."""
    if not GetOcrEnvironmentStatus()["onnx_ready"]:
        return {
            "engine_available": False, "engine_version": "unavailable", "lines": [],
            "error_message": "Thiếu thư viện OCR hoặc trọng số ONNX trong backend/weights/ocr-1/ppocrv3-viesvtr-v7/.",
        }
    return _extract_onnx_lines(image_bytes)


def _GroupOcrLinesIntoVisualRows(OcrLines: list) -> list:
    """Gộp các hộp văn bản nằm trên cùng một dòng ngang (tên món + giá tiền bên phải)."""
    if not OcrLines:
        return []
    SortedLines = sorted(OcrLines, key=lambda LineObj: (LineObj["box"][1], LineObj["box"][0]))
    Heights = [max(8, LineObj["box"][3] - LineObj["box"][1]) for LineObj in SortedLines]
    SortedHeights = sorted(Heights)
    MedianHeight = SortedHeights[len(SortedHeights) // 2]
    RowTolerance = max(10.0, 0.65 * float(MedianHeight))

    GroupedRows = []
    for LineObj in SortedLines:
        CenterY = 0.5 * (LineObj["box"][1] + LineObj["box"][3])
        PlacedInRow = False
        for RowBucket in GroupedRows:
            RowCenterY = sum(0.5 * (Member["box"][1] + Member["box"][3]) for Member in RowBucket) / float(len(RowBucket))
            if abs(CenterY - RowCenterY) <= RowTolerance:
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
    """Chuyển chuỗi số tiền VN (45.000 / 45,000 / 45000) thành số nguyên VND."""
    DigitsOnly = re.sub(r"[^\d]", "", str(RawDigits or ""))
    return int(DigitsOnly) if DigitsOnly else 0


def normalize_receipt_date(raw_date: str) -> str:
    """Chuẩn hóa ngày in ISO, DD/MM/YYYY hoặc DD-MM-YYYY; bỏ qua năm lỗi OCR ngoài [1990, 2100]."""
    try:
        first, second, third = re.split(r"[-/]", raw_date)
        parsed = (
            datetime.date(int(first), int(second), int(third))
            if len(first) == 4
            else datetime.date(int(third), int(second), int(first))
        )
        return parsed.isoformat() if 1990 <= parsed.year <= 2100 else ""
    except (TypeError, ValueError):
        return ""


def parse_vnd_amount(token: str) -> int | None:
    """Chuyển 45.000đ, 38k hoặc 70000 thành VND nguyên."""
    compact = re.sub(r"\s+", "", _StripVietnameseAccents(token))
    match = re.fullmatch(r"(\d+(?:[.,]\d{3})*)(k|nghin|ngan)?(?:d|vnd)?", compact)
    return _ParseVietnameseMoneyToken(match[1]) * (1000 if match[2] else 1) if match else None


def _payment_field(normalized_line: str) -> str | None:
    # OCR hay dính ký tự rác đầu dòng ("“ Tổng:", ".... Tổng tiền"), bỏ trước khi so mẫu.
    normalized_line = re.sub(r"^[^a-z0-9]+", "", normalized_line)
    if SubtotalPattern.search(normalized_line):
        return "subtotal"
    return next((key for key, pattern in PaymentFields if pattern.search(normalized_line)), None)


def read_paid_total(lines) -> int:
    """Chọn số thực trả từ các dòng thanh toán, hoặc trả 0 khi thiếu hay mâu thuẫn."""
    amounts = {key: set() for key, _ in PaymentFields}
    supporting_rows = collections.Counter()
    noisy = False
    for line in lines:
        normalized = _StripVietnameseAccents(line).strip()
        field = _payment_field(normalized)
        if field in amounts:
            row_amounts = set()
            for token in PaymentAmountPattern.findall(line):
                amount = parse_vnd_amount(token)
                if amount is None:
                    continue
                # Số lẻ < 500đ là số lượng hoặc mảnh số OCR tách rời ("Tổng: 1 39 000"): bỏ nhưng đánh dấu nhiễu.
                if amount < 500:
                    noisy = True
                    continue
                row_amounts.add(amount)
            amounts[field] |= row_amounts
            supporting_rows.update(row_amounts)

    paid, totals, tender, change = (amounts[key] for key in ("paid", "total", "tender", "change"))
    if paid:
        result = next(iter(paid)) if len(paid) == 1 else 0
    elif len(totals) > 1 or len(tender) > 1 or len(change) > 1:
        result = 0
    else:
        printed = next(iter(totals), 0)
        if not tender:
            result = printed
        elif not printed and not change:
            result = 0
        else:
            cash_paid = next(iter(tender)) - next(iter(change), 0)
            result = cash_paid if cash_paid > 0 and printed in {0, cash_paid} else 0
    # Khi đã bỏ mảnh số nhiễu, chỉ tin số tiền có ít nhất 2 dòng thanh toán cùng xác nhận.
    if noisy and result and supporting_rows[result] < 2:
        return 0
    return result


MerchantSkipPattern = re.compile(
    r"h[oa]+ don|phieu|ban hang|nhan vien|thu ngan|khach hang|^\W*d[cq]\b|duong|phuong|quan \d|so hd|ma so thue|mst"
)


def _LooksLikeMerchantName(RowItem: dict) -> bool:
    """Dòng tên cửa hàng: đủ tin cậy, phần lớn là chữ, không phải dòng địa chỉ/điện thoại."""
    Letters = sum(CharItem.isalpha() for CharItem in RowItem["text"])
    NonSpace = sum(not CharItem.isspace() for CharItem in RowItem["text"])
    return (
        RowItem["confidence"] >= 0.6
        and Letters >= 4
        and Letters >= 0.7 * NonSpace
        and not IgnoreLinePattern.search(_StripVietnameseAccents(RowItem["text"]))
        and not MerchantSkipPattern.search(_StripVietnameseAccents(RowItem["text"]))
    )


# --- Chọn tổng tiền theo mức ưu tiên từ khoá cho dòng ONNX (port từ backend/ocr_engine.py của Vũ, nhánh
# nguyenquangvu_2A202603407). Bỏ phần "không thấy tổng thì cộng các món" để không đoán số thực trả.
ImageTotalHighPattern = re.compile(
    r"(phai\s*thanh\s*toan|tong\s*cong|tong\s*so\s*thanh\s*toan|tong\s*tien\s*phai\s*t\.?\s*toan|"
    r"tien\s*thanh\s*toan|tong\s*tien\b(?!\s*hang)|grand\s*total|\btotal\b)"
)
ImageTotalMediumPattern = re.compile(r"(cong\s*tien\s*hang|cong\s*tien|thanh\s*toan)")
ImageTotalLowPattern = re.compile(r"(tong\s*tien\s*hang|\bthanh\s*cong\b)")
ImageSkipRowPattern = re.compile(
    r"(tien\s*khach|tien\s*dua|khach\s*(?:dua|tra)|tien\s*thua|tien\s*mat|tra\s*lai|change|cash|"
    r"don\s*gia|thanh\s*tien|ten\s*hang)"
)
# Dòng số lượng ("Tổng số lượng hàng: 2"): bỏ, trừ khi OCR gộp nó với dòng tổng mạnh trên cùng hàng ngang
# ("Tong so tien thanh toan: Tong so luong hang: 18,200.00", ảnh quwvb). Số lượng < 1000 nên không lẫn vào giá.
ImageQuantityRowPattern = re.compile(r"(tong\s*so\b(?!\s*(?:tien|thanh))|so\s*luong)")
ImageDiscountPattern = re.compile(r"(chiet\s*khau|giam\s*gia|khuyen\s*mai)")
ImageNegativeDiscountRowPattern = re.compile(r"(?:da|a)\s*giam|giam\s*tru")
ImagePricePattern = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d{3})+|\d{1,3}(?:,\d{3})+|\d{4,7})(?!\d)")
ImageSpacePricePattern = re.compile(r"(?<!\d)(\d{1,3}\s\d{3})(?!\d)")
ImageNoisePattern = re.compile(
    r"(?:https?://|www\.)\S+|\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b|\b\d{1,2}:\d{2}(?::\d{2})?\b"
    r"|\b0\d{8,10}\b|\b[A-Za-z]*\d{8,}[A-Za-z0-9]*\b|\b\d+(?:[.,]\d+)?\s*(?:g|kg|ml|l)\b",
    re.IGNORECASE,
)


def _ImageRowPrices(RowText: str, AllowSpace: bool) -> list:
    """Các số tiền trong một dòng OCR sau khi bỏ ngày, giờ, SĐT, mã dài, đơn vị đo."""
    Cleaned = ImageNoisePattern.sub(" ", RowText)
    Found = ImagePricePattern.findall(Cleaned) or (ImageSpacePricePattern.findall(Cleaned) if AllowSpace else [])
    return [Amount for Amount in (_ParseVietnameseMoneyToken(Token) for Token in Found) if Amount >= 1000]


def read_image_total(LogicalRows: list) -> int:
    """Số thực trả từ dòng OCR ảnh: dòng tổng có ưu tiên cao nhất (số có thể nằm ở dòng kế tiếp).

    Trả 0 khi không thấy dòng tổng, hoặc khi hai dòng cùng mức ưu tiên cao nhất ghi hai số khác nhau.
    """
    Best = {}  # mức ưu tiên → tập số tiền
    PendingPriority = 0
    for RowItem in LogicalRows:
        Normalized = re.sub(r"^[^a-z0-9]+", "", _StripVietnameseAccents(RowItem["text"]))
        HighTotal = ImageTotalHighPattern.search(Normalized)
        if ImageSkipRowPattern.search(Normalized) or (ImageQuantityRowPattern.search(Normalized) and not HighTotal):
            PendingPriority = 0
            continue
        Priority = (3 if HighTotal else 2 if ImageTotalMediumPattern.search(Normalized)
                    else 1 if ImageTotalLowPattern.search(Normalized) else 0)
        Prices = _ImageRowPrices(RowItem["text"], AllowSpace=bool(Priority or PendingPriority))
        if PendingPriority and Prices and not Priority:
            Best.setdefault(PendingPriority, set()).add(Prices[-1])
            PendingPriority = 0
            continue
        PendingPriority = 0
        IsNegativeDiscountRow = bool(
            ImageNegativeDiscountRowPattern.search(Normalized) and re.search(r"-\s*\d", RowItem["text"])
        )
        if Priority and not ImageDiscountPattern.search(Normalized) and not IsNegativeDiscountRow:
            if Prices:
                Best.setdefault(Priority, set()).add(Prices[-1])
            else:
                PendingPriority = Priority
    if not Best:
        return 0
    TopAmounts = Best[max(Best)]
    return next(iter(TopAmounts)) if len(TopAmounts) == 1 else 0


def ParseReceiptFromOcrLines(OcrLines: list, QualityReport: dict, FallbackDate: str) -> dict:
    """Phân tích các dòng OCR thành cấu trúc hoá đơn có kiểm tra G10 khi ảnh mờ/thiếu.

    Nhóm chi không chọn ở đây: web và answer() cùng gọi agent.choose_category().
    """
    LogicalRows = _GroupOcrLinesIntoVisualRows(OcrLines)
    MerchantName = ""
    ExtractedDate = ""
    ParsedItems = []

    for RowIndex, RowItem in enumerate(LogicalRows):
        RowText = RowItem["text"]
        NormalizedRowText = _StripVietnameseAccents(RowText)
        if not ExtractedDate:
            DateMatch = DateValuePattern.search(RowText)
            if DateMatch:
                ExtractedDate = normalize_receipt_date(DateMatch.group(1))

        if _payment_field(NormalizedRowText):
            continue

        if IgnoreLinePattern.search(NormalizedRowText):
            continue

        PriceMatches = list(PriceTokenPattern.finditer(RowText))
        if not PriceMatches:
            if RowIndex <= 5 and not MerchantName and _LooksLikeMerchantName(RowItem):
                MerchantName = RowText.strip(" .:-–—_|`'\"“”")
            continue

        LastMatch = PriceMatches[-1]
        ItemPrice = _ParseVietnameseMoneyToken(LastMatch.group(1))
        ItemLabel = RowText[: LastMatch.start()].strip(" .:-–0123456789")
        ItemLabel = re.sub(r"^\d+[.)]\s*", "", RowText[: LastMatch.start()]).strip(" .:-–")
        if ItemPrice > 0 and ItemLabel:
            ParsedItems.append({"name": ItemLabel, "price": ItemPrice})

    PrintedTotalVnd = read_image_total(LogicalRows)
    QualityStatus = QualityReport.get("quality_status", "unknown")
    MeanConfidence = (
        sum(LineItem["confidence"] for LineItem in LogicalRows) / float(len(LogicalRows))
        if LogicalRows
        else 0.0
    )
    uncertain_payment_row = any(
        row["confidence"] < 0.55
        and _payment_field(_StripVietnameseAccents(row["text"])) in {"paid", "total", "tender", "change"}
        and PaymentAmountPattern.search(row["text"])
        for row in LogicalRows
    )

    IsUncertain = bool(
        QualityStatus == "fail"
        or len(LogicalRows) == 0
        or PrintedTotalVnd <= 0
        or MeanConfidence < 0.45
        or uncertain_payment_row
        or (ExtractedDate and FallbackDate and ExtractedDate > FallbackDate)
    )

    if not MerchantName:
        MerchantName = "không rõ" if IsUncertain else "Cửa hàng trên hoá đơn"

    return {
        "merchant": MerchantName,
        "date": ExtractedDate or FallbackDate,
        "date_source": "hóa đơn" if ExtractedDate else "ngày chụp",
        "extracted_date_in_image": ExtractedDate,
        "items": ParsedItems,
        "printed_total": PrintedTotalVnd,
        "logical_rows": LogicalRows,
        "mean_confidence": round(MeanConfidence, 4),
        "is_uncertain": IsUncertain,
    }


def ScanReceiptImageBytes(
    ImageBytes: bytes,
    TargetDate: str,
    SourceMode: str = "camera",
    FileName: str = "",
) -> dict:
    """Chạy Quality Gate, OCR cục bộ và trích trường cho luồng chụp hóa đơn."""
    try:
        with Image.open(io.BytesIO(ImageBytes)) as uploaded:
            if uploaded.format not in {"JPEG", "PNG", "WEBP"} or uploaded.width * uploaded.height > 24_000_000:
                raise ValueError("Định dạng ảnh chưa hỗ trợ hoặc ảnh quá lớn.")
            image = ImageOps.exif_transpose(uploaded).convert("RGB")
            image.thumbnail((2000, 2000))
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            ImageBytes = buffer.getvalue()
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError("Không đọc được ảnh. Hãy chọn ảnh JPG, PNG hoặc WEBP.") from error
    QualityReport = AssessReceiptQuality(ImageBytes)
    OcrOutput = ExtractOcrLinesFromBytes(ImageBytes)
    lines = OcrOutput.get("lines", [])
    metadata = {
        "quality_report": QualityReport,
        "ocr_engine": OcrOutput.get("engine_version", "unavailable"),
        "ocr_engine_available": OcrOutput.get("engine_available", False),
        "ocr_error": OcrOutput.get("error_message", ""),
    }
    if receipt_has_sensitive_text(" ".join(row["text"] for row in lines)):
        return {**metadata, "blocked": True}
    ParsedReceipt = ParseReceiptFromOcrLines(lines, QualityReport, TargetDate)
    ParsedReceipt["source"] = SourceMode
    ParsedReceipt["filename"] = FileName
    ParsedReceipt["ocr_line_count"] = len(ParsedReceipt["logical_rows"])
    return {**ParsedReceipt, **metadata}
