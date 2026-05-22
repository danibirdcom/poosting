"""Contexto de request: usuario + tenant resuelto."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status

from src.auth.tokens import TokenPayload, decode_token
from src.db.pool import tenant_connection


@dataclass(frozen=True)
class RequestContext:
    usuario_id: UUID
    medio_id: UUID
    rol: str           # 'editor_jefe' | 'redactor' | 'colaborador' | 'superadmin'
    es_superadmin: bool


async def get_request_context(
    authorization: str = Header(..., alias="Authorization"),
    x_medio_id: str | None = Header(None, alias="X-Medio-Id"),
) -> RequestContext:
    """Resuelve el contexto del request.

    - Decodifica el bearer token.
    - Lee el medio activo del header ``X-Medio-Id`` (un usuario puede pertenecer
      a varios medios; el frontend elige cuál usar en cada request).
    - Verifica en BD que el usuario tiene rol en ese medio.
    """
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    payload: TokenPayload = decode_token(token)

    if payload.rol_global == "superadmin":
        # Superadmin debe declarar medio en header (o NULL para acceso global).
        medio_id = UUID(x_medio_id) if x_medio_id else None
        if medio_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "superadmin debe declarar X-Medio-Id en cada request",
            )
        return RequestContext(
            usuario_id=payload.sub,
            medio_id=medio_id,
            rol="superadmin",
            es_superadmin=True,
        )

    if x_medio_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Medio-Id requerido")
    medio_id = UUID(x_medio_id)

    # Verificar membresía en el medio. Esto NO usa RLS (queremos query global),
    # así que abrimos una conexión sin medio_actual y leemos usuarios_medios
    # que no tiene medio_id en RLS — la tabla intencionalmente queda fuera del RLS
    # multi-tenant (es la fuente de verdad de qué usuario accede a qué medio).
    async with tenant_connection(None) as conn:
        row = await conn.fetchrow(
            "SELECT rol FROM usuarios_medios WHERE usuario_id = $1 AND medio_id = $2",
            payload.sub,
            medio_id,
        )
    if row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "sin acceso a ese medio")

    return RequestContext(
        usuario_id=payload.sub,
        medio_id=medio_id,
        rol=row["rol"],
        es_superadmin=False,
    )


Ctx = Depends(get_request_context)
