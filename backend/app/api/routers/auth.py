"""Login, current user, and user management (ADMIN)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AuditLog, User
from app.security import (ROLES, Actor, ActorDep, create_token, hash_password, permissions_for, require,
                          validate_password_strength, verify_password)

router = APIRouter(prefix="/api/v1", tags=["auth"])
SessionDep = Annotated[Session, Depends(get_session)]
RoleLit = Literal["FRAUD_ANALYST", "AML_ANALYST", "COMPLIANCE_OFFICER", "INVESTIGATION_MANAGER",
                  "OPERATIONS_MANAGER", "ADMIN"]


def _user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at, "last_login_at": u.last_login_at}


@router.post("/auth/login", summary="Exchange username + password for a bearer token")
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep):
    user = session.scalar(select(User).where(User.username == form.username))
    ok = user is not None and user.is_active and verify_password(form.password, user.password_hash)
    session.add(AuditLog(actor=form.username[:80], action="LOGIN_SUCCEEDED" if ok else "LOGIN_FAILED",
                         entity_type="user", entity_id=form.username[:60], details={}))
    if not ok:
        session.commit()
        raise HTTPException(401, "Invalid username or password")
    user.last_login_at = datetime.now()
    session.commit()
    return {"access_token": create_token(user.username, user.role), "token_type": "bearer",
            "user": _user_out(user), "permissions": permissions_for(user.role)}


@router.get("/auth/me", summary="Current user and permissions")
def me(actor: ActorDep, session: SessionDep):
    user = session.scalar(select(User).where(User.username == actor.username))
    return {"user": _user_out(user), "permissions": permissions_for(actor.role)}


class NewUser(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[a-zA-Z0-9._-]+$")
    full_name: str = Field(min_length=1, max_length=120)
    role: RoleLit
    password: str = Field(min_length=10, max_length=200)


class UserUpdate(BaseModel):
    role: RoleLit | None = None
    is_active: bool | None = None
    full_name: str | None = Field(None, max_length=120)


@router.get("/users", summary="List users (ADMIN)")
def list_users(session: SessionDep, actor: Annotated[Actor, Depends(require("manage_users"))]):
    return {"roles": ROLES, "items": [_user_out(u) for u in session.scalars(select(User).order_by(User.username))]}


@router.post("/users", status_code=201, summary="Create a user (ADMIN)")
def create_user(body: NewUser, session: SessionDep, actor: Annotated[Actor, Depends(require("manage_users"))]):
    if session.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "Username already exists")
    try:
        validate_password_strength(body.password)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    u = User(username=body.username, full_name=body.full_name, role=body.role, password_hash=hash_password(body.password))
    session.add(u)
    session.add(AuditLog(actor=actor.username, action="USER_CREATED", entity_type="user", entity_id=body.username,
                         details={"role": body.role}))
    session.commit()
    return _user_out(u)


@router.patch("/users/{username}", summary="Change role / activate / deactivate (ADMIN)")
def update_user(username: str, body: UserUpdate, session: SessionDep,
                actor: Annotated[Actor, Depends(require("manage_users"))]):
    u = session.scalar(select(User).where(User.username == username))
    if not u:
        raise HTTPException(404, "User not found")
    if username == actor.username and (body.is_active is False or (body.role and body.role != "ADMIN")):
        raise HTTPException(422, "Admins cannot deactivate or demote themselves")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(u, k, v)
    session.add(AuditLog(actor=actor.username, action="USER_UPDATED", entity_type="user", entity_id=username,
                         details=changes))
    session.commit()
    return _user_out(u)
