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
    """One demo account per role. The shared password comes from DEMO_USER_PASSWORD (.env) and is never printed."""
    password = get_settings().demo_user_password
    if not password:
        return {"skipped": "set DEMO_USER_PASSWORD in .env to create demo users"}
    validate_password_strength(password)
    created, existing = [], []
    with Session(engine) as s:
        for username, name, role in DEMO_USERS:
            if s.query(User).filter(User.username == username).one_or_none():
                existing.append(username)
                continue
            s.add(User(username=username, full_name=name, role=role, password_hash=hash_password(password)))
            created.append(username)
        if created:
            s.add(AuditLog(actor="system:cli", action="DEMO_USERS_SEEDED", entity_type="user", entity_id=None,
                           details={"created": created}))
        s.commit()
    return {"created": created, "already_existed": existing, "password": "DEMO_USER_PASSWORD from .env"}
