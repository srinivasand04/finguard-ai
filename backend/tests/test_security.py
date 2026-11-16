"""Phase 4: authentication, role-based access, PII masking, user management, metrics."""
from conftest import TEST_PASSWORD, TEST_USERS

from app.security import hash_password, permissions_for, verify_password


def test_password_hashing():
    h = hash_password("Correct-Horse-9")
    assert h.startswith("pbkdf2_sha256$") and verify_password("Correct-Horse-9", h)
    assert not verify_password("wrong", h) and not verify_password("x", "garbage")
    assert hash_password("Correct-Horse-9") != h            # salted


def test_login_and_me(client):
    r = client.post("/api/v1/auth/login", data={"username": TEST_USERS["FRAUD_ANALYST"], "password": "nope"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login", data={"username": TEST_USERS["FRAUD_ANALYST"], "password": TEST_PASSWORD})
    assert r.status_code == 200 and "run_investigation" in r.json()["permissions"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["user"]["role"] == "FRAUD_ANALYST"


def test_unauthenticated_and_bad_tokens(client):
    from fastapi.testclient import TestClient

    from app.main import app

    anon = TestClient(app)
    assert anon.get("/health").status_code == 200                       # public for load balancers
    assert anon.get("/api/v1/customers").status_code == 401
    assert anon.get("/api/v1/dashboard/summary").status_code == 401
    assert anon.get("/api/v1/customers", headers={"Authorization": "Bearer not.a.token"}).status_code == 401


def test_role_based_access(client, as_role):
    ops, analyst, admin = as_role("OPERATIONS_MANAGER"), as_role("FRAUD_ANALYST"), as_role("ADMIN")
    assert client.get("/api/v1/dashboard/summary", headers=ops).status_code == 200
    assert client.get("/api/v1/customers", headers=ops).status_code == 403          # no customer-level data
    assert client.get("/api/v1/audit-logs", headers=analyst).status_code == 403     # audit is for oversight roles
    assert client.get("/api/v1/users", headers=analyst).status_code == 403
    assert client.post("/api/v1/investigations", headers=admin,                     # admins administer, not investigate
                       json={"request_text": "Investigate CUST10001"}).status_code == 403
    assert "decide_investigation" in permissions_for("INVESTIGATION_MANAGER")
    assert "decide_investigation" not in permissions_for("FRAUD_ANALYST")


def test_pii_masking(client, as_role):
    cid = client.get("/api/v1/customers", params={"segment": "RETAIL", "size": 1}).json()["items"][0]["customer_id"]
    full = client.get(f"/api/v1/customers/{cid}", headers=as_role("COMPLIANCE_OFFICER")).json()["date_of_birth"]
    masked = client.get(f"/api/v1/customers/{cid}", headers=as_role("ADMIN")).json()["date_of_birth"]
    assert full and "*" not in full
    assert masked.endswith("-**-**") and masked[:4] == full[:4]
    views = client.get("/api/v1/audit-logs", params={"action": "CUSTOMER_PROFILE_VIEWED"}).json()["items"]
    assert any(v["entity_id"] == cid and v["actor"] == TEST_USERS["COMPLIANCE_OFFICER"] for v in views)


def test_user_management(client, as_role):
    admin = as_role("ADMIN")
    r = client.post("/api/v1/users", headers=admin, json={"username": "new.analyst", "full_name": "New",
                                                          "role": "AML_ANALYST", "password": "weakpassword1"})
    assert r.status_code == 422                                                     # no upper-case letter
    r = client.post("/api/v1/users", headers=admin, json={"username": "new.analyst", "full_name": "New",
                                                          "role": "AML_ANALYST", "password": "Strong-Pass-123"})
    assert r.status_code == 201
    assert client.post("/api/v1/auth/login", data={"username": "new.analyst", "password": "Strong-Pass-123"}).status_code == 200
    assert client.patch("/api/v1/users/new.analyst", headers=admin, json={"is_active": False}).status_code == 200
    assert client.post("/api/v1/auth/login", data={"username": "new.analyst", "password": "Strong-Pass-123"}).status_code == 401
    assert client.patch(f"/api/v1/users/{TEST_USERS['ADMIN']}", headers=admin, json={"is_active": False}).status_code == 422


def test_metrics_endpoint(client):
    body = client.get("/metrics").text
    assert "finguard_http_requests_total" in body and "finguard_tool_calls_total" in body
