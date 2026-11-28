"""Kiểm phần phân tích chi tiêu không cần mạng: số liệu, hạn mức, mục tiêu để dành, gợi ý tiết kiệm
và luật lọc câu AI (số lạ, khuyên cắt nhóm cố định, nói về đầu tư / vay).

Chạy: cd codebase && python check_insights.py
"""
import insights

RECORDS = [
    {"date": "2026-10-03", "total": 100_000, "category": "Ăn uống"},
    {"date": "2026-10-04", "total": 2_900_000, "category": "Hóa đơn & Nhà ở"},
    {"date": "2026-10-05", "total": 50_000, "category": "Giải trí"},
    {"date": "2026-11-02", "total": 400_000, "category": "Ăn uống"},
    {"date": "2026-11-03", "total": 3_000_000, "category": "Hóa đơn & Nhà ở"},
    {"date": "2026-11-05", "total": 300_000, "category": "Giải trí"},
    {"date": "2026-11-10", "total": 75_500, "category": "Ăn uống"},
    {"date": "2026-11-10", "total": 24_500, "category": "Di chuyển"},
]
TODAY = "2026-11-10"

facts = insights.spending_facts(RECORDS, TODAY, {"monthly_budget": 4_500_000})
assert facts["today_total"] == 100_000 and facts["today_count"] == 2
assert facts["month_total"] == 3_800_000 and facts["prev_same_span_total"] == 3_050_000
assert facts["daily_average"] == 380_000 and facts["forecast_month_end"] == 3_800_000 + 380_000 * 20
assert facts["budget"] == {"limit": 4_500_000, "used_pct": 84.4, "remaining": 700_000, "safe_per_day": 35_000,
                           "forecast_over": 6_900_000}
titles = [alert["title"] for alert in facts["alerts"]]
assert titles == ["Sắp chạm hạn mức", "Dự báo vượt hạn mức", "Ăn uống tăng so với tháng trước",
                  "Giải trí tăng so với tháng trước"], titles
print("[1] Số liệu tháng, hạn mức và cảnh báo: đúng")

over = insights.spending_facts(RECORDS, TODAY, {"monthly_budget": 3_500_000})
assert over["alerts"][0]["level"] == "danger" and "300.000 ₫" in over["alerts"][0]["text"]
assert not insights.spending_facts(RECORDS, TODAY)["budget"]
print("[2] Vượt hạn mức → danger; không đặt hạn mức → không cảnh báo hạn mức")

goal = insights.spending_facts(RECORDS, TODAY, {"monthly_income": 15_000_000, "savings_goal": 5_000_000,
                                                "monthly_budget": 10_000_000})
assert goal["savings"] == {"income": 15_000_000, "goal": 5_000_000, "projected": 3_600_000, "gap": 1_400_000}
assert "Dự kiến chưa đạt mục tiêu để dành" in [a["title"] for a in goal["alerts"]]
assert "Dự báo vượt hạn mức" not in [a["title"] for a in goal["alerts"]]  # không báo trùng cùng một khoản hụt
broke = insights.spending_facts(RECORDS, TODAY, {"monthly_income": 10_000_000})
assert broke["savings"]["projected"] == -1_400_000 and broke["alerts"][0]["title"] == "Dự kiến chi vượt thu nhập"
assert "thu_nhap" not in str(insights._model_table(goal)) and "15.000.000" not in str(insights._model_table(goal))
print("[3] Mục tiêu để dành: dự kiến 3.600.000 ₫, thiếu 1.400.000 ₫; chi vượt thu nhập → danger; không gửi thu nhập cho AI")

ideas = facts["saving_ideas"]
assert [idea["category"] for idea in ideas] == ["Ăn uống", "Giải trí"], ideas  # chỉ nhóm linh hoạt, không có Hóa đơn & Nhà ở
assert [idea["save"] for idea in ideas] == [375_500, 250_000]
assert "lần lớn nhất 400.000 ₫ ngày 02/11" in ideas[0]["text"] and "để dành thêm được 375.500 ₫" in ideas[0]["text"]
print("[4] Gợi ý tiết kiệm chỉ cho nhóm linh hoạt, số đúng từng đồng:", [idea["save"] for idea in ideas])

table = insights._model_table(facts)
text = (
    "- Hôm nay chi 100.000 ₫.\n"
    "- Nên cắt 123.456 ₫ tiền ăn.\n"  # số bịa → bỏ
    "- Ưu tiên kiểm soát “Hóa đơn & Nhà ở” (3.000.000 ₫).\n"  # khuyên cắt nhóm cố định → bỏ
    "- Hóa đơn & Nhà ở là khoản cố định, nên giảm Ăn uống: giữ 100.000 ₫ như tháng trước là để dành thêm 375.500 ₫.\n"
    "- Có thể đầu tư 100.000 ₫ vào chứng khoán.\n"  # đầu tư → bỏ
    "- Hãy vay thêm để chi tiêu."  # vay → bỏ
)
kept = insights.grounded_lines(text, table)
assert kept == ["Hôm nay chi 100.000 ₫.",
                "Hóa đơn & Nhà ở là khoản cố định, nên giảm Ăn uống: giữ 100.000 ₫ như tháng trước là để dành thêm 375.500 ₫."], kept
print("[5] Lọc câu AI: bỏ", len(text.splitlines()) - len(kept), "câu (số bịa, cắt nhóm cố định, đầu tư, vay)")

for call in (lambda: insights.save_budget(-1), lambda: insights.save_budget("9000000"), lambda: insights.save_budget(1.5),
             lambda: insights.save_savings(1_000_000, 2_000_000), lambda: insights.save_savings(-1, 0)):
    try:
        call()
    except ValueError:
        continue
    raise AssertionError("Cài đặt sai vẫn được lưu")
print("[6] Hạn mức / thu nhập / mục tiêu sai kiểu hoặc mục tiêu > thu nhập bị từ chối")
print("ĐẠT cả 6 ca")
