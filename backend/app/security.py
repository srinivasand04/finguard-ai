"""Authentication (JWT) and role-based access control.

Roles mirror the target users in the project brief. Permissions are granted to roles
in one table (PERMISSIONS) so the whole access model can be reviewed in one place.
Separation of duties: analysts run investigations and submit them; only an
Investigation Manager can decide on a case, and never on a case they submitted.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session

ROLES = ["FRAUD_ANALYST", "AML_ANALYST", "COMPLIANCE_OFFICER", "INVESTIGATION_MANAGER",
         "OPERATIONS_MANAGER", "ADMIN"]

ANALYSTS = {"FRAUD_ANALYST", "AML_ANALYST"}
INVESTIGATORS = ANALYSTS | {"COMPLIANCE_OFFICER", "INVESTIGATION_MANAGER"}
EVERYONE = set(ROLES)

PERMISSIONS: dict[str, set[str]] = {
    "view_monitoring":       EVERYONE,                                  # dashboard, alerts summary, models
    "view_customers":        INVESTIGATORS | {"ADMIN"},                # customer / transaction / graph detail
    "view_pii":              INVESTIGATORS,                            # unmasked date of birth etc.
    "score_transaction":     ANALYSTS | {"ADMIN"},
    "ask_compliance":        EVERYONE,
    "run_investigation":     ANALYSTS,
    "view_investigations":   INVESTIGATORS | {"ADMIN"},
    "submit_for_approval":   ANALYSTS,
    "decide_investigation":  {"INVESTIGATION_MANAGER"},
    "view_audit":            {"COMPLIANCE_OFFICER", "INVESTIGATION_MANAGER", "ADMIN"},
    "manage_users":          {"ADMIN"},
}


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


# ------------------------------------------------------------------ passwords (PBKDF2-SHA256, stdlib only)
_ITER = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER).hex()
    return f"pbkdf2_sha256${_ITER}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters)).hex()
    return hmac.compare_digest(check, digest)


def validate_password_strength(password: str) -> None:
    if len(password) < 10 or password.lower() == password or not any(c.isdigit() for c in password):
        raise ValueError("Password must be at least 10 characters with an upper-case letter and a digit")


# ------------------------------------------------------------------ tokens
@dataclass(frozen=True)
class Actor:
    """Who is acting: a logged-in user, the MCP service identity, or a system job."""
    username: str
    role: str

    def can(self, permission: str) -> bool:
        return self.role in PERMISSIONS.get(permission, set())


def create_token(username: str, role: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": username, "role": role, "iat": now, "exp": now + timedelta(minutes=s.jwt_expire_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def current_actor(token: Annotated[str | None, Depends(oauth2_scheme)],
                  session: Annotated[Session, Depends(get_session)]) -> Actor:
    from app.models import User

    unauth = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if not token:
        raise unauth
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise unauth from None
    user = session.query(User).filter(User.username == payload.get("sub")).one_or_none()
    if user is None or not user.is_active:         # deactivated users lose access immediately
        raise unauth
    return Actor(user.username, user.role)


def require(permission: str):
    """FastAPI dependency: the caller must hold `permission`."""
    def dep(actor: Annotated[Actor, Depends(current_actor)]) -> Actor:
        if not actor.can(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Role {actor.role} lacks permission '{permission}'")
        return actor
    return dep


ActorDep = Annotated[Actor, Depends(current_actor)]


def mask_date(value) -> str | None:
    """Show only the birth year to roles without view_pii."""
    return None if value is None else f"{str(value)[:4]}-**-**"
