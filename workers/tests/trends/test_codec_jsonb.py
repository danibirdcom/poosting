"""Tests del codec JSONB del pool de workers.

Verifica que las columnas JSONB se leen como ``dict``, no como ``str``.
Sin esto, ``ejecutar_fuente`` falla con
``'str' object has no attribute 'get'`` al leer ``fuentes_configuradas.config``.
"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import asyncpg
import pytest

from src.trends.persistence import close_pool, get_pool

APP_DSN = os.environ.get("DATABASE_URL", "")
ADMIN_DSN = os.environ.get("DATABASE_URL_ADMIN", APP_DSN)

pytestmark = pytest.mark.skipif(not APP_DSN, reason="DATABASE_URL no definido")


async def _crear_medio_con_fuente(admin: asyncpg.Connection):
    slug = f"codec-test-{uuid4().hex[:8]}"
    medio_id = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) "
        "VALUES ($1, 'codec', 'custom') RETURNING id",
        slug,
    )
    await admin.execute(
        "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
    )
    perfil_id = await admin.fetchval(
        "INSERT INTO perfiles_deteccion (medio_id, nombre, categoria_destino) "
        "VALUES ($1, 'codec-test', 'general') RETURNING id",
        medio_id,
    )
    # Insertamos config como JSON string crudo (lo que asyncpg sin codec haría).
    # El codec del pool debe devolver dict al leerlo.
    await admin.execute(
        "INSERT INTO fuentes_configuradas (medio_id, perfil_id, detector, "
        "cron_expr, config) VALUES ($1, $2, 'rss', '*/15 * * * *', $3::jsonb)",
        medio_id,
        perfil_id,
        json.dumps({"feeds": ["https://example.com/rss"], "nested": {"a": 1}}),
    )
    return medio_id, slug


async def test_pool_devuelve_jsonb_como_dict_no_str() -> None:
    """Sin codec registrado, fuentes_configuradas.config llega como str
    y `config.get('feeds')` revienta. Con `_init_conn` registrando jsonb,
    llega como dict y todo el pipeline funciona.
    """
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id, slug = await _crear_medio_con_fuente(admin)
    await admin.close()

    try:
        pool = await get_pool(APP_DSN)
        async with pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
            )
            row = await conn.fetchrow(
                "SELECT config FROM fuentes_configuradas WHERE medio_id = $1",
                medio_id,
            )

        assert row is not None, "la fuente no se ve — ¿RLS o test setup mal?"
        assert isinstance(row["config"], dict), (
            f"config debería ser dict por el codec JSONB, "
            f"llega como {type(row['config']).__name__}: {row['config']!r}"
        )
        assert row["config"]["feeds"] == ["https://example.com/rss"]
        assert row["config"]["nested"]["a"] == 1
    finally:
        await close_pool()
        admin = await asyncpg.connect(ADMIN_DSN)
        await admin.execute("DELETE FROM medios WHERE slug = $1", slug)
        await admin.close()


async def test_pool_acepta_dict_como_parametro_jsonb() -> None:
    """El encoder JSONB del codec acepta tanto dict como str (mantiene
    compatibilidad con código que ya pasa json.dumps()).
    """
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id, slug = await _crear_medio_con_fuente(admin)
    await admin.close()

    try:
        pool = await get_pool(APP_DSN)
        async with pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
            )
            # Insertar pasando dict directamente
            perfil_id = await conn.fetchval(
                "SELECT id FROM perfiles_deteccion WHERE medio_id = $1",
                medio_id,
            )
            await conn.execute(
                "INSERT INTO fuentes_configuradas (medio_id, perfil_id, detector, "
                "cron_expr, config) VALUES ($1, $2, 'gtrends', '0 * * * *', $3)",
                medio_id,
                perfil_id,
                {"geos": [{"geo": "ES", "peso": 1.0}]},
            )
            row = await conn.fetchrow(
                "SELECT config FROM fuentes_configuradas "
                "WHERE medio_id = $1 AND detector = 'gtrends'",
                medio_id,
            )
        assert isinstance(row["config"], dict)
        assert row["config"]["geos"][0]["geo"] == "ES"
    finally:
        await close_pool()
        admin = await asyncpg.connect(ADMIN_DSN)
        await admin.execute("DELETE FROM medios WHERE slug = $1", slug)
        await admin.close()
