"""Gói backend Python cho SkyBill: Quality Gate, ONNX OCR tiếng Việt, lưu trữ CSDL và API server."""

from backend.ocr_engine import (
    AssessReceiptQuality,
    DefaultWeightsDirectory,
    ExtractOcrLinesFromBytes,
    GetOcrEnvironmentStatus,
    ParseReceiptFromOcrLines,
    ScanReceiptImageBytes,
    ScanReceiptImageFile,
)
