import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings

security_bearer = HTTPBearer(auto_error=False)


def hash_password(plain_password: str) -> str:
    """Computes SHA-256 hex digest for a plain-text password."""
    return hashlib.sha256(plain_password.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """
    Verifies a plain-text password against the stored password hash.
    Supports standard SHA-256 hex digest and bcrypt formats.
    """
    if not hashed_password:
        return False

    clean_plain = plain_password.strip()
    clean_hash = hashed_password.strip()

    # 1. SHA-256 hex digest match
    plain_hash = hashlib.sha256(clean_plain.encode("utf-8")).hexdigest()
    if hmac.compare_digest(plain_hash.lower(), clean_hash.lower()):
        return True

    # 2. Plain text match (if admin configured plain text password in env)
    if hmac.compare_digest(clean_plain, clean_hash):
        return True

    # 3. Bcrypt hash match if formatted as bcrypt
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
