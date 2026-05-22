"""Persistencia de señales: pool de conexiones con contexto multi-tenant.

Reaprovecha el mismo patrón que ``api/src/db/pool.py``: fija
``app.medio_actual`` por transacción para que RLS filtre correctamente.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5, command_timeout=30)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def tenant_connection(
    dsn: str, medio_id: UUID | None
) -> AsyncIterator[asyncpg.Connection]:
    pool = await get_pool(dsn)
    async with pool.acquire() as conn, conn.transaction():
        if medio_id is not None:
            await conn.execute(
                "SELECT set_config('app.medio_actual', $1, true)", str(medio_id)
            )
        yield conn


def _vector_literal(embedding: list[float] | None) -> str | None:
    if embedding is None:
        return None
    return "[" + ",".join(f"{x:.7f}" for x in embedding) + "]"


async def insertar_senal(
    conn: asyncpg.Connection,
    *,
    medio_id: UUID,
    perfil_id: UUID,
    fuente_id: UUID,
    origen: str,
    termino: str,
    categoria: str | None,
    pais: str | None,
    region: str | None,
    score: float,
    velocidad: float | None,
    volumen: int | None,
    url_origen: str | None,
    paywall: bool,
    expira_en_horas: int,
    embedding: list[float] | None,
    metadatos: dict[str, Any],
    now: datetime | None = None,
) -> UUID:
    now = now or datetime.utcnow()
    expira_at = now + timedelta(hours=expira_en_horas)

    senal_id = await conn.fetchval(
        """
        INSERT INTO senales (
          medio_id, origen, termino, pais, categoria, score,
          velocidad, volumen, metadatos, detectado_at, expira_at,
          paywall, perfil_id, fuente_id, embedding, url_origen, region
        )
        VALUES (
          $1, $2, $3, $4, $5, $6,
          $7, $8, $9::jsonb, $10, $11,
          $12, $13, $14, $15::vector, $16, $17
        )
        RETURNING id
        """,
        medio_id,
        origen,
        termino,
        pais,
        categoria,
        score,
        velocidad,
        volumen,
        _to_jsonb(metadatos),
        now,
        expira_at,
        paywall,
        perfil_id,
        fuente_id,
        _vector_literal(embedding),
        url_origen,
        region,
    )
    return senal_id


def _to_jsonb(d: dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)


async def marcar_ejecucion_fuente(
    conn: asyncpg.Connection, fuente_id: UUID, estado: str
) -> None:
    await conn.execute(
        "UPDATE fuentes_configuradas "
        "SET ultima_ejec_at = NOW(), ultima_ejec_estado = $1 "
        "WHERE id = $2",
        estado,
        fuente_id,
    )
