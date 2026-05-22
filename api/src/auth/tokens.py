"""JWT de sesión."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from jose import JWTError, jwt

from src.settings import get_settings

_ALG = "HS256"
_TTL = timedelta(hours=12)


@dataclass(frozen=True)
class TokenPayload:
    sub: UUID
    email: str
    rol_global: str | None
    exp: datetime


def create_token(usuario_id: UUID, email: str, rol_global: str | None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(usuario_id),
        "email": email,
        "rol_global": rol_global,
        "iat": int(now.timestamp()),
        "exp": int((now + _TTL).timestamp()),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm=_ALG)


def decode_token(token: str) -> TokenPayload:
    settings = get_settings()
    try:
        data = jwt.decode(token, settings.auth_secret, algorithms=[_ALG])
    except JWTError as err:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido") from err
    return TokenPayload(
        sub=UUID(data["sub"]),
        email=data["email"],
        rol_global=data.get("rol_global"),
        exp=datetime.fromtimestamp(data["exp"], tz=UTC),
    )
