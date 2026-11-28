"""Phân tích chi tiêu theo ngày / tháng, hạn mức tháng và cảnh báo (tính năng phát triển sau CP4).

Chia việc giữa code và AI:
    - Code tính MỌI con số (tổng ngày, tổng tháng, theo nhóm, so tháng trước, dự báo cuối tháng, % hạn mức)
      và sinh cảnh báo theo ngưỡng cố định. Số chính xác đến từng đồng, không làm tròn.
    - AI (call_model) chỉ viết nhận xét và gợi ý tiết kiệm bằng lời từ bảng số code đưa cho.
      Câu nào chứa con số không có trong bảng → bỏ câu đó (chặn AI bịa số).
    - Chỉ gửi số tổng theo ngày / nhóm chi cho model; không gửi tên cửa hàng, ảnh hay từng hóa đơn.
"""
import calendar
import datetime as dt
import hashlib
import json
import re

from ai import call_model
import storage

WARN_RATIO = 0.8  # đã dùng ≥80% hạn mức → cảnh báo vàng
SPIKE_RATIO = 2.0  # chi hôm nay ≥2× trung bình ngày của tháng → nhắc
CATEGORY_RISE_RATIO = 0.3  # nhóm chi tăng ≥30% so với cùng kỳ tháng trước → nhắc
CATEGORY_RISE_MIN_VND = 200_000  # bỏ qua biến động nhỏ

_AI_CACHE: dict[str, list[str]] = {}


def pct(value: float) -> str:
    """93.2 → '93,2%'."""
    return f"{value}".replace(".", ",") + "%"


def vnd(amount: int) -> str:
    """1234000 → '1.234.000 ₫' (đủ số, không làm tròn)."""
    return f"{int(amount):,}".replace(",", ".") + " ₫"


def _month_bounds(day: dt.date) -> tuple[dt.date, dt.date]:
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _previous_month_same_span(day: dt.date) -> tuple[dt.date, dt.date]:
    """Cùng kỳ tháng trước: ngày 1 → cùng ngày (cắt theo số ngày của tháng trước)."""
    first = day.replace(day=1)
    prev_last = first - dt.timedelta(days=1)
    return prev_last.replace(day=1), prev_last.replace(day=min(day.day, prev_last.day))


def _sum(records, start: dt.date, end: dt.date) -> tuple[int, int, dict[str, int]]:
    total, count, by_category = 0, 0, {}
    for record in records:
        try:
            when = dt.date.fromisoformat(str(record.get("date")))
        except ValueError:
            continue
        if start <= when <= end:
            amount = int(record.get("total") or 0)
            total += amount
            count += 1
            category = str(record.get("category") or "không rõ")
            by_category[category] = by_category.get(category, 0) + amount
    return total, count, by_category


def spending_facts(records: list, today: str, monthly_budget: int = 0) -> dict:
    """Số liệu ngày / tháng + cảnh báo, tính hoàn toàn bằng code."""
    day = dt.date.fromisoformat(today)
    month_start, month_end = _month_bounds(day)
    prev_start, prev_end = _previous_month_same_span(day)
    prev_full_start, prev_full_end = _month_bounds(prev_start)

    today_total, today_count, today_categories = _sum(records, day, day)
    month_total, month_count, month_categories = _sum(records, month_start, day)
    prev_span_total, _, prev_categories = _sum(records, prev_start, prev_end)
    prev_month_total, _, _ = _sum(records, prev_full_start, prev_full_end)

    days_elapsed = day.day
    days_in_month = month_end.day
    days_left = days_in_month - days_elapsed
    daily_average = month_total // days_elapsed
    forecast = month_total + daily_average * days_left

    by_day: dict[str, int] = {}
    for record in records:
        if month_start.isoformat() <= str(record.get("date")) <= day.isoformat():
            by_day[record["date"]] = by_day.get(record["date"], 0) + int(record.get("total") or 0)
    peak_date, peak_amount = max(by_day.items(), key=lambda item: item[1]) if by_day else ("", 0)

    categories = [
        {
            "category": name,
            "total": amount,
            "share_pct": round(amount * 100 / month_total, 1) if month_total else 0,
            "prev_same_span": prev_categories.get(name, 0),
        }
        for name, amount in sorted(month_categories.items(), key=lambda item: -item[1])
    ]

    budget = max(int(monthly_budget or 0), 0)
    budget_info = None
    if budget:
        remaining = budget - month_total
        budget_info = {
            "limit": budget,
            "used_pct": round(month_total * 100 / budget, 1),
            "remaining": remaining,
            "safe_per_day": remaining // days_left if days_left and remaining > 0 else 0,
            "forecast_over": max(forecast - budget, 0),
        }

    facts = {
        "today": day.isoformat(),
        "month": f"{day.month:02d}/{day.year}",
        "today_total": today_total,
        "today_count": today_count,
        "today_categories": today_categories,
        "month_total": month_total,
        "month_count": month_count,
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
        "daily_average": daily_average,
        "forecast_month_end": forecast,
        "prev_same_span_total": prev_span_total,
        "prev_month_total": prev_month_total,
        "peak_day": {"date": peak_date, "total": peak_amount},
        "categories": categories,
        "budget": budget_info,
    }
    facts["alerts"] = spending_alerts(facts)
    return facts


def spending_alerts(facts: dict) -> list[dict]:
    """Cảnh báo theo ngưỡng cố định (không dùng AI). level: danger · warn · info."""
    alerts = []
    budget = facts["budget"]
    month = facts["month"]
    if budget:
        if facts["month_total"] >= budget["limit"]:
            alerts.append({
                "level": "danger",
                "title": "Đã vượt hạn mức tháng",
                "text": f"Tháng {month} đã chi {vnd(facts['month_total'])}, vượt hạn mức {vnd(budget['limit'])} "
                        f"{vnd(-budget['remaining'])}.",
            })
        elif facts["month_total"] >= budget["limit"] * WARN_RATIO:
            alerts.append({
                "level": "warn",
                "title": "Sắp chạm hạn mức",
                "text": f"Đã dùng {pct(budget['used_pct'])} hạn mức ({vnd(facts['month_total'])} / {vnd(budget['limit'])}). "
                        f"Còn {vnd(budget['remaining'])} cho {facts['days_in_month'] - facts['days_elapsed']} ngày.",
            })
        if budget["forecast_over"] > 0 and facts["month_total"] < budget["limit"]:
            alerts.append({
                "level": "warn",
                "title": "Dự báo vượt hạn mức",
                "text": f"Giữ nhịp {vnd(facts['daily_average'])}/ngày, cuối tháng sẽ chi khoảng "
                        f"{vnd(facts['forecast_month_end'])}, vượt {vnd(budget['forecast_over'])}.",
            })
    if facts["today_total"] and facts["days_elapsed"] > 1 and facts["today_total"] >= facts["daily_average"] * SPIKE_RATIO:
        alerts.append({
            "level": "info",
            "title": "Hôm nay chi nhiều hơn thường lệ",
            "text": f"Hôm nay {vnd(facts['today_total'])}, gấp hơn 2 lần trung bình ngày ({vnd(facts['daily_average'])}).",
        })
    for row in facts["categories"]:
        rise = row["total"] - row["prev_same_span"]
        if row["prev_same_span"] and rise >= CATEGORY_RISE_MIN_VND and rise >= row["prev_same_span"] * CATEGORY_RISE_RATIO:
            alerts.append({
                "level": "info",
                "title": f"{row['category']} tăng so với tháng trước",
                "text": f"{row['category']}: {vnd(row['total'])}, cùng kỳ tháng trước {vnd(row['prev_same_span'])} "
                        f"(tăng {vnd(rise)}).",
            })
    return alerts


INSIGHT_PROMPT = (
    "Bạn là trợ lý chi tiêu cá nhân. Dựa CHỈ trên bảng số liệu JSON (số tiền VND đã tính sẵn), viết 3–4 dòng tiếng Việt, "
    "mỗi dòng bắt đầu bằng '- ' và dưới 30 từ:\n"
    "1) nhận xét chi tiêu hôm nay; 2) nhận xét cả tháng (so với cùng kỳ tháng trước, hạn mức nếu có); "
    "3–4) gợi ý tiết kiệm cụ thể nhắm vào nhóm chi lớn nhất hoặc tăng mạnh nhất.\n"
    "Quy tắc: chỉ dùng con số có trong bảng, chép đúng dạng số tiền như '1.234.000 ₫', không tự tính số mới, "
    "không làm tròn. Giọng nhẹ nhàng, gợi ý chứ không phán xét. Không tư vấn đầu tư, vay, thẻ tín dụng."
)


def _model_table(facts: dict) -> dict:
    """Bảng số gửi model: chỉ số tổng, đã định dạng sẵn để model chép nguyên văn."""
    budget = facts["budget"]
    return {
        "hom_nay": facts["today"],
        "chi_hom_nay": vnd(facts["today_total"]),
        "so_hoa_don_hom_nay": facts["today_count"],
        "nhom_chi_hom_nay": {name: vnd(amount) for name, amount in facts["today_categories"].items()},
        "thang": facts["month"],
        "chi_thang_den_hom_nay": vnd(facts["month_total"]),
        "so_hoa_don_thang": facts["month_count"],
        "trung_binh_ngay": vnd(facts["daily_average"]),
        "du_bao_cuoi_thang": vnd(facts["forecast_month_end"]),
        "cung_ky_thang_truoc": vnd(facts["prev_same_span_total"]),
        "ngay_chi_nhieu_nhat": {"ngay": facts["peak_day"]["date"], "so_tien": vnd(facts["peak_day"]["total"])},
        "theo_nhom": [
            {"nhom": row["category"], "thang_nay": vnd(row["total"]), "ty_trong": pct(row["share_pct"]),
             "cung_ky_thang_truoc": vnd(row["prev_same_span"])}
            for row in facts["categories"]
        ],
        "han_muc": None if not budget else {
            "han_muc_thang": vnd(budget["limit"]), "da_dung": pct(budget["used_pct"]),
            "con_lai": vnd(budget["remaining"]), "nen_chi_moi_ngay": vnd(budget["safe_per_day"]),
        },
        "canh_bao": [alert["text"] for alert in facts["alerts"]],
    }


def _number_tokens(text: str) -> set[str]:
    """Các con số trong chữ, bỏ dấu phân cách để so: '1.234.000đ' → '1234000', '12,5%' → '125'."""
    return {re.sub(r"[.,]", "", token) for token in re.findall(r"\d[\d.,]*\d|\d", text)}


def grounded_lines(text: str, table: dict) -> list[str]:
    """Giữ dòng mà mọi con số đều có trong bảng số liệu; dòng có số lạ bị bỏ."""
    allowed = _number_tokens(json.dumps(table, ensure_ascii=False))
    lines = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-•* ").strip()
        if line and _number_tokens(line) <= allowed:
            lines.append(line)
    return lines[:4]


def ai_insights(facts: dict) -> dict:
    """Gọi model một lần cho bảng số liệu; cache theo nội dung bảng (bảng không đổi → không gọi lại)."""
    table = _model_table(facts)
    payload = json.dumps(table, ensure_ascii=False)
    key = hashlib.sha256(payload.encode()).hexdigest()
    if key in _AI_CACHE:
        return {"lines": _AI_CACHE[key], "cached": True, "dropped": 0}
    result = call_model(INSIGHT_PROMPT, payload)
    raw_lines = [line for line in result["text"].splitlines() if line.strip()]
    lines = grounded_lines(result["text"], table)
    if result.get("model") != "fake":
        _AI_CACHE[key] = lines
    return {"lines": lines, "cached": False, "dropped": max(len(raw_lines) - len(lines), 0), "model": result.get("model")}


def load_budget(user_id: str = "default_user") -> int:
    return int(storage.LoadUserSettings(user_id).get("monthly_budget") or 0)


def save_budget(amount, user_id: str = "default_user") -> int:
    if type(amount) is not int or amount < 0:
        raise ValueError("Hạn mức phải là số nguyên VND không âm (0 = tắt hạn mức).")
    storage.SaveUserSettings(user_id, {"monthly_budget": amount})
    return amount
