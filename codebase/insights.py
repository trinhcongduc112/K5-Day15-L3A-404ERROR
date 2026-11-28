"""Phân tích chi tiêu theo ngày / tháng, hạn mức tháng, mục tiêu để dành và cảnh báo (tính năng phát triển sau CP4).

Chia việc giữa code và AI:
    - Code tính MỌI con số (tổng ngày, tổng tháng, theo nhóm, so cùng kỳ tháng trước, dự báo cuối tháng, % hạn mức,
      số dự kiến để dành, kịch bản tiết kiệm theo nhóm) và sinh cảnh báo theo ngưỡng cố định.
      Số chính xác đến từng đồng, không làm tròn.
    - AI (call_model) chỉ viết nhận xét và gợi ý tiết kiệm bằng lời từ bảng số code đưa cho. Code lọc lại từng dòng:
      bỏ dòng có con số không có trong bảng, dòng khuyên cắt nhóm cố định / thiết yếu, dòng nói về đầu tư hay vay.
    - Không tư vấn đầu tư (nhóm đã chốt 28/11/2026): app chỉ gợi ý chi tiêu và để dành.
    - Chỉ gửi số tổng theo ngày / nhóm chi cho model; không gửi tên cửa hàng, ảnh, từng hóa đơn hay thu nhập.
"""
import calendar
import datetime as dt
import hashlib
import json
import re
import unicodedata

from ai import call_model
import storage

WARN_RATIO = 0.8  # đã dùng ≥80% hạn mức → cảnh báo vàng
SPIKE_RATIO = 2.0  # chi hôm nay ≥2× trung bình ngày của tháng → nhắc
CATEGORY_RISE_RATIO = 0.3  # nhóm chi tăng ≥30% so với cùng kỳ tháng trước → nhắc
CATEGORY_RISE_MIN_VND = 200_000  # bỏ qua biến động nhỏ
HABIT_MIN_COUNT = 3  # nhóm chi ≥3 lần/tháng mới gợi ý "bớt một lần"

# Nhóm cố định / thiết yếu: không khuyên cắt (tiền nhà, điện nước, khám chữa bệnh).
FIXED_CATEGORIES = ("Hóa đơn & Nhà ở", "Sức khỏe")
UNKNOWN_CATEGORIES = ("không rõ",)

# Dòng AI nói về sản phẩm tài chính → bỏ (app không tư vấn đầu tư, vay).
FINANCE_ADVICE_PATTERN = re.compile(
    r"đầu\s*tư|chứng\s*khoán|cổ\s*phiếu|trái\s*phiếu|bitcoin|crypto|tiền\s*(?:mã\s*hóa|ảo|số)|\bvàng\b"
    r"|gửi\s*tiết\s*kiệm|lãi\s*suất|\bvay\b|thẻ\s*tín\s*dụng|quỹ\s*(?:mở|etf)",
    re.IGNORECASE,
)
CUT_VERBS = r"(?:giảm|cắt|bớt|hạn\s*chế|kiểm\s*soát|siết|tiết\s*kiệm)"

_AI_CACHE: dict[str, list[str]] = {}


def pct(value: float) -> str:
    """93.2 → '93,2%'."""
    return f"{value}".replace(".", ",") + "%"


def vnd(amount: int) -> str:
    """1234000 → '1.234.000 ₫' (đủ số, không làm tròn)."""
    return f"{int(amount):,}".replace(",", ".") + " ₫"


def _day_month(iso_date: str) -> str:
    return f"{iso_date[8:10]}/{iso_date[5:7]}"


def _month_bounds(day: dt.date) -> tuple[dt.date, dt.date]:
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _previous_month_same_span(day: dt.date) -> tuple[dt.date, dt.date]:
    """Cùng kỳ tháng trước: ngày 1 → cùng ngày (cắt theo số ngày của tháng trước)."""
    prev_last = day.replace(day=1) - dt.timedelta(days=1)
    return prev_last.replace(day=1), prev_last.replace(day=min(day.day, prev_last.day))


def _rows_between(records: list, start: dt.date, end: dt.date) -> list[tuple[dt.date, int, str]]:
    rows = []
    for record in records:
        try:
            when = dt.date.fromisoformat(str(record.get("date")))
        except ValueError:
            continue
        if start <= when <= end:
            rows.append((when, int(record.get("total") or 0), str(record.get("category") or "không rõ")))
    return rows


def _by_category(rows: list) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for when, amount, category in rows:
        group = groups.setdefault(category, {"total": 0, "count": 0, "largest": 0, "largest_date": ""})
        group["total"] += amount
        group["count"] += 1
        if amount > group["largest"]:
            group["largest"], group["largest_date"] = amount, when.isoformat()
    return groups


def _kind(category: str) -> str:
    if category in FIXED_CATEGORIES:
        return "cố định"
    return "chưa rõ" if category in UNKNOWN_CATEGORIES else "linh hoạt"


def saving_ideas(categories: list[dict]) -> list[dict]:
    """Kịch bản tiết kiệm có số cụ thể, chỉ cho nhóm chi linh hoạt (code tính, AI chỉ diễn đạt lại)."""
    ideas = []
    for row in categories:
        if row["kind"] != "linh hoạt":
            continue
        rise = row["total"] - row["prev_same_span"]
        detail = (f"{row['category']}: tháng này {vnd(row['total'])} ({row['count']} lần, lần lớn nhất "
                  f"{vnd(row['largest'])} ngày {_day_month(row['largest_date'])}).")
        if row["prev_same_span"] and rise > 0:
            save = rise
            text = f"{detail} Nếu giữ ở mức cùng kỳ tháng trước ({vnd(row['prev_same_span'])}) thì để dành thêm được {vnd(save)}."
        elif row["count"] >= HABIT_MIN_COUNT:
            save = row["largest"]
            text = f"{detail} Bớt một lần chi cỡ lần lớn nhất là để dành được {vnd(save)}."
        else:
            continue
        ideas.append({"category": row["category"], "save": save, "text": text})
    ideas.sort(key=lambda idea: -idea["save"])
    return ideas[:3]


def spending_facts(records: list, today: str, settings: dict | None = None) -> dict:
    """Số liệu ngày / tháng + hạn mức + để dành + gợi ý + cảnh báo, tính hoàn toàn bằng code."""
    settings = {key: int((settings or {}).get(key) or 0) for key in ("monthly_budget", "monthly_income", "savings_goal")}
    day = dt.date.fromisoformat(today)
    month_start, month_end = _month_bounds(day)
    prev_start, prev_end = _previous_month_same_span(day)
    prev_full_start, prev_full_end = _month_bounds(prev_start)

    today_rows = _rows_between(records, day, day)
    month_rows = _rows_between(records, month_start, day)
    prev_groups = _by_category(_rows_between(records, prev_start, prev_end))
    month_groups = _by_category(month_rows)

    month_total = sum(amount for _, amount, _ in month_rows)
    days_elapsed = day.day
    days_in_month = month_end.day
    days_left = days_in_month - days_elapsed
    daily_average = month_total // days_elapsed
    forecast = month_total + daily_average * days_left

    by_day: dict[str, int] = {}
    for when, amount, _ in month_rows:
        by_day[when.isoformat()] = by_day.get(when.isoformat(), 0) + amount
    peak_date, peak_amount = max(by_day.items(), key=lambda item: item[1]) if by_day else ("", 0)

    categories = [
        {
            "category": name,
            "kind": _kind(name),
            "total": group["total"],
            "count": group["count"],
            "largest": group["largest"],
            "largest_date": group["largest_date"],
            "share_pct": round(group["total"] * 100 / month_total, 1) if month_total else 0,
            "prev_same_span": prev_groups.get(name, {}).get("total", 0),
        }
        for name, group in sorted(month_groups.items(), key=lambda item: -item[1]["total"])
    ]

    budget = settings["monthly_budget"]
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

    income, goal = settings["monthly_income"], settings["savings_goal"]
    savings = None
    if income:
        projected = income - forecast
        savings = {"income": income, "goal": goal, "projected": projected, "gap": max(goal - projected, 0) if goal else 0}

    facts = {
        "today": day.isoformat(),
        "month": f"{day.month:02d}/{day.year}",
        "settings": settings,
        "today_total": sum(amount for _, amount, _ in today_rows),
        "today_count": len(today_rows),
        "today_categories": {name: group["total"] for name, group in _by_category(today_rows).items()},
        "month_total": month_total,
        "month_count": len(month_rows),
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
        "daily_average": daily_average,
        "forecast_month_end": forecast,
        "prev_same_span_total": sum(group["total"] for group in prev_groups.values()),
        "prev_month_total": sum(amount for _, amount, _ in _rows_between(records, prev_full_start, prev_full_end)),
        "peak_day": {"date": peak_date, "total": peak_amount},
        "categories": categories,
        "budget": budget_info,
        "savings": savings,
        "saving_ideas": saving_ideas(categories),
    }
    facts["alerts"] = spending_alerts(facts)
    return facts


def spending_alerts(facts: dict) -> list[dict]:
    """Cảnh báo theo ngưỡng cố định (không dùng AI). level: danger · warn · info."""
    alerts = []
    budget, savings = facts["budget"], facts["savings"]
    month, month_total = facts["month"], facts["month_total"]
    pace = f"Giữ nhịp {vnd(facts['daily_average'])}/ngày, cuối tháng chi khoảng {vnd(facts['forecast_month_end'])}"
    if budget:
        if month_total >= budget["limit"]:
            alerts.append({
                "level": "danger",
                "title": "Đã vượt hạn mức tháng",
                "text": f"Tháng {month} đã chi {vnd(month_total)}, vượt {vnd(-budget['remaining'])} "
                        f"so với hạn mức {vnd(budget['limit'])}.",
            })
        elif month_total >= budget["limit"] * WARN_RATIO:
            alerts.append({
                "level": "warn",
                "title": "Sắp chạm hạn mức",
                "text": f"Đã dùng {pct(budget['used_pct'])} hạn mức ({vnd(month_total)} / {vnd(budget['limit'])}). "
                        f"Còn {vnd(budget['remaining'])} cho {facts['days_in_month'] - facts['days_elapsed']} ngày.",
            })
    if savings and savings["projected"] < 0:
        alerts.append({
            "level": "danger",
            "title": "Dự kiến chi vượt thu nhập",
            "text": f"{pace}, vượt thu nhập tháng {vnd(-savings['projected'])}.",
        })
    elif savings and savings["gap"]:
        alerts.append({
            "level": "warn",
            "title": "Dự kiến chưa đạt mục tiêu để dành",
            "text": f"{pace}, chỉ để dành được {vnd(savings['projected'])}, thiếu {vnd(savings['gap'])} "
                    f"so với mục tiêu {vnd(savings['goal'])}.",
        })
    elif budget and budget["forecast_over"] > 0 and month_total < budget["limit"]:
        alerts.append({
            "level": "warn",
            "title": "Dự báo vượt hạn mức",
            "text": f"{pace}, vượt {vnd(budget['forecast_over'])}.",
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
    "Bạn là trợ lý chi tiêu cá nhân. Chỉ dựa trên bảng số liệu JSON (số tiền VND đã tính sẵn), viết 3–4 dòng tiếng Việt, "
    "mỗi dòng bắt đầu bằng '- ' và dưới 35 từ:\n"
    "1) nhận xét chi tiêu hôm nay; 2) nhận xét cả tháng (so với cùng kỳ tháng trước, hạn mức và mục tiêu để dành nếu có);\n"
    "3–4) gợi ý tiết kiệm: chọn trong 'kich_ban_tiet_kiem', nói rõ nên làm gì và để dành được bao nhiêu.\n"
    "Quy tắc: chỉ dùng con số có trong bảng, chép đúng dạng như '1.234.000 ₫', không tự tính số mới, không làm tròn. "
    "Không khuyên cắt giảm các nhóm trong 'nhom_khong_cat' (tiền nhà, điện nước, sức khỏe). "
    "Không nhắc tới đầu tư, chứng khoán, vàng, tiền số, gửi tiết kiệm ngân hàng, vay hay thẻ tín dụng. "
    "Giọng nhẹ nhàng, gợi ý chứ không phán xét."
)


def _model_table(facts: dict) -> dict:
    """Bảng số gửi model: chỉ số tổng, đã định dạng sẵn để model chép nguyên văn. Không gửi thu nhập."""
    budget, savings = facts["budget"], facts["savings"]
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
            {"nhom": row["category"], "loai": row["kind"], "thang_nay": vnd(row["total"]), "so_lan": row["count"],
             "ty_trong": pct(row["share_pct"]), "cung_ky_thang_truoc": vnd(row["prev_same_span"])}
            for row in facts["categories"]
        ],
        "nhom_khong_cat": [row["category"] for row in facts["categories"] if row["kind"] == "cố định"],
        "kich_ban_tiet_kiem": [idea["text"] for idea in facts["saving_ideas"]],
        "han_muc": None if not budget else {
            "han_muc_thang": vnd(budget["limit"]), "da_dung": pct(budget["used_pct"]),
            "con_lai": vnd(budget["remaining"]), "nen_chi_moi_ngay": vnd(budget["safe_per_day"]),
        },
        "de_danh": None if not savings else {
            "muc_tieu_thang": vnd(savings["goal"]), "du_kien_de_danh_duoc": vnd(savings["projected"]),
            "con_thieu": vnd(savings["gap"]),
        },
        "canh_bao": [alert["text"] for alert in facts["alerts"]],
    }


def _number_tokens(text: str) -> set[str]:
    """Các con số trong chữ, bỏ dấu phân cách để so: '1.234.000 ₫' → '1234000', '12,5%' → '125'."""
    return {re.sub(r"[.,]", "", token) for token in re.findall(r"\d[\d.,]*\d|\d", text)}


def _cuts_fixed_category(line: str) -> bool:
    """Dòng khuyên cắt / kiểm soát một nhóm cố định (vd 'kiểm soát “Hóa đơn & Nhà ở”')."""
    for name in FIXED_CATEGORIES:
        escaped = re.escape(name)
        if re.search(CUT_VERBS + r"[^.;!?]{0,30}?" + escaped, line, re.IGNORECASE) or re.search(
            escaped + r"[^.;!?]{0,12}?" + CUT_VERBS, line, re.IGNORECASE
        ):
            return True
    return False


def grounded_lines(text: str, table: dict) -> list[str]:
    """Giữ dòng mà mọi con số đều có trong bảng, không khuyên cắt nhóm cố định, không nói về đầu tư / vay."""
    allowed = _number_tokens(json.dumps(table, ensure_ascii=False))
    lines = []
    for raw in unicodedata.normalize("NFC", text).splitlines():
        line = raw.strip().lstrip("-•* ").strip()
        if (
            line
            and _number_tokens(line) <= allowed
            and not FINANCE_ADVICE_PATTERN.search(line)
            and not _cuts_fixed_category(line)
        ):
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


def load_settings(user_id: str = "default_user") -> dict:
    raw = storage.LoadUserSettings(user_id)
    return {key: int(raw.get(key) or 0) for key in ("monthly_budget", "monthly_income", "savings_goal")}


def _check_amount(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} phải là số nguyên VND không âm.")
    return value


def save_budget(amount, user_id: str = "default_user") -> dict:
    """Đặt hạn mức tay (0 = tắt). Hạn mức tay thay cho hạn mức tính từ mục tiêu để dành."""
    _check_amount(amount, "Hạn mức (0 = tắt hạn mức)")
    return storage.SaveUserSettings(user_id, {"monthly_budget": amount, "savings_goal": 0})


def save_savings(monthly_income, savings_goal, user_id: str = "default_user") -> dict:
    """Thu nhập + mục tiêu để dành → hạn mức = thu nhập − mục tiêu (thu nhập 0 = tắt phần để dành)."""
    _check_amount(monthly_income, "Thu nhập tháng")
    _check_amount(savings_goal, "Mục tiêu để dành")
    if savings_goal > monthly_income:
        raise ValueError("Mục tiêu để dành không được lớn hơn thu nhập tháng.")
    changes = {"monthly_income": monthly_income, "savings_goal": savings_goal}
    if monthly_income:
        changes["monthly_budget"] = monthly_income - savings_goal
    return storage.SaveUserSettings(user_id, changes)
