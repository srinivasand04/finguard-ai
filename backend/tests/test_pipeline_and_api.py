"""Integration tests: full pipeline on a small dataset + every API endpoint."""
from sqlalchemy import text


def test_ingestion_catches_injected_dirty_rows(pipeline):
    injected = pipeline["generation"]["dirty_rows_injected"]
    rej = pipeline["ingest"]["transactions"]["rejections_by_reason"]
    assert rej["duplicate_row"] == injected["duplicates"]
    assert rej["non_positive_or_invalid_amount"] == injected["negative_amount"]
    assert rej["invalid_timestamp"] == injected["bad_timestamp"]
    assert rej["self_transfer"] == injected["self_transfer"]
    assert rej["unknown_account"] == injected["unknown_account"]
    assert rej["missing_account_reference"] == injected["missing_receiver"]


def test_tables_populated_and_consistent(pipeline):
    with pipeline["engine"].connect() as c:
        n = {t: c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in
             ["customers", "accounts", "transactions", "fraud_predictions", "customer_risk", "alerts", "model_versions", "audit_logs"]}
        assert n["fraud_predictions"] == n["transactions"] > 0
        assert n["customer_risk"] == n["customers"]
        assert n["model_versions"] == 3 and n["alerts"] > 0 and n["audit_logs"] >= 5
        orphans = c.execute(text("SELECT COUNT(*) FROM transactions t LEFT JOIN accounts a "
                                 "ON a.account_id = t.sender_account_id WHERE a.account_id IS NULL")).scalar()
        assert orphans == 0


def test_model_beats_random(pipeline):
    m = pipeline["train"]["models"]["fraud_xgboost"]
    assert m["roc_auc"] > 0.8
    assert m["pr_auc"] > 5 * m["base_rate"]  # far better than the no-skill baseline


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["database"] is True


def test_dashboard(client):
    s = client.get("/api/v1/dashboard/summary").json()
    assert s["transactions"] > 0 and "disclaimer" in s and len(s["active_models"]) == 2
    ts = client.get("/api/v1/dashboard/timeseries").json()
    assert ts and {"date", "count", "volume", "high", "medium"} <= set(ts[0])
    dist = client.get("/api/v1/dashboard/risk-distribution").json()
    assert len(dist) == 10 and sum(d["customers"] for d in dist) == s["customers"]


def test_customer_endpoints(client):
    page = client.get("/api/v1/customers", params={"size": 5}).json()
    assert page["total"] > 0 and len(page["items"]) == 5
    scores = [c["risk_score"] for c in page["items"]]
    assert scores == sorted(scores, reverse=True)
    cid = page["items"][0]["customer_id"]
    d = client.get(f"/api/v1/customers/{cid}").json()
    assert d["accounts"] and d["risk"]["indicators"] is not None
    assert client.get(f"/api/v1/customers/{cid}/risk").status_code == 200
    tx = client.get(f"/api/v1/customers/{cid}/transactions", params={"size": 3}).json()
    assert all(cid in (t["sender_customer_id"], t["receiver_customer_id"]) for t in tx["items"])
    cps = client.get(f"/api/v1/customers/{cid}/counterparties").json()["counterparties"]
    assert all(c["customer_id"] != cid for c in cps)
    assert client.get("/api/v1/customers/NOPE").status_code == 404
    assert client.get("/api/v1/customers", params={"q": cid}).json()["total"] == 1


def test_transaction_filters_and_detail(client):
    hi = client.get("/api/v1/transactions", params={"risk_band": "HIGH", "sort": "risk_desc", "size": 5}).json()
    assert hi["total"] > 0 and all(t["risk_band"] == "HIGH" for t in hi["items"])
    amt = client.get("/api/v1/transactions", params={"min_amount": 1000, "max_amount": 2000, "size": 20}).json()
    assert all(1000 <= t["amount"] <= 2000 for t in amt["items"])
    tid = hi["items"][0]["transaction_id"]
    d = client.get(f"/api/v1/transactions/{tid}").json()
    assert d["prediction"]["risk_band"] == "HIGH" and d["prediction"]["top_factors"]
    assert client.get("/api/v1/transactions/999999999").status_code == 404
    assert client.get("/api/v1/transactions", params={"size": 500}).status_code == 422


def test_account_velocity(client):
    t = client.get("/api/v1/transactions", params={"size": 1}).json()["items"][0]
    v = client.get(f"/api/v1/accounts/{t['sender_account_id']}/velocity", params={"days": 90}).json()
    assert set(v["windows"]) == {"24h", "7d", "30d", "90d"} and v["daily"]
    assert client.get("/api/v1/accounts/NOPE/velocity").status_code == 404


def test_realtime_scoring(client):
    t = client.get("/api/v1/transactions", params={"size": 1, "sort": "timestamp_desc"}).json()["items"][0]
    body = {"sender_account_id": t["sender_account_id"], "receiver_account_id": t["receiver_account_id"],
            "amount": 9600, "tx_type": "TRANSFER", "timestamp": "2030-01-01T02:00:00"}
    r = client.post("/api/v1/transactions/score", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert 0 <= out["fraud_probability"] <= 1 and out["risk_band"] in {"LOW", "MEDIUM", "HIGH"}
    assert out["features"]["near_threshold"] == 1 and out["features"]["is_night"] == 1
    assert out["persisted"] is False
    assert client.post("/api/v1/transactions/score", json={**body, "receiver_account_id": "NOPE1"}).status_code == 404
    assert client.post("/api/v1/transactions/score", json={**body, "amount": -1}).status_code == 422
    assert client.post("/api/v1/transactions/score", json={**body, "receiver_account_id": body["sender_account_id"]}).status_code == 422
    logs = client.get("/api/v1/audit-logs", params={"action": "TRANSACTION_SCORED"}).json()
    assert logs["total"] >= 1


def test_alerts_and_models(client):
    a = client.get("/api/v1/alerts", params={"size": 10}).json()
    assert a["total"] > 0 and all(x["reasons"] for x in a["items"])
    assert client.get(f"/api/v1/alerts/{a['items'][0]['id']}").status_code == 200
    ms = client.get("/api/v1/models").json()
    assert {m["model_name"] for m in ms} == {"fraud_xgboost", "fraud_random_forest", "anomaly_isolation_forest"}
    assert client.get(f"/api/v1/models/{ms[0]['id']}").json()["metrics"]
