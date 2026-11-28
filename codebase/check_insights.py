"""Kiểm phần phân tích chi tiêu không cần mạng: số liệu, cảnh báo hạn mức và luật bỏ câu AI có số lạ.

Chạy: cd codebase && python check_insights.py
"""
import insights

RECORDS = [
    {"date": "2026-10-03", "total": 100_000, "category": "Ăn uống"},
    {"date": "2026-10-05", "total": 50_000, "category": "Giải trí"},
    {"date": "2026-11-02", "total": 400_000, "category": "Ăn uống"},
    {"date": "2026-11-05", "total": 300_000, "category": "Giải trí"},
    {"date": "2026-11-10", "total": 75_500, "category": "Ăn uống"},
    {"date": "2026-11-10", "total": 24_500, "category": "Di chuyển"},
]

facts = insights.spending_facts(RECORDS, "2026-11-10", monthly_budget=900_000)
assert facts["today_total"] == 100_000 and facts["today_count"] == 2
assert facts["month_total"] == 800_000 and facts["prev_same_span_total"] == 150_000
assert facts["daily_average"] == 80_000 and facts["forecast_month_end"] == 800_000 + 80_000 * 20
assert facts["budget"]["remaining"] == 100_000 and facts["budget"]["used_pct"] == 88.9
levels = [alert["level"] for alert in facts["alerts"]]
assert levels.count("warn") == 2, facts["alerts"]  # ≥80% hạn mức + dự báo vượt
assert any("Ăn uống" in alert["title"] for alert in facts["alerts"])  # 475.500 so với 100.000 cùng kỳ
print("[1] Số liệu và cảnh báo: đúng", levels)

over = insights.spending_facts(RECORDS, "2026-11-10", monthly_budget=700_000)
assert over["alerts"][0]["level"] == "danger" and "100.000 ₫" in over["alerts"][0]["text"]
assert not insights.spending_facts(RECORDS, "2026-11-10")["budget"]
print("[2] Vượt hạn mức → danger; không đặt hạn mức → không cảnh báo hạn mức")

table = insights._model_table(facts)
text = (
    "- Hôm nay chi 100.000 ₫.\n"
    "- Tháng này 800.000 ₫, đã dùng 88,9% hạn mức.\n"
    "- Nên cắt 123.456 ₫ tiền ăn.\n"  # số bịa → bỏ
    "- Ăn uống tăng mạnh, thử nấu ăn ở nhà vài bữa."
)
kept = insights.grounded_lines(text, table)
assert kept == ["Hôm nay chi 100.000 ₫.", "Tháng này 800.000 ₫, đã dùng 88,9% hạn mức.",
                "Ăn uống tăng mạnh, thử nấu ăn ở nhà vài bữa."], kept
print("[3] Câu AI có số không có trong bảng bị bỏ:", len(text.splitlines()) - len(kept), "câu")

for bad in (-1, "9000000", 1.5):
    try:
        insights.save_budget(bad)
    except ValueError:
        continue
    raise AssertionError(f"Hạn mức sai kiểu vẫn được lưu: {bad!r}")
print("[4] Hạn mức không phải số nguyên VND ≥ 0 bị từ chối")
print("ĐẠT cả 4 ca")
