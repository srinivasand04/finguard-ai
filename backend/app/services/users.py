"""User provisioning for development / demos."""
from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog, User
from app.security import ROLES, hash_password, validate_password_strength

DEMO_USERS = [
    ("analyst.fraud", "Fraud Analyst (demo)", "FRAUD_ANALYST"),
    ("analyst.aml", "AML Analyst (demo)", "AML_ANALYST"),
    ("compliance.officer", "Compliance Officer (demo)", "COMPLIANCE_OFFICER"),
    ("manager.investigations", "Investigation Manager (demo)", "INVESTIGATION_MANAGER"),
    ("manager.operations", "Operations Manager (demo)", "OPERATIONS_MANAGER"),
    ("admin", "System Administrator (demo)", "ADMIN"),
]


# personal accounts: <OWNER_USERNAME_PREFIX>.<suffix>, one per role
OWNER_SUFFIX = {"FRAUD_ANALYST": "fraud", "AML_ANALYST": "aml", "COMPLIANCE_OFFICER": "compliance",
                "INVESTIGATION_MANAGER": "manager", "OPERATIONS_MANAGER": "operations", "ADMIN": "admin"}


def create_user(engine: Engine, username: str, role: str, password: str, full_name: str | None = None) -> dict:
    if role not in ROLES:
        raise SystemExit(f"Role must be one of {ROLES}")
    validate_password_strength(password)
    with Session(engine) as s:
        if s.query(User).filter(User.username == username).one_or_none():
            raise SystemExit(f"User {username} already exists")
        s.add(User(username=username, full_name=full_name or username, role=role, password_hash=hash_password(password)))
        s.add(AuditLog(actor="system:cli", action="USER_CREATED", entity_type="user", entity_id=username,
                       details={"role": role}))
        s.commit()
    return {"created": username, "role": role}


def seed_demo_users(engine: Engine) -> dict:
    """One demo account per role (password DEMO_USER_PASSWORD) plus, if OWNER_USERNAME_PREFIX and
    OWNER_PASSWORD are set in .env, one personal account per role (<prefix>.fraud, <prefix>.manager, ...).
    Passwords come from .env and are never printed."""
    st = get_settings()
    accounts: list[tuple[str, str, str, str]] = []
    if st.demo_user_password:
        validate_password_strength(st.demo_user_password)
        accounts += [(u, n, r, st.demo_user_password) for u, n, r in DEMO_USERS]
    if st.owner_username_prefix and st.owner_password:
        validate_password_strength(st.owner_password)
        accounts += [(f"{st.owner_username_prefix}.{suffix}", f"{st.owner_username_prefix} ({role.replace('_', ' ').title()})",
                      role, st.owner_password) for role, suffix in OWNER_SUFFIX.items()]
    if not accounts:
        return {"skipped": "set DEMO_USER_PASSWORD and/or OWNER_USERNAME_PREFIX + OWNER_PASSWORD in .env"}
    created, existing = [], []
    with Session(engine) as s:
        for username, name, role, password in accounts:
            if s.query(User).filter(User.username == username).one_or_none():
                existing.append(username)
                continue
            s.add(User(username=username, full_name=name, role=role, password_hash=hash_password(password)))
            created.append(username)
        if created:
            s.add(AuditLog(actor="system:cli", action="DEMO_USERS_SEEDED", entity_type="user", entity_id=None,
                           details={"created": created}))
        s.commit()
    return {"created": created, "already_existed": existing, "passwords": "from .env (DEMO_USER_PASSWORD / OWNER_PASSWORD)"}
