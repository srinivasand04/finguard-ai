import pandas as pd

from app.services.alerting import detect_structuring
from app.services.risk_scoring import score_profile

CFG = {"customer_risk": {"levels": {"HIGH": 60, "MEDIUM": 30}, "indicators": [
    {"code": "A", "label": "a", "metric": "x", "op": ">=", "threshold": 2, "weight": 40},
    {"code": "B", "label": "b", "metric": "ratio", "op": "between", "threshold": [0.9, 1.1], "weight": 30,
     "min_metric": {"total_in": 1000}},
    {"code": "C", "label": "c", "metric": "pep", "op": "==", "threshold": True, "weight": 50},
]}}


def test_no_indicators_is_low():
    score, level, ind = score_profile(pd.Series({"x": 0, "ratio": 5.0, "total_in": 0, "pep": False}), CFG)
    assert (score, level, ind) == (0, "LOW", [])


def test_indicators_are_explained_and_ordered():
    score, level, ind = score_profile(pd.Series({"x": 3, "ratio": 1.0, "total_in": 5000, "pep": False}), CFG)
    assert score == 70 and level == "HIGH"
    assert [i["code"] for i in ind] == ["A", "B"]
    assert ind[0]["value"] == 3 and ind[0]["threshold"] == 2


def test_min_metric_guard_and_cap():
    _, _, ind = score_profile(pd.Series({"x": 0, "ratio": 1.0, "total_in": 10, "pep": False}), CFG)
    assert ind == []  # pass-through ignored for tiny volumes
    score, _, _ = score_profile(pd.Series({"x": 5, "ratio": 1.0, "total_in": 5000, "pep": True}), CFG)
    assert score == 100  # 120 capped


def test_missing_metric_does_not_trigger():
    score, _, _ = score_profile(pd.Series({"x": float("nan"), "ratio": float("nan"), "total_in": 0, "pep": False}), CFG)
    assert score == 0


def test_structuring_rule_window():
    tx = pd.DataFrame({
        "transaction_id": [1, 2, 3, 4, 5],
        "sender_account_id": ["A"] * 3 + ["B"] * 2,
        "sender_customer_id": ["C1"] * 3 + ["C2"] * 2,
        "amount": [9500, 9800, 9100, 9900, 9900],
        "timestamp": pd.to_datetime(["2026-01-01", "2026-01-03", "2026-01-06", "2026-01-01", "2026-03-01"]),
    })
    hits = detect_structuring(tx, 9000, 10000, 3, 7)
    assert hits["account_id"].tolist() == ["A"]
    assert hits.iloc[0]["count"] == 3 and hits.iloc[0]["tx_ids"] == [1, 2, 3]
