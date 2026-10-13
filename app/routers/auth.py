import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.auth import (
    verify_password,
    hash_password_secure,
    create_access_token,
    require_auth,
    limiter
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str = Field(..., description="Username")
    password: str = Field(..., description="Password")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: Optional[int] = None
    username: Optional[str] = None
    is_admin: bool = False


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$", description="Username (letters, numbers, underscores)")
    password: str = Field(..., min_length=6, max_length=128, description="Password (at least 6 characters)")
    email: Optional[str] = Field(None, max_length=255, description="Optional email address")
    full_name: Optional[str] = Field(None, max_length=255, description="Optional full name")


class RegisterResponse(BaseModel):
    message: str
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login to receive a JWT access token"
)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate against the database user accounts (salted PBKDF2 hash)
    or the single-user admin environment credentials.
    Rate limited to 15 requests per minute per IP.
    """
    clean_user = body.username.strip()

    # 1. Check database users table first
    stmt = select(User).where(User.username == clean_user)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if user:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account has been disabled."
            )
        if verify_password(body.password, user.hashed_password):
            token = create_access_token({
                "sub": user.username,
                "user_id": user.id,
                "is_superuser": user.is_superuser
            })
            return LoginResponse(
                access_token=token,
                token_type="bearer",
                user_id=user.id,
                username=user.username,
                is_admin=user.is_superuser
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )

    # 2. Fallback to configured environment admin credentials
    configured_user = settings.ADMIN_USERNAME
    configured_hash = getattr(settings, "ADMIN_PASSWORD", None) or settings.ADMIN_PASSWORD_HASH

    if clean_user == configured_user and configured_hash and verify_password(body.password, configured_hash):
        # Auto-provision or retrieve admin record in DB to enable relational scoping
        stmt_admin = select(User).where(User.username == configured_user)
        res_admin = await db.execute(stmt_admin)
        admin_rec = res_admin.scalar_one_or_none()
        if not admin_rec:
            admin_rec = User(
                username=configured_user,
                hashed_password=hash_password_secure(body.password),
                is_superuser=True,
                is_active=True
            )
            db.add(admin_rec)
            await db.commit()
            await db.refresh(admin_rec)

        token = create_access_token({
            "sub": configured_user,
            "user_id": admin_rec.id,
            "is_superuser": True
        })
        return LoginResponse(
            access_token=token,
            token_type="bearer",
            user_id=admin_rec.id,
            username=configured_user,
            is_admin=True
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password"
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account"
)
@limiter.limit("30/minute")
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Register a new user with encrypted password storage (PBKDF2-HMAC-SHA256, 100k iterations).
    Provides scoped portfolio and mutual fund data isolation.
    """
    clean_user = body.username.strip()

    if clean_user.lower() == settings.ADMIN_USERNAME.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This username is reserved. Please choose a different username."
        )

    # Check if username exists
    existing_user = await db.execute(select(User).where(User.username == clean_user))
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{clean_user}' is already registered. Please choose another or sign in."
        )

    # Check if email exists
    clean_email = body.email.strip().lower() if body.email else None
    if clean_email:
        existing_email = await db.execute(select(User).where(User.email == clean_email))
        if existing_email.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email address is already registered."
            )

    new_user = User(
        username=clean_user,
        email=clean_email,
        hashed_password=hash_password_secure(body.password),
        full_name=body.full_name.strip() if body.full_name else None,
        is_active=True,
        is_superuser=False
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    token = create_access_token({
        "sub": new_user.username,
        "user_id": new_user.id,
        "is_superuser": False
    })

    logger.info("Successfully registered new user '%s' (id=%d)", new_user.username, new_user.id)
    return RegisterResponse(
        message="User account registered successfully.",
        access_token=token,
        token_type="bearer",
        user_id=new_user.id,
        username=new_user.username
    )


@router.get(
    "/me",
    summary="Get current user details"
)
async def get_me(payload: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    """Returns details of the currently authenticated user."""
    sub = payload.get("sub")
    res = await db.execute(select(User).where(User.username == sub))
    user = res.scalar_one_or_none()
    if user:
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "is_superuser": user.is_superuser
        }
    return {
        "id": None,
        "username": sub,
        "email": None,
        "full_name": "Admin",
        "is_superuser": (sub == settings.ADMIN_USERNAME)
    }
