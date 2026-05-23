"""Detector Google Trends.

Usa el endpoint público de "daily trends" sin clave (sujeto a rate limit no
documentado). Para cada ``geo`` configurado en ``ctx.config['geos']`` extrae
las búsquedas trending.

⚠️ Limitaciones conocidas (Fase 2, ver `docs/agents/trend_detector.md`):
- Google **no soporta granularidad de comunidad autónoma** en este
  endpoint. ``ES-AR`` devuelve 404. Sólo códigos de país (``ES``, ``FR``,
  ``GB``, etc.) son válidos. El multiplicador de región del scorer se
  vuelve un no-op cuando todas las geos son nivel país.
- Google bloquea User-Agents que parezcan bots (entre ellos versiones
  antiguas o cadenas tipo "compatible; Redactia"). Usamos un UA realista
  de Chrome (ver constante ``USER_AGENT``).
- Si Google migra el endpoint, devolverá 404. El detector responde con
  lista vacía y log warning, no rompe el pipeline.

Forma del config (Fase 2):
    geos: [{"geo": "ES", "peso": 1.0}]
    max_resultados: 20

Follow-up Fase 2.5: investigar pytrends / endpoint nuevo si Google
deprecia este definitivamente.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import structlog

from .base import DetectorContext, SenalCruda

logger = structlog.get_logger(__name__)

BASE_URL = "https://trends.google.com/trends/api/dailytrends"
TIMEOUT_S = 15.0
# User-Agent realista de Chrome: Google devuelve 404 a UAs con palabras
# como "bot", "crawler" o cadenas custom.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Google prefija la respuesta con ")]}'," para evitar JSON hijacking.
JSON_PREFIX = ")]}',"


class GTrendsDetector:
    nombre = "gtrends"

    async def detectar(self, ctx: DetectorContext) -> list[SenalCruda]:
        geos: list[dict[str, Any]] = ctx.config.get("geos") or [
            {"geo": ctx.pais, "peso": 1.0}
        ]
        max_resultados = int(ctx.config.get("max_resultados", 20))

        async with httpx.AsyncClient(
            timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}
        ) as client:
            tasks = [self._procesar_geo(client, ctx, g, max_resultados) for g in geos]
            resultados = await asyncio.gather(*tasks, return_exceptions=True)

        senales: list[SenalCruda] = []
        for geo, res in zip(geos, resultados, strict=True):
            if isinstance(res, BaseException):
                logger.warning("gtrends_geo_error", geo=geo, error=str(res))
                continue
            senales.extend(res)
        return senales

    async def _procesar_geo(
        self,
        client: httpx.AsyncClient,
        ctx: DetectorContext,
        geo_cfg: dict[str, Any],
        max_resultados: int,
    ) -> list[SenalCruda]:
        geo = geo_cfg["geo"]
        peso = float(geo_cfg.get("peso", 1.0))

        params = {"hl": "es-ES", "tz": "-120", "geo": geo, "ns": "15"}
        resp = await client.get(BASE_URL, params=params)
        if resp.status_code == 404:
            # Geo no válido o endpoint deprecado. Log y devuelve vacío en
            # lugar de romper. Si veo este warning de forma persistente,
            # tocar revisar la configuración de seed_hoy_aragon.py o
            # marcar la fuente como activo=FALSE.
            logger.warning(
                "gtrends_404",
                geo=geo,
                msg="endpoint devolvió 404; geo no válida o API deprecada",
            )
            return []
        if resp.status_code == 429:
            logger.warning("gtrends_429", geo=geo)
            return []
        resp.raise_for_status()
        text = resp.text
        if text.startswith(JSON_PREFIX):
            text = text[len(JSON_PREFIX):]
        data = json.loads(text)

        trends_list = (
            data.get("default", {}).get("trendingSearchesDays", [{}])[0].get("trendingSearches", [])
        )

        senales: list[SenalCruda] = []
        for trend in trends_list[:max_resultados]:
            titulo = trend.get("title", {}).get("query", "").strip()
            if not titulo:
                continue
            traffic_raw = trend.get("formattedTraffic", "0")
            volumen = _parse_volumen(traffic_raw)
            articles = trend.get("articles", [])
            url_articulo = articles[0].get("url") if articles else None

            senales.append(
                SenalCruda(
                    origen="gtrends",
                    termino=titulo,
                    categoria=ctx.categoria_destino,
                    pais=ctx.pais,
                    region=geo,
                    velocidad=None,
                    volumen=volumen,
                    url_origen=url_articulo,
                    paywall=False,
                    expira_en_horas=24,
                    metadatos={
                        "geo": geo,
                        "peso_region": peso,
                        "traffic_raw": traffic_raw,
                        "articulos_relacionados": [
                            {"url": a.get("url"), "title": a.get("articleTitle")}
                            for a in articles[:3]
                        ],
                    },
                )
            )
        return senales


def _parse_volumen(traffic: str) -> int:
    """Convierte '50K+', '1M+', '500+' a un int aproximado."""
    t = traffic.strip().rstrip("+").upper()
    multiplicador = 1
    if t.endswith("K"):
        multiplicador = 1000
        t = t[:-1]
    elif t.endswith("M"):
        multiplicador = 1_000_000
        t = t[:-1]
    try:
        return int(float(t) * multiplicador)
    except ValueError:
        return 0
