from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies.auth import get_current_user_raw
from app.config import get_security_settings
from app.errors import AuthenticationError, AuthorizationError
from app.models.user_model import public_user
from app.schemas.auth_schema import ChangePasswordRequestModel, LoginRequestModel
from app.services.auth_service import change_password, login, logout, refresh


router = APIRouter(prefix="/auth", tags=["Authentication"])


def _validate_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in get_security_settings().allowed_origins:
        raise AuthorizationError("ORIGIN_NOT_ALLOWED", "The request origin is not allowed.")


def _set_cookie(response: Response, token: str) -> None:
    settings = get_security_settings()
    response.set_cookie(settings.refresh_cookie_name, token, max_age=settings.refresh_token_days * 86400,
                        httponly=True, secure=settings.refresh_cookie_secure, samesite=settings.refresh_cookie_samesite,
                        domain=settings.refresh_cookie_domain, path="/auth")


def _clear_cookie(response: Response) -> None:
    settings = get_security_settings()
    response.delete_cookie(settings.refresh_cookie_name, domain=settings.refresh_cookie_domain, path="/auth",
                           secure=settings.refresh_cookie_secure, httponly=True, samesite=settings.refresh_cookie_samesite)


@router.post("/login")
async def login_route(payload: LoginRequestModel, request: Request, response: Response):
    _validate_origin(request)
    data, refresh_token = login(payload.emailId, payload.password, getattr(request.state, "request_id", None))
    _set_cookie(response, refresh_token)
    return {"data": data}


@router.post("/refresh")
async def refresh_route(request: Request, response: Response):
    _validate_origin(request)
    settings = get_security_settings()
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        raise AuthenticationError("REFRESH_REQUIRED", "The session is invalid or has expired.")
    data, new_token = refresh(token, getattr(request.state, "request_id", None))
    _set_cookie(response, new_token)
    return {"data": data}


@router.post("/logout")
async def logout_route(request: Request, response: Response):
    _validate_origin(request)
    settings = get_security_settings()
    logout(request.cookies.get(settings.refresh_cookie_name), getattr(request.state, "request_id", None))
    _clear_cookie(response)
    return {"data": {"loggedOut": True}}


@router.get("/me")
async def me_route(user=Depends(get_current_user_raw)):
    return {"data": {"user": public_user(user)}}


@router.post("/change-password")
async def change_password_route(payload: ChangePasswordRequestModel, request: Request, response: Response,
                                user=Depends(get_current_user_raw)):
    _validate_origin(request)
    change_password(user, payload.currentPassword, payload.newPassword, getattr(request.state, "request_id", None))
    _clear_cookie(response)
    return {"data": {"passwordChanged": True, "reauthenticationRequired": True}}
