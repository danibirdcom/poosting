"""Detector GDELT.

GDELT DOC API v2: agregador de noticias global con filtros por país, idioma
y tema. Sin clave de API, rate limit razonable. Útil para temas con cobertura
internacional o eventos de gran impacto.

Retry exponencial en 429/5xx vía tenacity (3 intentos, esperas 2s→4s capped
a 8s). Known issue: en runners de GitHub Actions el 429 es común porque
muchas IPs comparten salida; cuando movamos a daemon con IP fija mejorará.

Doc: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .base import DetectorContext, SenalCruda

logger = structlog.get_logger(__name__)

BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
TIMEOUT_S = 20.0
USER_AGENT = "Redactia/0.1 (+https://redactia.es)"


def _es_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, httpx.TransportError | httpx.TimeoutException)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    retry=retry_if_exception(_es_retryable),
    reraise=True,
)
async def _fetch_gdelt(params: dict[str, str]) -> httpx.Response:
    async with httpx.AsyncClient(
        timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}
    ) as client:
        resp = await client.get(BASE_URL, params=params)
        # 429 y 5xx → raise para que tenacity reintente.
        if resp.status_code == 429 or resp.status_code >= 500:
            logger.warning("gdelt_retry", status=resp.status_code)
            resp.raise_for_status()
        return resp


class GDELTDetector:
    nombre = "gdelt"

    async def detectar(self, ctx: DetectorContext) -> list[SenalCruda]:
        query = self._build_query(ctx)
        max_records = int(ctx.config.get("max_records", 50))
        timespan = ctx.config.get("timespan", "24h")

        params = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(max_records),
            "sort": "hybridrel",
            "timespan": timespan,
        }

        try:
            resp = await _fetch_gdelt(params)
        except httpx.HTTPStatusError as err:
            # Tras agotar reintentos, devolvemos vacío en lugar de propagar
            # — el cron siguiente lo intentará. Para que llegue a marcar
            # "error", el runner debe verlo como excepción; pero aquí el
            # 429 sostenido es un known issue de GHA, no un fallo real
            # de la fuente.
            logger.warning(
                "gdelt_agotados_reintentos",
                status=err.response.status_code,
                query=query,
            )
            return []
        resp.raise_for_status()
        data = resp.json()

        articles: list[dict[str, Any]] = data.get("articles", []) or []
        senales: list[SenalCruda] = []
        for art in articles:
            titulo = (art.get("title") or "").strip()
            if not titulo:
                continue
            senales.append(
                SenalCruda(
                    origen="gdelt",
                    termino=titulo,
                    categoria=ctx.categoria_destino,
                    pais=ctx.pais,
                    region=art.get("sourcecountry"),
                    velocidad=None,
                    volumen=1,
                    url_origen=art.get("url"),
                    paywall=False,    # GDELT no marca paywall; usar dominio si hace falta
                    expira_en_horas=24,
                    metadatos={
                        "domain": art.get("domain"),
                        "language": art.get("language"),
                        "seendate": art.get("seendate"),
                        "tone": art.get("tone"),
                    },
                )
            )
        return senales

    def _build_query(self, ctx: DetectorContext) -> str:
        base = ctx.config.get("query")
        if base:
            return str(base)
        partes: list[str] = []
        if ctx.idiomas:
            idiomas = ",".join(ctx.idiomas)
            partes.append(f"sourcelang:{idiomas}")
        if ctx.pais:
            partes.append(f"sourcecountry:{ctx.pais}")
        if ctx.keywords_obligatorias:
            keywords = " OR ".join(f'"{k}"' for k in ctx.keywords_obligatorias)
            partes.append(f"({keywords})")
        return " ".join(partes) or ctx.categoria_destino
