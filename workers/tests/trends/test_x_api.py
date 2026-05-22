"""Tests del detector X API con budget enforcement contra BD real."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import asyncpg
import httpx
import pytest

from src.trends.base import DetectorContext
from src.trends.x_api import XApiDetector

APP_DSN = os.environ.get("DATABASE_URL", "")
ADMIN_DSN = os.environ.get("DATABASE_URL_ADMIN", APP_DSN)
pytestmark = pytest.mark.skipif(not APP_DSN, reason="DATABASE_URL no definido")


async def _setup(admin: asyncpg.Connection, budget_eur: Decimal):
    slug = f"x-test-{uuid4().hex[:8]}"
    medio_id = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) VALUES ($1, 'X', 'custom') RETURNING id",
        slug,
    )
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
    return medio_id, slug


def _ctx(medio_id) -> DetectorContext:
    return DetectorContext(
        medio_id=medio_id,
        perfil_id=uuid4(),
        fuente_id=uuid4(),
        categoria_destino="politica_local",
        pais="ES",
        idiomas=("es",),
        keywords_obligatorias=("aragón",),
        keywords_negativas=(),
        config={"max_results": 10},
        usar_solo_como_senal=False,
    )


async def test_x_api_skip_sin_bearer() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id, slug = await _setup(admin, Decimal("10.0"))
    try:
        await admin.execute("SELECT set_config('app.medio_actual', $1, false)", str(medio_id))
        det = XApiDetector(conn=admin, bearer_token="")
        senales = await det.detectar(_ctx(medio_id))
        assert senales == []
    finally:
        await admin.execute("SELECT set_config('app.medio_actual', '', false)")
        await admin.execute("DELETE FROM medios WHERE slug = $1", slug)
        await admin.close()


async def test_x_api_consume_budget_y_devuelve_senales(monkeypatch) -> None:
    payload = {
        "data": [
            {
                "id": "1",
                "text": "Azcón habla en Zaragoza sobre presupuestos",
                "public_metrics": {
                    "retweet_count": 10,
                    "like_count": 50,
                    "reply_count": 5,
                    "quote_count": 2,
                },
                "created_at": "2026-05-22T10:00:00Z",
                "lang": "es",
            }
        ]
    }

    async def fake_get(self, url, params=None, headers=None):
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id, slug = await _setup(admin, Decimal("10.0"))
    try:
        await admin.execute("SELECT set_config('app.medio_actual', $1, false)", str(medio_id))
        det = XApiDetector(conn=admin, bearer_token="fake")
        senales = await det.detectar(_ctx(medio_id))
        assert len(senales) == 1
        assert senales[0].volumen == 67  # 10+50+5+2

        gasto = await admin.fetchval(
            "SELECT gasto_mes_actual_eur FROM presupuestos_api WHERE medio_id = $1",
            medio_id,
        )
        assert gasto > 0
    finally:
        await admin.execute("SELECT set_config('app.medio_actual', '', false)")
        await admin.execute("DELETE FROM medios WHERE slug = $1", slug)
        await admin.close()


async def test_x_api_budget_excedido_bloquea(monkeypatch) -> None:
    """Si el budget está casi agotado, el detector no debe llamar a la API."""
    llamadas: list[str] = []

    async def fake_get(self, url, params=None, headers=None):
        llamadas.append(url)
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id, slug = await _setup(admin, Decimal("0.001"))  # budget minúsculo
    try:
        await admin.execute("SELECT set_config('app.medio_actual', $1, false)", str(medio_id))
        det = XApiDetector(conn=admin, bearer_token="fake")
        senales = await det.detectar(_ctx(medio_id))
        assert senales == []
        assert llamadas == []  # ni siquiera se llamó a la API
    finally:
        await admin.execute("SELECT set_config('app.medio_actual', '', false)")
        await admin.execute("DELETE FROM medios WHERE slug = $1", slug)
        await admin.close()
