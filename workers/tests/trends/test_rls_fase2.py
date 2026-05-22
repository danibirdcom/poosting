"""RLS sobre las tablas de Fase 2 (perfiles_deteccion, fuentes_configuradas, presupuestos_api).

Mismo patrón que api/tests/test_rls.py: setup con admin, verificación con app.
"""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest

APP_DSN = os.environ.get("DATABASE_URL", "")
ADMIN_DSN = os.environ.get("DATABASE_URL_ADMIN", APP_DSN)

pytestmark = pytest.mark.skipif(not APP_DSN, reason="DATABASE_URL no definido")


async def _setup_dos_medios_con_perfiles(admin: asyncpg.Connection):
    slug_a = f"rls-fase2-a-{uuid4().hex[:8]}"
    slug_b = f"rls-fase2-b-{uuid4().hex[:8]}"
    medio_a = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) VALUES ($1, 'A', 'custom') RETURNING id",
        slug_a,
    )
    medio_b = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) VALUES ($1, 'B', 'custom') RETURNING id",
        slug_b,
    )
    # Insert perfiles requiere contexto multi-tenant (FORCE RLS WITH CHECK).
    await admin.execute("SELECT set_config('app.medio_actual', $1, false)", str(medio_a))
    await admin.execute(
        "INSERT INTO perfiles_deteccion (medio_id, nombre, categoria_destino) "
        "VALUES ($1, 'politica', 'politica_local')",
        medio_a,
    )
    await admin.execute("SELECT set_config('app.medio_actual', $1, false)", str(medio_b))
    await admin.execute(
        "INSERT INTO perfiles_deteccion (medio_id, nombre, categoria_destino) "
        "VALUES ($1, 'deportes', 'deportes')",
        medio_b,
    )
    await admin.execute("SELECT set_config('app.medio_actual', '', false)")
    return medio_a, medio_b, slug_a, slug_b


async def _limpiar(admin: asyncpg.Connection, slugs: list[str]) -> None:
    await admin.execute("DELETE FROM medios WHERE slug = ANY($1)", slugs)


async def test_rls_perfiles_deteccion_aisla() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_a, medio_b, slug_a, slug_b = await _setup_dos_medios_con_perfiles(admin)
    await admin.close()

    sess_a = await asyncpg.connect(APP_DSN)
    sess_b = await asyncpg.connect(APP_DSN)
    try:
        async with sess_a.transaction():
            await sess_a.execute("SELECT set_config('app.medio_actual', $1, true)", str(medio_a))
            nombres_a = {
                r["nombre"]
                for r in await sess_a.fetch("SELECT nombre FROM perfiles_deteccion")
            }
        async with sess_b.transaction():
            await sess_b.execute("SELECT set_config('app.medio_actual', $1, true)", str(medio_b))
            nombres_b = {
                r["nombre"]
                for r in await sess_b.fetch("SELECT nombre FROM perfiles_deteccion")
            }
        assert "politica" in nombres_a and "deportes" not in nombres_a
        assert "deportes" in nombres_b and "politica" not in nombres_b
    finally:
        await sess_a.close()
        await sess_b.close()
        admin = await asyncpg.connect(ADMIN_DSN)
        await _limpiar(admin, [slug_a, slug_b])
        await admin.close()


async def test_rls_insert_perfil_con_medio_ajeno_rechazado() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_a, medio_b, slug_a, slug_b = await _setup_dos_medios_con_perfiles(admin)
    await admin.close()

    sess = await asyncpg.connect(APP_DSN)
    try:
        async with sess.transaction():
            await sess.execute("SELECT set_config('app.medio_actual', $1, true)", str(medio_a))
            with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
                await sess.execute(
                    "INSERT INTO perfiles_deteccion (medio_id, nombre, categoria_destino) "
                    "VALUES ($1, 'intruso', 'x')",
                    medio_b,
                )
    finally:
        await sess.close()
        admin = await asyncpg.connect(ADMIN_DSN)
        await _limpiar(admin, [slug_a, slug_b])
        await admin.close()
