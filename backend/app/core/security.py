import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import AppError

password_hasher = PasswordHasher()


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: str) -> tuple[str, int]:
    settings = get_settings(); expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    token = jwt.encode({"sub": user_id, "type": "access", "iat": datetime.now(timezone.utc), "exp": expires}, settings.secret_key, algorithm="HS256")
    return token, settings.access_token_expire_minutes * 60


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        if payload.get("type") != "access" or not payload.get("sub"): raise AppError("Authentication is required.", "AUTH_REQUIRED", 401)
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise AppError("The access token has expired.", "AUTH_TOKEN_EXPIRED", 401) from exc
    except (jwt.InvalidTokenError, AppError) as exc:
        if isinstance(exc, AppError): raise
        raise AppError("Authentication is required.", "AUTH_REQUIRED", 401) from exc


def new_refresh_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    return token, hashlib.sha256(token.encode()).hexdigest()


def new_one_time_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    return token, hash_one_time_token(token)


def hash_one_time_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
