import pandas as pd
import pytest

from app.services import validation as v

ACCOUNTS = {"A1", "A2", "A3"}


def tx(**over):
    row = {"TX_ID": "1", "SENDER_ACCOUNT_ID": "A1", "RECEIVER_ACCOUNT_ID": "A2", "TX_TYPE": "TRANSFER",
           "TX_AMOUNT": "100.50", "TIMESTAMP": "2026-01-01T10:00:00", "IS_SAR": "False", "ALERT_ID": "-1"}
    row.update(over)
    return row


def run(rows):
    return v.validate_transactions(pd.DataFrame(rows, dtype=str), ACCOUNTS)


def test_clean_row_passes():
    r = run([tx()])
    assert len(r.clean) == 1 and r.rejected.empty
    assert r.clean["TX_AMOUNT"].iloc[0] == pytest.approx(100.5)


@pytest.mark.parametrize("override,reason", [
    ({"TX_AMOUNT": "-5"}, "non_positive_or_invalid_amount"),
    ({"TX_AMOUNT": "abc"}, "non_positive_or_invalid_amount"),
    ({"RECEIVER_ACCOUNT_ID": ""}, "missing_account_reference"),
    ({"SENDER_ACCOUNT_ID": "ZZZ"}, "unknown_account"),
    ({"RECEIVER_ACCOUNT_ID": "A1"}, "self_transfer"),
    ({"TIMESTAMP": "not-a-date"}, "invalid_timestamp"),
    ({"TX_TYPE": "TELEPORT"}, "unknown_tx_type"),
])
def test_rejections_have_reasons(override, reason):
    r = run([tx(TX_ID="1"), tx(TX_ID="2", **override)])
    assert len(r.clean) == 1
    assert r.rejected["REJECT_REASON"].tolist() == [reason]
    assert r.report["rejections_by_reason"] == {reason: 1}


def test_duplicates():
    r = run([tx(), tx(), tx(TX_AMOUNT="999")])  # exact duplicate, then conflicting re-use of TX_ID
    assert len(r.clean) == 1
    assert sorted(r.rejected["REJECT_REASON"]) == ["duplicate_row", "duplicate_tx_id"]


def test_messy_type_is_fixed_not_rejected():
    r = run([tx(TX_TYPE="  payment ")])
    assert r.clean["TX_TYPE"].iloc[0] == "PAYMENT"
    assert r.report["auto_fixes"]["normalised_tx_type"] == 1


def test_missing_column_raises():
    with pytest.raises(v.SchemaError):
        v.validate_transactions(pd.DataFrame([{"TX_ID": "1"}]), ACCOUNTS)


def test_accounts_reject_unknown_customer():
    df = pd.DataFrame([{"ACCOUNT_ID": "A1", "CUSTOMER_ID": "C1", "INIT_BALANCE": "1", "COUNTRY": "de", "ACCOUNT_TYPE": "checking"},
                       {"ACCOUNT_ID": "A2", "CUSTOMER_ID": "C9", "INIT_BALANCE": "1", "COUNTRY": "DE", "ACCOUNT_TYPE": "CHECKING"}])
    r = v.validate_accounts(df, {"C1"})
    assert r.clean["COUNTRY"].tolist() == ["DE"] and r.clean["ACCOUNT_TYPE"].tolist() == ["CHECKING"]
    assert r.rejected["REJECT_REASON"].tolist() == ["unknown_customer"]


def test_categorise():
    customers = pd.DataFrame({"CUSTOMER_ID": ["C1", "C2", "C3"], "SEGMENT": ["RETAIL", "SME", "CORPORATE"]})
    accounts = pd.DataFrame({"ACCOUNT_ID": ["A1", "A2", "A3"], "CUSTOMER_ID": ["C1", "C2", "C3"], "COUNTRY": ["DE", "DE", "NL"]})
    t = pd.DataFrame({"SENDER_ACCOUNT_ID": ["A1", "A3", "A2"], "RECEIVER_ACCOUNT_ID": ["A2", "A1", "A3"],
                      "TX_TYPE": ["PAYMENT", "TRANSFER", "WIRE"]})
    out = v.categorise(t, accounts, customers)
    assert out["CATEGORY"].tolist() == ["MERCHANT_PAYMENT", "SALARY_OR_PAYROLL", "BUSINESS_TRANSFER"]
    assert out["IS_CROSS_BORDER"].tolist() == [False, True, True]
    assert out["S_CUSTOMER_ID"].tolist() == ["C1", "C3", "C2"]
