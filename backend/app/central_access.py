from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import httpx
from sqlalchemy import select
from .config import settings
from .database import SessionLocal, User, UserPermission
from .security import ALL_PERMISSIONS, hash_password

def gateway_configured() -> bool:
    return bool((settings.access_gateway_url or "").strip())

def _base() -> str:
    return (settings.access_gateway_url or "").strip().rstrip("/")

def _timeout() -> float:
    return max(3.0, float(settings.access_gateway_timeout_seconds))

async def submit_access_request(payload: dict[str, str]) -> dict[str, Any]:
    if not gateway_configured():
        raise RuntimeError("Central ITICAS access service is not configured.")
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        r = await client.post(f"{_base()}/api/access/request", json=payload)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise RuntimeError(data.get("detail") or data.get("message") or "Access request could not be submitted.")
    return data

async def central_login(identifier: str, password: str) -> dict[str, Any] | None:
    if not gateway_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            r = await client.post(f"{_base()}/api/access/login", json={"identifier":identifier,"password":password})
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Central access service unavailable: {exc}") from exc
    if r.status_code == 401:
        return None
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise RuntimeError(data.get("detail") or "Central sign-in failed.")
    return data

def sync_central_user(profile: dict[str, Any], supplied_password: str) -> User:
    username = str(profile["username"]).strip()
    email = str(profile["email"]).strip().lower()
    role = str(profile.get("role") or "user").strip().lower()
    perms = {p for p in profile.get("permissions", []) if isinstance(p,str) and p in ALL_PERMISSIONS}
    with SessionLocal() as db:
        user = db.scalar(select(User).where((User.email.ilike(email)) | (User.username.ilike(username))))
        if user is None:
            user = User(username=username,email=email,password_hash=hash_password(supplied_password),
                        role=role,status="approved",is_primary_admin=1 if role=="admin" else 0,
                        approved_at=datetime.now(timezone.utc))
            db.add(user); db.flush()
        else:
            user.username=username; user.email=email; user.role=role; user.status="approved"
            if role=="admin": user.is_primary_admin=1
            user.approved_at = user.approved_at or datetime.now(timezone.utc)
        db.query(UserPermission).filter(UserPermission.user_id==user.id).delete()
        if role!="admin":
            for p in sorted(perms):
                db.add(UserPermission(user_id=user.id,permission=p,granted=1))
        db.commit(); db.refresh(user); db.expunge(user); return user
