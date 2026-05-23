"""Detector X (Twitter) API v2.

Implementación funcional con budget enforcement HARD-CAP. Si no hay bearer
token configurado, hace skip silencioso (warning log, no crash) — el código
está completo para activar cuando ``X_API_BEARER`` esté disponible.

Coste estimado por read: ``X_READ_COST_EUR`` (0.0046 €). Antes de cada
llamada reservamos contra ``presupuestos_api``. Si la reserva falla,
abortamos limpiamente.

Solo recommended para medios con `presupuestos_api(servicio='x_api')` activo
(en Fase 2: solo Hoy Aragón).
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import asyncpg
import httpx
import structlog

from .base import DetectorContext, SenalCruda
from .budget import BudgetExceededError, liberar, reservar

logger = structlog.get_logger(__name__)

BASE_URL = "https://api.x.com/2/tweets/search/recent"
TIMEOUT_S = 20.0
X_READ_COST_EUR = Decimal("0.0046")
SERVICIO = "x_api"


class XApiDetector:
    """Necesita acceso a BD para reservar budget. La reserva se hace en una
    conexión dedicada (autocommit) del pool, **fuera** de la transacción que
    orquesta los inserts de señales en el runner. Razón: si la transacción
    exterior hace rollback, la llamada HTTP ya ha gastado dinero real y el
    contador del budget debe persistir. Ver docs/runbooks/budget.md
    §"Aislamiento transaccional".
    """

    nombre = "x"

    def __init__(self, pool: asyncpg.Pool, bearer_token: str | None = None) -> None:
        self._pool = pool
        self._bearer = bearer_token or os.environ.get("X_API_BEARER", "")

    async def detectar(self, ctx: DetectorContext) -> list[SenalCruda]:
        if not self._bearer:
            logger.warning(
                "x_api_skip_sin_bearer",
                medio_id=str(ctx.medio_id),
                msg="X_API_BEARER no configurado; saltando detector",
            )
            return []

        query: str = (
            ctx.config.get("query")
            or self._build_query_default(ctx)
        )
        max_results = max(10, min(int(ctx.config.get("max_results", 15)), 100))

        # Conexión dedicada, sin envolver en transaction(). Cada statement se
        # auto-commitea, así la reserva del budget sobrevive a un rollback en
        # la transacción del runner.
        async with self._pool.acquire() as budget_conn:
            # presupuestos_api tiene FORCE RLS → necesitamos contexto
            await budget_conn.execute(
                "SELECT set_config('app.medio_actual', $1, false)",
                str(ctx.medio_id),
            )
            try:
                reserva = await reservar(
                    budget_conn, ctx.medio_id, SERVICIO, X_READ_COST_EUR
                )
            except BudgetExceededError as err:
                logger.warning(
                    "x_api_budget_bloquea",
                    medio_id=str(ctx.medio_id),
                    razon=str(err),
                )
                return []

            data: dict[str, Any] | None = None
            try:
                params = {
                    "query": query,
                    "max_results": str(max_results),
                    "tweet.fields": "public_metrics,created_at,lang",
                }
                headers = {"Authorization": f"Bearer {self._bearer}"}
                async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                    resp = await client.get(BASE_URL, params=params, headers=headers)
                if resp.status_code == 429:
                    await liberar(budget_conn, reserva.presupuesto_id, X_READ_COST_EUR)
                    logger.warning("x_api_429", medio_id=str(ctx.medio_id))
                    return []
                if resp.status_code >= 400:
                    await liberar(budget_conn, reserva.presupuesto_id, X_READ_COST_EUR)
                    logger.warning(
                        "x_api_error",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    return []
                data = resp.json()
            except Exception:
                await liberar(budget_conn, reserva.presupuesto_id, X_READ_COST_EUR)
                raise

        # Conexión budget liberada al pool. La reserva ya está persistida.
        assert data is not None
        tweets: list[dict[str, Any]] = data.get("data", []) or []
        senales: list[SenalCruda] = []
        for tw in tweets:
            texto = (tw.get("text") or "").strip()
            if not texto:
                continue
            metricas = tw.get("public_metrics", {}) or {}
            engagement = (
                int(metricas.get("retweet_count", 0))
                + int(metricas.get("like_count", 0))
                + int(metricas.get("reply_count", 0))
                + int(metricas.get("quote_count", 0))
            )
            tweet_id = tw.get("id")
            url_tweet = f"https://x.com/i/web/status/{tweet_id}" if tweet_id else None
            senales.append(
                SenalCruda(
                    origen="x",
                    termino=texto[:280],
                    categoria=ctx.categoria_destino,
                    pais=ctx.pais,
                    region=None,
                    velocidad=None,
                    volumen=engagement,
                    url_origen=url_tweet,
                    paywall=False,
                    expira_en_horas=8,   # X envejece rápido
                    metadatos={
                        "tweet_id": tw.get("id"),
                        "created_at": tw.get("created_at"),
                        "lang": tw.get("lang"),
                        "metrics": metricas,
                    },
                )
            )

        logger.info(
            "x_api_ok",
            medio_id=str(ctx.medio_id),
            n_senales=len(senales),
            gasto_tras_eur=str(reserva.gasto_tras_reserva_eur),
        )
        return senales

    def _build_query_default(self, ctx: DetectorContext) -> str:
        partes: list[str] = []
        if ctx.keywords_obligatorias:
            partes.append("(" + " OR ".join(f'"{k}"' for k in ctx.keywords_obligatorias) + ")")
        if ctx.idiomas:
            partes.append("(" + " OR ".join(f"lang:{lang}" for lang in ctx.idiomas) + ")")
        partes.append("-is:retweet")
        return " ".join(partes)
