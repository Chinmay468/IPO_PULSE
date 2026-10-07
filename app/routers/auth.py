from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from app.config import settings
from app.auth import verify_password, create_access_token, limiter

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str = Field(..., description="Admin username")
    password: str = Field(..., description="Admin password")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login to receive a JWT access token"
)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest):
    """
    Authenticate against the single-user admin credentials configured via environment variables.
    Rate limited to 5 requests per minute per IP.
    """
    configured_user = settings.ADMIN_USERNAME
    configured_hash = getattr(settings, "ADMIN_PASSWORD", None) or settings.ADMIN_PASSWORD_HASH

    if not configured_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication not configured on server"
        )

    if body.username != configured_user or not verify_password(body.password, configured_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    token = create_access_token({"sub": body.username})
    return LoginResponse(access_token=token, token_type="bearer")
