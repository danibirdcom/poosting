"""Verifica el aislamiento RLS entre tenants.

Setup: ``DATABASE_URL_ADMIN`` apunta al usuario owner (redactia_admin o
equivalente), que aplica las migraciones y crea los medios de prueba.
``DATABASE_URL`` apunta al usuario de aplicación (redactia_app_ci en CI),
que es el que valida que RLS le aísla.

Si solo se define ``DATABASE_URL``, se usa el mismo para setup y app: con
FORCE RLS el comportamiento es idéntico porque el owner también está sujeto
a las policies.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import asyncpg
import pytest

APP_DSN = os.environ.get("DATABASE_URL", "")
ADMIN_DSN = os.environ.get("DATABASE_URL_ADMIN", APP_DSN)

pytestmark = pytest.mark.skipif(not APP_DSN, reason="DATABASE_URL no definido")


async def _crear_medios_y_redactores(
    admin: asyncpg.Connection,
) -> tuple[UUID, UUID, str, str]:
    slug_a = f"test-a-{uuid4().hex[:8]}"
    slug_b = f"test-b-{uuid4().hex[:8]}"
    medio_a = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) VALUES ($1, 'A', 'custom') RETURNING id",
        slug_a,
    )
    medio_b = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) VALUES ($1, 'B', 'custom') RETURNING id",
        slug_b,
    )
    await admin.execute(
        "INSERT INTO redactores (medio_id, nombre_publico) VALUES ($1, 'Ana de A')",
        medio_a,
    )
    await admin.execute(
        "INSERT INTO redactores (medio_id, nombre_publico) VALUES ($1, 'Bea de B')",
        medio_b,
    )
    return medio_a, medio_b, slug_a, slug_b


async def _limpiar(admin: asyncpg.Connection, slugs: list[str]) -> None:
    await admin.execute("DELETE FROM medios WHERE slug = ANY($1)", slugs)


async def test_rls_aisla_redactores_entre_medios() -> None:
    """Dos sesiones del rol app, cada una con un medio distinto, no se ven."""
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_a, medio_b, slug_a, slug_b = await _crear_medios_y_redactores(admin)
    await admin.close()

    sesion_a = await asyncpg.connect(APP_DSN)
    sesion_b = await asyncpg.connect(APP_DSN)
    try:
        async with sesion_a.transaction():
            await sesion_a.execute(
                "SELECT set_config('app.medio_actual', $1, true)", str(medio_a)
            )
            filas_a = await sesion_a.fetch("SELECT nombre_publico FROM redactores")

        async with sesion_b.transaction():
            await sesion_b.execute(
                "SELECT set_config('app.medio_actual', $1, true)", str(medio_b)
            )
            filas_b = await sesion_b.fetch("SELECT nombre_publico FROM redactores")

        nombres_a = {r["nombre_publico"] for r in filas_a}
        nombres_b = {r["nombre_publico"] for r in filas_b}

        assert "Ana de A" in nombres_a
        assert "Bea de B" not in nombres_a
        assert "Bea de B" in nombres_b
        assert "Ana de A" not in nombres_b
    finally:
        await sesion_a.close()
        await sesion_b.close()
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await _limpiar(admin, [slug_a, slug_b])
        finally:
            await admin.close()


async def test_rls_sin_contexto_no_devuelve_filas() -> None:
    """Sin ``app.medio_actual`` fijado, el rol app no ve filas multi-tenant."""
    admin = await asyncpg.connect(ADMIN_DSN)
    _, _, slug_a, slug_b = await _crear_medios_y_redactores(admin)
    await admin.close()

    sesion = await asyncpg.connect(APP_DSN)
    try:
        # No fijamos app.medio_actual → app_current_medio() devuelve NULL.
        # La policy `medio_id = NULL` evalúa NULL (no TRUE), así que se
        # niegan todas las filas. No debe lanzar error, solo devolver 0.
        filas = await sesion.fetch("SELECT id FROM redactores")
        assert filas == []
    finally:
        await sesion.close()
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await _limpiar(admin, [slug_a, slug_b])
        finally:
            await admin.close()


async def test_rls_insert_rechaza_medio_ajeno() -> None:
    """WITH CHECK debe bloquear INSERTs cuyo medio_id no coincida con el contexto."""
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_a, medio_b, slug_a, slug_b = await _crear_medios_y_redactores(admin)
    await admin.close()

    sesion = await asyncpg.connect(APP_DSN)
    try:
        async with sesion.transaction():
            await sesion.execute(
                "SELECT set_config('app.medio_actual', $1, true)", str(medio_a)
            )
            with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
                # Intento de insertar un redactor en el medio B con contexto A.
                await sesion.execute(
                    "INSERT INTO redactores (medio_id, nombre_publico) "
                    "VALUES ($1, 'intruso')",
                    medio_b,
                )
    finally:
        await sesion.close()
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await _limpiar(admin, [slug_a, slug_b])
        finally:
            await admin.close()
