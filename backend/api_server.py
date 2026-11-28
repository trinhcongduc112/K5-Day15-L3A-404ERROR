"""API Web Server độc lập nằm trong folder backend/, phục vụ Frontend SkyBill, CSDL/ và ONNX OCR."""

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
import socket
import sys
import threading
import urllib.parse
import uuid
import webbrowser

BackendDirectory = os.path.dirname(os.path.abspath(__file__))
ProjectRootDirectory = os.path.dirname(BackendDirectory)
CodebaseDirectory = os.path.join(ProjectRootDirectory, "codebase")
FrontendDirectory = os.path.join(CodebaseDirectory, "frontend")

for SearchPath in (ProjectRootDirectory, CodebaseDirectory):
    if SearchPath not in sys.path:
        sys.path.insert(0, SearchPath)

from backend import ocr_engine as OcrEngineModule
from backend import storage_service as BackendStorage
import storage as LegacyStorageModule
import tools as ReceiptTools


def _FindFreePort(PreferredPort: int) -> int:
    """Tìm cổng TCP trống bắt đầu từ PreferredPort trên 127.0.0.1."""
    for CandidatePort in range(PreferredPort, PreferredPort + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as TestSocket:
            if TestSocket.connect_ex(("127.0.0.1", CandidatePort)) != 0:
                return CandidatePort
    return PreferredPort


def _CreateBackendHandler(TracingModule, AnswerFunction):
    class BackendHttpHandler(SimpleHTTPRequestHandler):
        def __init__(SelfInstance, *PositionalArgs, **KeywordArgs):
            super().__init__(*PositionalArgs, directory=FrontendDirectory, **KeywordArgs)

        def log_message(SelfInstance, LogFormat, *PositionalArgs):
            pass

        def _SendJsonResponse(SelfInstance, StatusCode: int, ResponsePayload: dict):
            EncodedBytes = json.dumps(ResponsePayload, ensure_ascii=False).encode("utf-8")
            SelfInstance.send_response(StatusCode)
            SelfInstance.send_header("Content-Type", "application/json; charset=utf-8")
            SelfInstance.send_header("Content-Length", str(len(EncodedBytes)))
            SelfInstance.end_headers()
            SelfInstance.wfile.write(EncodedBytes)

        def _ReadJsonBody(SelfInstance) -> dict:
            ContentLength = int(SelfInstance.headers.get("Content-Length", "0"))
            RawBody = SelfInstance.rfile.read(ContentLength).decode("utf-8") if ContentLength > 0 else "{}"
            ParsedPayload = json.loads(RawBody)
            return ParsedPayload if isinstance(ParsedPayload, dict) else {}

        def _ServeStoredImage(SelfInstance, RelativeUrlPath: str):
            AbsoluteImagePath = BackendStorage.ResolveImageAbsolutePath(RelativeUrlPath)
            if not AbsoluteImagePath:
                SelfInstance._SendJsonResponse(404, {"error": "Không tìm thấy ảnh trong CSDL"})
                return
            MimeType, UnusedEncoding = mimetypes.guess_type(AbsoluteImagePath)
            with open(AbsoluteImagePath, "rb") as ImageStream:
                ImageBytes = ImageStream.read()
            SelfInstance.send_response(200)
            SelfInstance.send_header("Content-Type", MimeType or "image/jpeg")
            SelfInstance.send_header("Content-Length", str(len(ImageBytes)))
            SelfInstance.end_headers()
            SelfInstance.wfile.write(ImageBytes)

        def do_GET(SelfInstance):
            ParsedUrl = urllib.parse.urlparse(SelfInstance.path)
            RoutePath = ParsedUrl.path
            QueryParams = urllib.parse.parse_qs(ParsedUrl.query)

            if RoutePath.startswith("/csdl/images/"):
                RelativePath = urllib.parse.unquote(RoutePath[len("/csdl/images/") :])
                SelfInstance._ServeStoredImage(RelativePath)
                return

            if RoutePath == "/api/health":
                OcrStatus = OcrEngineModule.GetOcrEnvironmentStatus()
                ReceiptCount = len(LegacyStorageModule.LoadReceiptRecords("default_user"))
                SelfInstance._SendJsonResponse(
                    200,
                    {
                        "status": "ok",
                        "storage_dir": BackendStorage.StorageRootDirectory,
                        "receipts_count": ReceiptCount,
                        "ocr": OcrStatus,
                    },
                )
                return

            if RoutePath == "/api/receipts":
                ReceiptsList = LegacyStorageModule.LoadReceiptRecords("default_user")
                SelfInstance._SendJsonResponse(200, {"receipts": ReceiptsList})
                return

            if RoutePath == "/api/summary/day":
                TargetDate = (QueryParams.get("date") or [""])[0]
                if not TargetDate:
                    SelfInstance._SendJsonResponse(400, {"error": "Thiếu tham số date"})
                    return
                DaySummary = ReceiptTools.get_day_summary("default_user", TargetDate)
                SelfInstance._SendJsonResponse(200, DaySummary)
                return

            if RoutePath == "/api/summary/compare":
                PeriodType = (QueryParams.get("period") or ["month"])[0]
                CurrentKey = (QueryParams.get("current") or [""])[0]
                PreviousKey = (QueryParams.get("previous") or [""])[0]
                ComparisonResult = ReceiptTools.compare_periods("default_user", PeriodType, CurrentKey, PreviousKey)
                SelfInstance._SendJsonResponse(200, ComparisonResult)
                return

            super().do_GET()

        def do_POST(SelfInstance):
            ParsedUrl = urllib.parse.urlparse(SelfInstance.path)
            RoutePath = ParsedUrl.path

            try:
                RequestBody = SelfInstance._ReadJsonBody()
            except Exception as JsonError:
                SelfInstance._SendJsonResponse(400, {"error": "JSON không hợp lệ: %s" % JsonError})
                return

            if RoutePath == "/api/receipts/scan":
                ImageDataUrl = str(RequestBody.get("image_data_url") or "")
                TargetDate = str(RequestBody.get("receipt_date") or "").strip()
                SourceMode = str(RequestBody.get("source_mode") or "camera").strip()
                FileName = str(RequestBody.get("filename") or "").strip()

                if not ImageDataUrl or not TargetDate:
                    SelfInstance._SendJsonResponse(400, {"error": "Thiếu image_data_url hoặc receipt_date"})
                    return

                DraftId = "DRAFT-" + uuid.uuid4().hex[:8].upper()
                try:
                    RelativeImagePath, ImageRawBytes = BackendStorage.SaveBase64ReceiptImage(
                        ImageDataUrl, TargetDate, DraftId
                    )
                except Exception as ImageError:
                    SelfInstance._SendJsonResponse(400, {"error": "Không đọc được dữ liệu ảnh: %s" % ImageError})
                    return

                ScanResult = OcrEngineModule.ScanReceiptImageBytes(
                    ImageRawBytes, TargetDate, SourceMode=SourceMode, FileName=FileName
                )
                ScanResult["draft_id"] = DraftId
                ScanResult["capture_id"] = DraftId
                ScanResult["image_path"] = RelativeImagePath
                ScanResult["user_id"] = "default_user"

                ValidationResult = ReceiptTools.validate_receipt(ScanResult)
                SavedDraft = ReceiptTools.draft_save_receipt("default_user", TargetDate, ScanResult)
                SavedDraft["needs_reread"] = bool(ScanResult.get("needs_reread"))
                SavedDraft["review_status"] = ScanResult.get("review_status") or "Sẵn sàng Chốt"
                SavedDraft["capture_id"] = DraftId

                SelfInstance._SendJsonResponse(
                    200,
                    {
                        "draft": SavedDraft,
                        "validation": ValidationResult,
                        "quality_report": ScanResult.get("quality_report"),
                        "ocr_engine": ScanResult.get("ocr_engine"),
                        "ocr_engine_available": ScanResult.get("ocr_engine_available"),
                        "ocr_error": ScanResult.get("ocr_error"),
                        "ocr_lines": ScanResult.get("ocr_lines", []),
                        "needs_reread": ScanResult.get("needs_reread"),
                        "review_status": ScanResult.get("review_status"),
                    },
                )
                return

            if RoutePath == "/api/receipts/confirm":
                ConfirmedReceipt = BackendStorage.ConfirmDraftToLedger(RequestBody)
                SelfInstance._SendJsonResponse(200, {"receipt": ConfirmedReceipt})
                return

            if RoutePath == "/api/receipts/reset-demo":
                FreshList = LegacyStorageModule.ResetDemoReceiptRecords()
                SelfInstance._SendJsonResponse(200, {"receipts": FreshList})
                return

            if RoutePath == "/api/analyze":
                InputText = str(RequestBody.get("text") or "").strip()
                if not InputText:
                    SelfInstance._SendJsonResponse(400, {"error": "Thiếu trường text"})
                    return
                TracingModule.begin("web")
                try:
                    AnswerResult = AnswerFunction(InputText)
                    TraceSummary, UnusedEvents = TracingModule.end()
                    OutputText = AnswerResult.get("output", "") if isinstance(AnswerResult, dict) else str(AnswerResult)
                    SelfInstance._SendJsonResponse(200, {"output": OutputText, "summary": TraceSummary})
                except Exception as AnalyzeError:
                    TracingModule.end()
                    SelfInstance._SendJsonResponse(500, {"error": "%s: %s" % (type(AnalyzeError).__name__, AnalyzeError)})
                return

            SelfInstance._SendJsonResponse(404, {"error": "Not found"})

        def do_PATCH(SelfInstance):
            ParsedUrl = urllib.parse.urlparse(SelfInstance.path)
            RoutePath = ParsedUrl.path
            if not RoutePath.startswith("/api/receipts/"):
                SelfInstance._SendJsonResponse(404, {"error": "Not found"})
                return
            ReceiptId = urllib.parse.unquote(RoutePath[len("/api/receipts/") :])
            try:
                RequestBody = SelfInstance._ReadJsonBody()
            except Exception as JsonError:
                SelfInstance._SendJsonResponse(400, {"error": "JSON không hợp lệ: %s" % JsonError})
                return
            UpdatedReceipt = LegacyStorageModule.UpdateReceiptRecord(ReceiptId, RequestBody)
            if UpdatedReceipt is None:
                SelfInstance._SendJsonResponse(404, {"error": "Không tìm thấy hoá đơn"})
                return
            SelfInstance._SendJsonResponse(200, {"receipt": UpdatedReceipt})

        def do_DELETE(SelfInstance):
            ParsedUrl = urllib.parse.urlparse(SelfInstance.path)
            RoutePath = ParsedUrl.path
            if not RoutePath.startswith("/api/receipts/"):
                SelfInstance._SendJsonResponse(404, {"error": "Not found"})
                return
            ReceiptId = urllib.parse.unquote(RoutePath[len("/api/receipts/") :])
            WasDeleted = LegacyStorageModule.DeleteReceiptRecord(ReceiptId)
            if not WasDeleted:
                SelfInstance._SendJsonResponse(404, {"error": "Không tìm thấy hoá đơn"})
                return
            SelfInstance._SendJsonResponse(200, {"deleted": True, "id": ReceiptId})

    return BackendHttpHandler


def main() -> int:
    for StreamObject in (sys.stdout, sys.stderr):
        try:
            StreamObject.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ArgParser = argparse.ArgumentParser(description="Chạy Backend API Server cho SkyBill")
    ArgParser.add_argument("--port", type=int, default=8080, help="Cổng lắng nghe (mặc định 8080)")
    ArgParser.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt")
    ParsedArgs = ArgParser.parse_args()

    import tracing
    from agent import answer

    LegacyStorageModule.EnsureStorageLayout()
    OcrStatus = OcrEngineModule.GetOcrEnvironmentStatus()
    ChosenPort = _FindFreePort(ParsedArgs.port)
    WebServer = ThreadingHTTPServer(("127.0.0.1", ChosenPort), _CreateBackendHandler(tracing, answer))
    ServerUrl = "http://127.0.0.1:%d" % ChosenPort

    print("Backend SkyBill đang chạy tại: %s" % ServerUrl)
    print("Thư mục trọng số OCR: %s" % OcrStatus["weights_directory"])
    print("ONNX OCR (%s): %s" % (OcrStatus["engine_version"], "SẴN SÀNG" if OcrStatus["engine_ready"] else "THIẾU GÓI/TRỌNG SỐ"))

    if not ParsedArgs.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(ServerUrl)).start()

    try:
        WebServer.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng Backend SkyBill.")
    finally:
        WebServer.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
