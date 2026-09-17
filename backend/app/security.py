from __future__ import annotations
import hashlib, hmac, json, secrets, time
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from fastapi import Request, HTTPException
from sqlalchemy import select

from .config import settings
from .database import SessionLocal, User, UserPermission, AuthSession, AuditLog

ALL_PERMISSIONS = (
    "traffic:view",
    "traffic:acquire",
    "monitoring:view",
    "monitoring:run",
    "locations:view",
    "locations:manage",
    "analytics:view",
    "prediction:run",
    "reports:view",
    "reports:export",
    "validation:view",
    "admin:users",
    "admin:audit",
    "admin:security",
)

_LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)

def now_utc():
    return datetime.now(timezone.utc)

def _b64hex(data: bytes) -> str:
    return data.hex()

def hash_password(password: str) -> str:
    if len(password) < settings.security_password_min_length:
        raise ValueError(f"Password must contain at least {settings.security_password_min_length} characters.")
    salt = secrets.token_bytes(16)
    n, r, p = 2**14, 8, 1
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${derived.hex()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$", 5)
        if scheme != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest_hex))
        )
        return hmac.compare_digest(derived.hex(), digest_hex)
    except Exception:
        return False

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:80]
    return (request.client.host if request.client else "unknown")[:80]

def audit(action: str, request: Request | None = None, user_id: int | None = None,
          resource_type: str | None = None, resource_id: str | None = None,
          outcome: str = "success", details: dict | None = None):
    with SessionLocal() as db:
        db.add(AuditLog(
            user_id=user_id, action=action, resource_type=resource_type,
            resource_id=resource_id, outcome=outcome,
            client_ip=client_ip(request) if request else None,
            details_json=json.dumps(details or {}, ensure_ascii=False)
        ))
        db.commit()

def create_session(user: User, request: Request) -> str:
    raw = secrets.token_urlsafe(48)
    expires = now_utc() + timedelta(hours=max(1, settings.security_session_hours))
    with SessionLocal() as db:
        db.add(AuthSession(
            user_id=user.id, token_hash=token_hash(raw), expires_at=expires,
            client_ip=client_ip(request), user_agent=request.headers.get("user-agent", "")[:500]
        ))
        u = db.get(User, user.id)
        if u:
            u.last_login_at = now_utc()
            u.failed_login_count = 0
            u.locked_until = None
        db.commit()
    return raw

def revoke_session(raw: str | None):
    if not raw:
        return
    with SessionLocal() as db:
        row = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(raw)))
        if row and row.revoked_at is None:
            row.revoked_at = now_utc()
            db.commit()

def current_user_optional(request: Request) -> User | None:
    raw = request.cookies.get(settings.security_cookie_name)
    if not raw:
        return None
    with SessionLocal() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(raw)))
        if not session or session.revoked_at is not None:
            return None
        expires = session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= now_utc():
            return None
        user = db.get(User, session.user_id)
        if not user or user.status != "approved":
            return None
        db.expunge(user)
        return user

def require_user(request: Request) -> User:
    user = current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user

def permissions_for(user: User) -> set[str]:
    if user.role == "admin":
        return set(ALL_PERMISSIONS)
    with SessionLocal() as db:
        rows = db.scalars(
            select(UserPermission).where(UserPermission.user_id == user.id, UserPermission.granted == 1)
        ).all()
        return {x.permission for x in rows}

def require_permission(request: Request, permission: str) -> User:
    user = require_user(request)
    if permission not in permissions_for(user):
        raise HTTPException(status_code=403, detail=f"Permission required: {permission}")
    return user

def check_login_rate_limit(request: Request):
    ip = client_ip(request)
    now = time.time()
    q = _LOGIN_ATTEMPTS[ip]
    window = max(60, settings.security_login_window_seconds)
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= max(1, settings.security_login_max_attempts):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    q.append(now)

def clear_login_rate_limit(request: Request):
    _LOGIN_ATTEMPTS.pop(client_ip(request), None)

def authenticate(username_or_email: str, password: str) -> User | None:
    value = username_or_email.strip().lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(
            (User.username.ilike(value)) | (User.email.ilike(value))
        ))
        if not user:
            return None
        if user.status != "approved":
            return None
        if user.locked_until:
            locked = user.locked_until
            if locked.tzinfo is None:
                locked = locked.replace(tzinfo=timezone.utc)
            if locked > now_utc():
                return None
        if not verify_password(password, user.password_hash):
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= 5:
                user.locked_until = now_utc() + timedelta(minutes=15)
            db.commit()
            return None
        db.expunge(user)
        return user
