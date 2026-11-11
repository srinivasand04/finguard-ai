import pandas as pd
import pytest

from ml.features import FEATURES, build_features, describe_factor

ACCOUNTS = pd.DataFrame({
    "account_id": ["A", "B", "C", "D"],
    "country": ["DE", "DE", "PA", "DE"],
    "opened_date": ["2025-01-01"] * 4,
    "segment": ["RETAIL", "SME", "RETAIL", "CORPORATE"],
})


def frame(rows):
    df = pd.DataFrame(rows, columns=["transaction_id", "sender_account_id", "receiver_account_id", "amount", "timestamp", "tx_type"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["is_cross_border"] = False
    return df


def test_all_features_present_and_finite():
    f = build_features(frame([(1, "A", "B", 50, "2026-01-01 10:00", "PAYMENT")]), ACCOUNTS, ["PA"])
    assert list(f.columns) == ["transaction_id"] + FEATURES
    assert f[FEATURES].notna().all().all()


def test_velocity_counts_only_strictly_prior_events():
    f = build_features(frame([
        (1, "A", "B", 10, "2026-01-01 10:00", "PAYMENT"),
        (2, "A", "B", 20, "2026-01-01 12:00", "PAYMENT"),
        (3, "A", "C", 30, "2026-01-05 12:00", "TRANSFER"),
        (4, "A", "B", 40, "2026-01-20 12:00", "PAYMENT"),
    ]), ACCOUNTS, ["PA"]).set_index("transaction_id")
    assert f.loc[1, "sender_tx_count_24h"] == 0          # no history yet
    assert f.loc[2, "sender_tx_count_24h"] == 1          # tx 1 is 2h earlier
    assert f.loc[3, "sender_tx_count_24h"] == 0 and f.loc[3, "sender_tx_count_7d"] == 2
    assert f.loc[4, "sender_tx_count_7d"] == 0 and f.loc[4, "sender_prior_tx_count"] == 3
    assert f.loc[3, "amount_vs_sender_mean"] == pytest.approx(30 / 15)


def test_new_counterparty_and_country_risk():
    f = build_features(frame([
        (1, "A", "B", 10, "2026-01-01 10:00", "PAYMENT"),
        (2, "A", "B", 10, "2026-01-02 10:00", "PAYMENT"),
        (3, "A", "C", 10, "2026-01-03 10:00", "TRANSFER"),
    ]), ACCOUNTS, ["PA"]).set_index("transaction_id")
    assert f["is_new_counterparty"].tolist() == [1, 0, 1]
    assert f.loc[3, "sender_new_counterparties_7d"] == 1  # only tx 1 created a new pair before tx 3
    assert f.loc[3, "receiver_high_risk_country"] == 1


def test_fan_in_and_pass_through():
    f = build_features(frame([
        (1, "B", "A", 5000, "2026-01-01 10:00", "TRANSFER"),
        (2, "D", "A", 5000, "2026-01-01 11:00", "TRANSFER"),
        (3, "A", "C", 9500, "2026-01-01 12:00", "TRANSFER"),
    ]), ACCOUNTS, ["PA"]).set_index("transaction_id")
    assert f.loc[2, "receiver_in_count_7d"] == 1
    assert f.loc[3, "pass_through_ratio"] == pytest.approx(0.95)
    assert f.loc[3, "near_threshold"] == 1 and f.loc[3, "is_round_amount"] == 1


def test_describe_factor_readable():
    assert describe_factor("sender_segment", 1) == "Sender customer segment: sme"
    assert describe_factor("is_night", 1).endswith("yes")
    assert "2.50x" in describe_factor("pass_through_ratio", 2.5)
