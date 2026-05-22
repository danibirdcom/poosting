"""Tests del enforcement de presupuesto contra Postgres real."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import asyncpg
import pytest

from src.trends.budget import BudgetExceededError, liberar, reservar

ADMIN_DSN = os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("DATABASE_URL", "")
APP_DSN = os.environ.get("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="DATABASE_URL no definido")


async def _crear_medio_y_budget(
    admin: asyncpg.Connection, budget_eur: Decimal
) -> tuple[str, str]:
    slug = f"test-budget-{uuid4().hex[:8]}"
    medio_id = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) "
        "VALUES ($1, 'TestBudget', 'custom') RETURNING id",
        slug,
    )
    # Fijar contexto antes de tocar tablas con FORCE RLS y WITH CHECK por medio_id.
    await admin.execute(
        "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
    )
    mes = date(datetime.now(tz=UTC).year, datetime.now(tz=UTC).month, 1)
    await admin.execute(
        "INSERT INTO presupuestos_api (medio_id, servicio, budget_mensual_eur, mes_ref) "
        "VALUES ($1, 'x_api', $2, $3)",
        medio_id,
        budget_eur,
        mes,
    )
    return str(medio_id), slug


async def _limpiar(admin: asyncpg.Connection, slug: str) -> None:
    await admin.execute("DELETE FROM medios WHERE slug = $1", slug)


async def test_reservar_dentro_del_budget_actualiza_gasto() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id, slug = await _crear_medio_y_budget(admin, Decimal("10.0"))
    try:
        # Fijar contexto y reservar
        await admin.execute("SELECT set_config('app.medio_actual', $1, false)", medio_id)
        r1 = await reservar(admin, medio_id, "x_api", Decimal("1.0"))
        assert r1.gasto_tras_reserva_eur == Decimal("1.0000")
        r2 = await reservar(admin, medio_id, "x_api", Decimal("0.5"))
        assert r2.gasto_tras_reserva_eur == Decimal("1.5000")
    finally:
        await admin.execute("SELECT set_config('app.medio_actual', '', false)")
        await _limpiar(admin, slug)
        await admin.close()


async def test_reservar_supera_95pct_bloquea() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    # budget 10 € → cap a 9.5 €
    medio_id, slug = await _crear_medio_y_budget(admin, Decimal("10.0"))
    try:
        await admin.execute("SELECT set_config('app.medio_actual', $1, false)", medio_id)
        await reservar(admin, medio_id, "x_api", Decimal("9.0"))
        # 9 + 1 = 10 > 9.5 → debe lanzar
        with pytest.raises(BudgetExceededError):
            await reservar(admin, medio_id, "x_api", Decimal("1.0"))
        # Pero un importe pequeño que mantiene <= 9.5 sí pasa
        ok = await reservar(admin, medio_id, "x_api", Decimal("0.4"))
        assert ok.gasto_tras_reserva_eur == Decimal("9.4000")
    finally:
        await admin.execute("SELECT set_config('app.medio_actual', '', false)")
        await _limpiar(admin, slug)
        await admin.close()


async def test_reservar_sin_budget_configurado_lanza_excepcion() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    slug = f"test-sinbudget-{uuid4().hex[:8]}"
    medio_id = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) VALUES ($1, 'X', 'custom') RETURNING id",
        slug,
    )
    try:
        await admin.execute("SELECT set_config('app.medio_actual', $1, false)", str(medio_id))
        with pytest.raises(BudgetExceededError):
            await reservar(admin, medio_id, "x_api", Decimal("0.01"))
    finally:
        await admin.execute("SELECT set_config('app.medio_actual', '', false)")
        await admin.execute("DELETE FROM medios WHERE slug = $1", slug)
        await admin.close()


async def test_liberar_devuelve_importe() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id, slug = await _crear_medio_y_budget(admin, Decimal("10.0"))
    try:
        await admin.execute("SELECT set_config('app.medio_actual', $1, false)", medio_id)
        r = await reservar(admin, medio_id, "x_api", Decimal("2.0"))
        await liberar(admin, r.presupuesto_id, Decimal("1.5"))
        gasto = await admin.fetchval(
            "SELECT gasto_mes_actual_eur FROM presupuestos_api WHERE id = $1",
            r.presupuesto_id,
        )
        assert gasto == Decimal("0.5000")
    finally:
        await admin.execute("SELECT set_config('app.medio_actual', '', false)")
        await _limpiar(admin, slug)
        await admin.close()
