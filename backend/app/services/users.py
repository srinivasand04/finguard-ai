"""User provisioning for development / demos."""
from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog, User
from app.security import ROLES, hash_password, validate_password_strength

PUBLIC_DEMO_PASSWORD = "FinGuard-Demo-2026"   # the value shown in .env.example (public on GitHub)

# one demo account per role; the username says what the account can do
DEMO_USERS = [
    ("fraud_analyst", "Fraud Analyst", "FRAUD_ANALYST"),
    ("aml_analyst", "AML Analyst", "AML_ANALYST"),
    ("compliance_officer", "Compliance Officer", "COMPLIANCE_OFFICER"),
    ("investigation_manager", "Investigation Manager", "INVESTIGATION_MANAGER"),
    ("operations_manager", "Operations Manager", "OPERATIONS_MANAGER"),
    ("admin", "System Administrator", "ADMIN"),
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


def seed_demo_users(engine: Engine, reset_passwords: bool = False) -> dict:
    """Create one demo account per role with the password DEMO_USER_PASSWORD from .env (never printed).

    reset_passwords=True also sets that password on demo accounts that already exist and re-activates
    them - use it after changing DEMO_USER_PASSWORD.
    """
    password = get_settings().demo_user_password
    if not password:
        return {"skipped": "set DEMO_USER_PASSWORD in .env to create demo users"}
    validate_password_strength(password)
    if get_settings().environment == "production" and password == PUBLIC_DEMO_PASSWORD:
        raise SystemExit("DEMO_USER_PASSWORD is the public example value - choose a private one for production")
    created, updated, existing = [], [], []
    with Session(engine) as s:
        for username, name, role in DEMO_USERS:
            u = s.query(User).filter(User.username == username).one_or_none()
            if u is None:
                s.add(User(username=username, full_name=name, role=role, password_hash=hash_password(password)))
                created.append(username)
            elif reset_passwords:
                u.password_hash, u.is_active, u.role, u.full_name = hash_password(password), True, role, name
                updated.append(username)
            else:
                existing.append(username)
        if created or updated:
            s.add(AuditLog(actor="system:cli", action="DEMO_USERS_SEEDED", entity_type="user", entity_id=None,
                           details={"created": created, "password_reset": updated}))
        s.commit()
    return {"created": created, "password_reset": updated, "already_existed": existing,
            "password": "DEMO_USER_PASSWORD from .env"}
