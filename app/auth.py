import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db

security_bearer = HTTPBearer(auto_error=False)
limiter = Limiter(key_func=get_remote_address)


def hash_password(plain_password: str) -> str:
    """Computes SHA-256 hex digest for a plain-text password."""
    return hashlib.sha256(plain_password.encode("utf-8")).hexdigest()


def hash_password_secure(plain_password: str) -> str:
    """
    Computes cryptographically secure PBKDF2-HMAC-SHA256 password hash
    with 100,000 iterations and a cryptographically random 16-byte salt.
    Format: pbkdf2:sha256:100000$<salt_hex>$<hash_hex>
    """
    salt = os.urandom(16)
    iterations = 100_000
    derived = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
    return f"pbkdf2:sha256:{iterations}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """
    Verifies a plain-text password against the stored password hash.
    Supports:
    1. PBKDF2-HMAC-SHA256 (salted, 100k iterations)
    2. Standard SHA-256 hex digest
    3. Plain text match (if admin configured plain text password in env)
    4. Bcrypt hash match if formatted as bcrypt
    """
    if not hashed_password:
        return False

    clean_plain = plain_password.strip()
    clean_hash = hashed_password.strip()

    # 1. PBKDF2-HMAC-SHA256 match
    if clean_hash.startswith("pbkdf2:sha256:"):
        parts = clean_hash.split("$")
        if len(parts) == 3:
            prefix, salt_hex, expected_hex = parts
            try:
                iterations = int(prefix.split(":")[2])
                salt = bytes.fromhex(salt_hex)
                computed = hashlib.pbkdf2_hmac("sha256", clean_plain.encode("utf-8"), salt, iterations)
                return hmac.compare_digest(computed.hex().lower(), expected_hex.lower())
            except Exception:
                pass

    # 2. SHA-256 hex digest match
    plain_hash = hashlib.sha256(clean_plain.encode("utf-8")).hexdigest()
    if hmac.compare_digest(plain_hash.lower(), clean_hash.lower()):
        return True

    # 3. Plain text match (if admin configured plain text password in env)
    if hmac.compare_digest(clean_plain, clean_hash):
        return True

    # 4. Bcrypt hash match if formatted as bcrypt
    if clean_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            import bcrypt
            return bcrypt.checkpw(clean_plain.encode("utf-8"), clean_hash.encode("utf-8"))
        except Exception:
            pass

    return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Encodes a signed JWT with expiration."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Decodes and validates a JWT signature and expiration."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except Exception:
        return None


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer)
) -> dict:
    """FastAPI dependency requiring a valid Bearer JWT."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_current_user_id(
    payload: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> Optional[int]:
    """
    Resolves the authenticated user's ID from the JWT payload.
    If the JWT was issued without user_id, falls back to querying the database by username ('sub').
    Returns None if no matching user record exists.
    """
    user_id = payload.get("user_id")
    if user_id is not None:
        try:
            return int(user_id)
        except (ValueError, TypeError):
            pass

    sub = payload.get("sub")
    if sub:
        from app.models.user import User
        res = await db.execute(select(User.id).where(User.username == sub))
        db_id = res.scalar_one_or_none()
        if db_id is not None:
            return db_id

    return None


async def get_current_user(
    payload: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the User model instance for the currently authenticated user.
    """
    sub = payload.get("sub")
    if not sub:
        return None
    from app.models.user import User
    res = await db.execute(select(User).where(User.username == sub))
    return res.scalar_one_or_none()


async def require_admin(payload: dict = Depends(require_auth)) -> dict:
    """FastAPI dependency requiring an authenticated admin user."""
    configured_user = getattr(settings, "ADMIN_USERNAME", "admin")
    is_admin = (payload.get("sub") == configured_user) or bool(payload.get("is_superuser"))
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return payload
