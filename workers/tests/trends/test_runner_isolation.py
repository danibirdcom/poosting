"""Verifica que un fallo en una fuente NO destruye los datos de fuentes previas.

Bug que motivó este test (PR #3 pre-merge, run real en staging):
las señales de Heraldo + El Periódico + X (34 total) se commiteaban
aparentemente, pero quedaban en `senales` con count = 0. Causa: el CLI
envolvía todo el bucle en una sola ``async with conn.transaction()``,
así que cuando Voyage devolvía 429 en una fuente posterior, la excepción
escalaba y disparaba rollback global.

Tras la fix, cada fuente vive en su propia transacción. Este test inyecta
un detector que tira excepción tras uno que graba señales, y verifica
que las señales previas siguen ahí.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from src.trends.base import DetectorContext, SenalCruda
from src.trends.persistence import close_pool, get_pool
from src.trends.runner import ejecutar_fuente

APP_DSN = os.environ.get("DATABASE_URL", "")
ADMIN_DSN = os.environ.get("DATABASE_URL_ADMIN", APP_DSN)
pytestmark = pytest.mark.skipif(not APP_DSN, reason="DATABASE_URL no definido")


class _DetectorOK:
    """Devuelve siempre una señal con el término dado."""

    nombre = "rss"

    def __init__(self, termino: str) -> None:
        self._termino = termino

    async def detectar(self, ctx: DetectorContext) -> list[SenalCruda]:
        return [
            SenalCruda(
                origen="rss",
                termino=self._termino,
                categoria=ctx.categoria_destino,
                pais=ctx.pais,
                region=None,
                velocidad=1.0,
                volumen=1,
                url_origen="https://example.com/x",
                paywall=False,
                expira_en_horas=24,
                metadatos={"feed": "test"},
            )
        ]


class _DetectorBoom:
    """Detector que SIEMPRE lanza."""

    nombre = "rss"

    async def detectar(self, ctx: DetectorContext) -> list[SenalCruda]:
        raise RuntimeError("simulado: detector roto")


class _EmbeddingsBoom:
    """Embeddings que lanzan en la primera llamada (simula Voyage 429)."""

    async def embed(self, textos: list[str], input_type: str = "document") -> list[list[float]]:
        raise RuntimeError("simulado: voyage 429")


class _EmbeddingsFake:
    async def embed(self, textos: list[str], input_type: str = "document") -> list[list[float]]:
        return [[0.1 + 0.0001 * i] * 1024 for i, _ in enumerate(textos)]


async def _setup(admin: asyncpg.Connection) -> tuple[UUID, UUID, UUID, str]:
    slug = f"iso-{uuid4().hex[:8]}"
    medio_id = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) "
        "VALUES ($1, 'Isolation', 'custom') RETURNING id",
        slug,
    )
    await admin.execute(
        "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
    )
    perfil_id = await admin.fetchval(
        "INSERT INTO perfiles_deteccion (medio_id, nombre, categoria_destino) "
        "VALUES ($1, 'iso-perfil', 'general') RETURNING id",
        medio_id,
    )
    fuente_a = await admin.fetchval(
        "INSERT INTO fuentes_configuradas "
        "(medio_id, perfil_id, detector, cron_expr, config) "
        "VALUES ($1, $2, 'rss', '*/15 * * * *', '{}'::jsonb) RETURNING id",
        medio_id,
        perfil_id,
    )
    fuente_b = await admin.fetchval(
        "INSERT INTO fuentes_configuradas "
        "(medio_id, perfil_id, detector, cron_expr, config) "
        "VALUES ($1, $2, 'rss', '*/15 * * * *', '{}'::jsonb) RETURNING id",
        medio_id,
        perfil_id,
    )
    return medio_id, fuente_a, fuente_b, slug


async def _cleanup(slug: str) -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute("DELETE FROM medios WHERE slug = $1", slug)
    finally:
        await admin.close()


async def test_runner_detector_falla_no_borra_senales_previas() -> None:
    """A graba señal. B explota en detectar(). La señal de A persiste."""
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id, fuente_a, fuente_b, slug = await _setup(admin)
    await admin.close()

    try:
        pool = await get_pool(APP_DSN)
        # A: ok
        res_a = await ejecutar_fuente(pool, medio_id, fuente_a, _DetectorOK("A"), _EmbeddingsFake())
        assert res_a.estado == "ok", res_a
        assert res_a.n_insertadas == 1
        # B: boom
        res_b = await ejecutar_fuente(pool, medio_id, fuente_b, _DetectorBoom(), _EmbeddingsFake())
        assert res_b.estado == "error"

        # Verificar en BD que la señal de A sigue ahí
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await admin.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
            )
            n_a = await admin.fetchval(
                "SELECT COUNT(*) FROM senales WHERE fuente_id = $1", fuente_a
            )
            estado_a = await admin.fetchval(
                "SELECT ultima_ejec_estado FROM fuentes_configuradas WHERE id = $1",
                fuente_a,
            )
            estado_b = await admin.fetchval(
                "SELECT ultima_ejec_estado FROM fuentes_configuradas WHERE id = $1",
                fuente_b,
            )
            assert n_a == 1, f"perdida señal de A tras fallo de B (count={n_a})"
            assert estado_a == "ok"
            assert estado_b == "error"
        finally:
            await admin.close()
    finally:
        await close_pool()
        await _cleanup(slug)


async def test_runner_embeddings_falla_no_borra_senales_previas() -> None:
    """A graba con embeddings ok. B explota en embeddings.embed(). A persiste.

    Reproduce exactamente el escenario del run real: detector devuelve
    señales, pero embeddings.embed() lanza (Voyage 429).
    """
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id, fuente_a, fuente_b, slug = await _setup(admin)
    await admin.close()

    try:
        pool = await get_pool(APP_DSN)
        await ejecutar_fuente(pool, medio_id, fuente_a, _DetectorOK("A"), _EmbeddingsFake())
        res_b = await ejecutar_fuente(pool, medio_id, fuente_b, _DetectorOK("B"), _EmbeddingsBoom())
        assert res_b.estado == "error"

        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await admin.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
            )
            n_a = await admin.fetchval(
                "SELECT COUNT(*) FROM senales WHERE fuente_id = $1", fuente_a
            )
            n_b = await admin.fetchval(
                "SELECT COUNT(*) FROM senales WHERE fuente_id = $1", fuente_b
            )
            assert n_a == 1, f"señal de A perdida tras fallo de embeddings en B (n={n_a})"
            assert n_b == 0, f"señal de B insertada pese a fallo de embeddings (n={n_b})"
        finally:
            await admin.close()
    finally:
        await close_pool()
        await _cleanup(slug)
