"""Verifica que RLS aísla correctamente entre tenants.

Requiere postgres en ``DATABASE_URL`` con la migración 001_initial.sql aplicada.
"""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest

DSN = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL no definido")


async def _setup_two_medios(conn: asyncpg.Connection) -> tuple[str, str]:
    slug_a = f"test-a-{uuid4().hex[:8]}"
    slug_b = f"test-b-{uuid4().hex[:8]}"
    medio_a = await conn.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) VALUES ($1, 'A', 'custom') RETURNING id",
        slug_a,
    )
    medio_b = await conn.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) VALUES ($1, 'B', 'custom') RETURNING id",
        slug_b,
    )
    await conn.execute(
        "INSERT INTO redactores (medio_id, nombre_publico) VALUES ($1, 'Ana de A')",
        medio_a,
    )
    await conn.execute(
        "INSERT INTO redactores (medio_id, nombre_publico) VALUES ($1, 'Bea de B')",
        medio_b,
    )
    return str(medio_a), str(medio_b)


async def test_rls_aisla_redactores_entre_medios() -> None:
    conn = await asyncpg.connect(DSN)
    try:
        medio_a, medio_b = await _setup_two_medios(conn)

        # Contexto = medio A → solo ve los redactores de A.
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.medio_actual', $1, true)", medio_a)
            nombres = await conn.fetch("SELECT nombre_publico FROM redactores")
        names = {r["nombre_publico"] for r in nombres}
        assert "Ana de A" in names
        assert "Bea de B" not in names

        # Contexto = medio B → solo ve los de B.
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.medio_actual', $1, true)", medio_b)
            nombres = await conn.fetch("SELECT nombre_publico FROM redactores")
        names = {r["nombre_publico"] for r in nombres}
        assert "Bea de B" in names
        assert "Ana de A" not in names
    finally:
        # Cleanup: borrar los medios de prueba (con app.medio_actual reseteado).
        await conn.execute(
            "DELETE FROM medios WHERE slug LIKE 'test-a-%' OR slug LIKE 'test-b-%'"
        )
        await conn.close()
