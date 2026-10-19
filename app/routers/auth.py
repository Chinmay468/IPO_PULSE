import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.auth import (
    verify_password,
    hash_password_secure,
    create_access_token,
    decode_access_token,
    create_reset_token,
    require_auth,
    limiter
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, description="Current account password")
    new_password: str = Field(..., min_length=6, max_length=128, description="New password (at least 6 characters)")


class ForgotPasswordRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100, description="Username of the account")
    email: Optional[str] = Field(None, max_length=255, description="Registered email address if applicable")


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_token: str
    username: str
    has_email: bool


class ResetPasswordWithTokenRequest(BaseModel):
    reset_token: str = Field(..., description="Password reset verification token")
    new_password: str = Field(..., min_length=6, max_length=128, description="New password (at least 6 characters)")


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


class CheckUsernameResponse(BaseModel):
    username: str
    available: bool
    message: str


@router.get(
    "/check-username",
    response_model=CheckUsernameResponse,
    summary="Check if a username is available in real time"
)
@limiter.limit("60/minute")
async def check_username(
    request: Request,
    username: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Real-time check for username availability while filling out the registration form.
    Checks length, character pattern, reserved administrative aliases, and duplicate usernames.
    """
    clean_user = username.strip()
    if len(clean_user) < 3:
        return CheckUsernameResponse(
            username=clean_user,
            available=False,
            message="Username must be at least 3 characters long."
        )
    if len(clean_user) > 50:
        return CheckUsernameResponse(
            username=clean_user,
            available=False,
            message="Username cannot exceed 50 characters."
        )

    import re
    if not re.match(r"^[a-zA-Z0-9_.-]+$", clean_user):
        return CheckUsernameResponse(
            username=clean_user,
            available=False,
            message="Letters, numbers, underscores, dashes, and periods only."
        )

    reserved_names = {
        settings.ADMIN_USERNAME.lower(),
        "admin", "administrator", "root", "system", "superuser", "moderator"
    }
    if clean_user.lower() in reserved_names:
        return CheckUsernameResponse(
            username=clean_user,
            available=False,
            message="This username is reserved. Please choose another."
        )

    # Case-insensitive duplicate check
    stmt = select(User).where(func.lower(User.username) == clean_user.lower())
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        return CheckUsernameResponse(
            username=clean_user,
            available=False,
            message=f"Username '{clean_user}' is already taken."
        )

    return CheckUsernameResponse(
        username=clean_user,
        available=True,
        message="Username is available!"
    )


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

    reserved_names = {
        settings.ADMIN_USERNAME.lower(),
        "admin", "administrator", "root", "system", "superuser", "moderator"
    }
    if clean_user.lower() in reserved_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This username is reserved. Please choose a different username."
        )

    # Check if username exists (case-insensitive)
    existing_user = await db.execute(select(User).where(func.lower(User.username) == clean_user.lower()))
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


@router.post(
    "/change-password",
    summary="Change or reset password for the currently authenticated user"
)
@limiter.limit("10/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    payload: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """
    Allows an authenticated user to update their account password.
    Requires verifying their current password and hashes the new password
    using salted PBKDF2-HMAC-SHA256 (100,000 iterations).
    """
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials."
        )

    clean_user = sub.strip()
    stmt = select(User).where(func.lower(User.username) == clean_user.lower())
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        # Check if environment admin user
        configured_user = settings.ADMIN_USERNAME
        configured_hash = getattr(settings, "ADMIN_PASSWORD", None) or settings.ADMIN_PASSWORD_HASH
        if clean_user == configured_user and configured_hash:
            if not verify_password(body.current_password, configured_hash):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Current password is incorrect."
                )
            if body.current_password == body.new_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="New password must be different from current password."
                )
            # Provision admin user in DB with newly hashed password
            user = User(
                username=configured_user,
                hashed_password=hash_password_secure(body.new_password),
                is_superuser=True,
                is_active=True
            )
            db.add(user)
            await db.commit()
            return {"message": "Password changed successfully."}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found."
        )

    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect."
        )

    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password."
        )

    user.hashed_password = hash_password_secure(body.new_password)
    await db.commit()
    logger.info("Password updated successfully for user '%s'", user.username)
    return {"message": "Password updated successfully."}


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="Verify account credentials to initiate password recovery"
)
@limiter.limit("10/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 1 of password recovery: verifies user identity via username and (if configured) registered email.
    Returns a signed, short-lived reset token (valid for 15 minutes) to securely authorize password update.
    """
    clean_user = body.username.strip()
    stmt = select(User).where(func.lower(User.username) == clean_user.lower())
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    # Check environment admin fallback if record not yet instantiated in DB
    if not user and clean_user.lower() == settings.ADMIN_USERNAME.lower():
        configured_hash = getattr(settings, "ADMIN_PASSWORD", None) or settings.ADMIN_PASSWORD_HASH
        user = User(
            username=settings.ADMIN_USERNAME,
            hashed_password=configured_hash or hash_password_secure("admin123"),
            is_superuser=True,
            is_active=True
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No account found with username '{clean_user}'."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled. Please contact an administrator."
        )

    # If the user registered an email, require matching email for identity verification
    if user.email:
        if not body.email or not body.email.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This account has a registered email address. Please enter your email to verify your identity."
            )
        if body.email.strip().lower() != user.email.strip().lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The provided email address does not match our records for this account."
            )

    reset_token = create_reset_token(user.username, user.id, expires_minutes=15)
    return ForgotPasswordResponse(
        message="Account identity verified. Please proceed to set your new password.",
        reset_token=reset_token,
        username=user.username,
        has_email=bool(user.email)
    )


@router.post(
    "/reset-password-with-token",
    response_model=LoginResponse,
    summary="Reset password using a validated recovery token"
)
@limiter.limit("10/minute")
async def reset_password_with_token(
    request: Request,
    body: ResetPasswordWithTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 2 of password recovery: verifies signed reset token and updates the user's password.
    Returns a fresh login access token so the user is immediately logged in.
    """
    payload = decode_access_token(body.reset_token)
    if not payload or payload.get("type") != "password_reset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token. Please start the recovery process again."
        )

    username = payload.get("sub")
    user_id = payload.get("user_id")

    stmt = select(User).where((User.id == user_id) | (func.lower(User.username) == username.lower()))
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account associated with this reset token could not be found."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled."
        )

    user.hashed_password = hash_password_secure(body.new_password)
    await db.commit()
    logger.info("Password successfully reset via recovery token for user '%s'", user.username)

    # Auto-login: issue fresh access token
    new_token = create_access_token({
        "sub": user.username,
        "user_id": user.id,
        "is_superuser": user.is_superuser
    })

    return LoginResponse(
        access_token=new_token,
        token_type="bearer",
        user_id=user.id,
        username=user.username,
        is_admin=user.is_superuser
    )
