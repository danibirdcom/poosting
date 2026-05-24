"""Tests del detector GTrends con HTTP mockeado."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from src.trends.base import DetectorContext
from src.trends.gtrends import JSON_PREFIX, GTrendsDetector, _parse_volumen


def _ctx_gtrends(geos=None) -> DetectorContext:
    return DetectorContext(
        medio_id=uuid4(),
        perfil_id=uuid4(),
        fuente_id=uuid4(),
        categoria_destino="general",
        pais="ES",
        idiomas=("es",),
        keywords_obligatorias=(),
        keywords_negativas=(),
        config={"geos": geos or [{"geo": "ES", "peso": 1.0}], "max_resultados": 5},
        usar_solo_como_senal=False,
    )


def test_parse_volumen_unidades() -> None:
    assert _parse_volumen("500+") == 500
    assert _parse_volumen("50K+") == 50_000
    assert _parse_volumen("1M+") == 1_000_000
    assert _parse_volumen("2.5K+") == 2_500
    assert _parse_volumen("bla") == 0


def _respuesta_dailytrends(titulos: list[str]) -> str:
    import json
    payload = {
        "default": {
            "trendingSearchesDays": [
                {
                    "trendingSearches": [
                        {
                            "title": {"query": t},
                            "formattedTraffic": "10K+",
                            "articles": [
                                {"url": f"https://ex.com/{i}", "articleTitle": f"a{i}"}
                            ],
                        }
                        for i, t in enumerate(titulos)
                    ]
                }
            ]
        }
    }
    return JSON_PREFIX + json.dumps(payload)


@pytest.mark.asyncio
async def test_gtrends_parsea_respuesta(monkeypatch) -> None:
    async def fake_get(self, url, params=None):
        return httpx.Response(
            200,
            text=_respuesta_dailytrends(["Real Zaragoza", "Pilares", "Azcón"]),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    det = GTrendsDetector()
    senales = await det.detectar(_ctx_gtrends())
    titulos = [s.termino for s in senales]
    assert "Real Zaragoza" in titulos
    assert all(s.origen == "gtrends" for s in senales)
    assert all(s.volumen == 10_000 for s in senales)
    assert all(s.region == "ES" for s in senales)


@pytest.mark.asyncio
async def test_gtrends_mezcla_geos_con_peso(monkeypatch) -> None:
    llamadas: list[str] = []

    async def fake_get(self, url, params=None):
        llamadas.append(params["geo"])
        return httpx.Response(
            200,
            text=_respuesta_dailytrends([f"trend-{params['geo']}"]),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    # Mezcla a nivel país (multi-geo). ES-AR ya no se usa (404 en Google).
    ctx = _ctx_gtrends(geos=[{"geo": "ES", "peso": 0.7}, {"geo": "FR", "peso": 0.3}])
    det = GTrendsDetector()
    senales = await det.detectar(ctx)
    assert {"ES", "FR"} == set(llamadas)
    regiones = {s.region for s in senales}
    assert regiones == {"ES", "FR"}


@pytest.mark.asyncio
async def test_gtrends_404_devuelve_vacio_no_lanza(monkeypatch) -> None:
    """Si Google devuelve 404 (geo inválida o endpoint deprecado), el
    detector debe loggear warning y devolver lista vacía, no lanzar."""

    async def fake_get(self, url, params=None):
        return httpx.Response(404, text="not found", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    senales = await GTrendsDetector().detectar(_ctx_gtrends())
    assert senales == []


@pytest.mark.asyncio
async def test_gtrends_429_devuelve_vacio_no_lanza(monkeypatch) -> None:
    """429 rate limit: log warning, lista vacía. No reintentamos a este
    nivel — un cron posterior lo capturará."""

    async def fake_get(self, url, params=None):
        return httpx.Response(429, text="rate limited", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    senales = await GTrendsDetector().detectar(_ctx_gtrends())
    assert senales == []
