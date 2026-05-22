"""Detector Google Trends.

Usa el endpoint público de "daily trends" sin clave (sujeto a rate limit no
documentado). Para cada ``geo`` configurado en ``ctx.config['geos']`` extrae
las búsquedas trending. Aplica peso por región para que ES-AR cuente más
que ES en perfiles aragoneses.

Forma del config:
    geos: [{"geo": "ES-AR", "peso": 0.70}, {"geo": "ES", "peso": 0.30}]
    max_resultados: 20
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
USER_AGENT = "Mozilla/5.0 (compatible; Redactia/0.1)"
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
