"""Công cụ CLI chạy lại được để kiểm tra Quality Gate và ONNX OCR trên ảnh hoá đơn thật."""

import argparse
import json
import os
import sys

BackendDirectory = os.path.dirname(os.path.abspath(__file__))
ProjectRootDirectory = os.path.dirname(BackendDirectory)
if ProjectRootDirectory not in sys.path:
    sys.path.insert(0, ProjectRootDirectory)

from backend.ocr_engine import GetOcrEnvironmentStatus, ScanReceiptImageFile


def FormatCliSummary(ImageFilePath: str, TargetDate: str = "") -> dict:
    """Chạy OCR trên một file ảnh và gom các trường bàn giao theo PHAN-CONG.md."""
    ScanOutput = ScanReceiptImageFile(ImageFilePath, TargetDate=TargetDate, SourceMode="cli")
    return {
        "image_file": os.path.relpath(ImageFilePath, ProjectRootDirectory).replace(os.sep, "/"),
        "model_version": ScanOutput.get("ocr_engine"),
        "weights_directory": ScanOutput.get("weights_directory"),
        "engine_available": ScanOutput.get("ocr_engine_available"),
        "quality_report": ScanOutput.get("quality_report"),
        "ocr_lines_count": len(ScanOutput.get("ocr_lines") or []),
        "mean_confidence": ScanOutput.get("mean_confidence"),
        "date": ScanOutput.get("extracted_date_in_image") or ScanOutput.get("date"),
        "merchant": ScanOutput.get("merchant"),
        "actual_paid_vnd": ScanOutput.get("actual_paid_vnd"),
        "category": ScanOutput.get("category"),
        "needs_reread": ScanOutput.get("needs_reread"),
        "review_status": ScanOutput.get("review_status"),
        "sample_lines": [LineObj["text"] for LineObj in (ScanOutput.get("ocr_lines") or [])[:10]],
        "error": ScanOutput.get("ocr_error") or "",
    }


def main() -> int:
    for StreamObject in (sys.stdout, sys.stderr):
        try:
            StreamObject.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ArgParser = argparse.ArgumentParser(description="Kiểm tra Quality Gate & ONNX OCR từ thư mục backend/")
    ArgParser.add_argument("image_path", nargs="?", help="Đường dẫn ảnh hoá đơn cần quét")
    ArgParser.add_argument("--date", default="", help="Ngày chụp/nhập dự kiến (YYYY-MM-DD)")
    ArgParser.add_argument(
        "--sample-pair",
        action="store_true",
        help="Chạy thử trên 1 ảnh rõ (thuong) và 1 ảnh khó (kho) trong data/receipts/images/",
    )
    ParsedArgs = ArgParser.parse_args()

    EnvStatus = GetOcrEnvironmentStatus()
    if ParsedArgs.sample_pair or not ParsedArgs.image_path:
        ClearSamplePath = os.path.join(ProjectRootDirectory, "data", "receipts", "images", "mcocr_public_145014pevvt.jpg")
        HardSamplePath = os.path.join(ProjectRootDirectory, "data", "receipts", "images", "mcocr_public_145014zxdlo.jpg")
        ResultsList = []
        for SamplePath in (ClearSamplePath, HardSamplePath):
            if os.path.isfile(SamplePath):
                ResultsList.append(FormatCliSummary(SamplePath, TargetDate=ParsedArgs.date))
        OutputPayload = {"environment": EnvStatus, "samples": ResultsList}
        print(json.dumps(OutputPayload, ensure_ascii=False, indent=2))
        return 0

    if not os.path.isfile(ParsedArgs.image_path):
        print(json.dumps({"error": "Không tìm thấy ảnh: %s" % ParsedArgs.image_path}, ensure_ascii=False))
        return 1

    SingleResult = FormatCliSummary(ParsedArgs.image_path, TargetDate=ParsedArgs.date)
    print(json.dumps({"environment": EnvStatus, "result": SingleResult}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
