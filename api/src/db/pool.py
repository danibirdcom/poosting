"""Pool de conexiones asyncpg con contexto multi-tenant.

Toda query de aplicación debe pasar por ``tenant_connection`` para fijar
``app.medio_actual`` en la sesión Postgres antes de ejecutar. Las RLS policies
declaradas en ``001_initial.sql`` leen ese setting.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional
from uuid import UUID

import asyncpg
import structlog

from src.settings import get_settings

logger = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,
            max_size=20,
            command_timeout=30,
        )
        logger.info("db_pool_created", min_size=2, max_size=20)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("db_pool_closed")


@asynccontextmanager
async def tenant_connection(medio_id: Optional[UUID]) -> AsyncIterator[asyncpg.Connection]:
    """Adquiere una conexión y fija el contexto multi-tenant para el scope.

    Si ``medio_id`` es None (caso superadmin), no se fija el setting y la
    RLS policy verá ``app_current_medio() IS NULL``. Las queries normales no
    devolverán nada bajo esa condición — usar SECURITY DEFINER para acceso global.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if medio_id is not None:
                await conn.execute(
                    "SELECT set_config('app.medio_actual', $1, true)",
                    str(medio_id),
                )
            yield conn
