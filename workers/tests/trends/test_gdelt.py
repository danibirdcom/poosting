"""Tests del detector GDELT con HTTP mockeado."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from src.trends.base import DetectorContext
from src.trends.gdelt import GDELTDetector


def _ctx() -> DetectorContext:
    return DetectorContext(
        medio_id=uuid4(),
        perfil_id=uuid4(),
        fuente_id=uuid4(),
        categoria_destino="general",
        pais="ES",
        idiomas=("es",),
        keywords_obligatorias=("aragón",),
        keywords_negativas=(),
        config={"max_records": 10, "timespan": "24h"},
        usar_solo_como_senal=False,
    )


@pytest.mark.asyncio
async def test_gdelt_parsea_articles(monkeypatch) -> None:
    payload = {
        "articles": [
            {
                "url": "https://ex.com/a",
                "title": "Aragón aprueba algo",
                "domain": "ex.com",
                "language": "Spanish",
                "seendate": "20260522T100000Z",
                "sourcecountry": "Spain",
                "tone": "-1.2",
            },
            {
                "url": "https://ex.com/b",
                "title": "Otra noticia",
                "domain": "ex.com",
                "language": "Spanish",
                "seendate": "20260522T110000Z",
                "sourcecountry": "Spain",
                "tone": "0.0",
            },
        ]
    }

    async def fake_get(self, url, params=None):
        assert "aragón" in params["query"].lower()
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=payload, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    det = GDELTDetector()
    senales = await det.detectar(_ctx())
    assert len(senales) == 2
    assert senales[0].origen == "gdelt"
    assert senales[0].url_origen.startswith("https://")
    assert senales[0].region == "Spain"


@pytest.fixture
def _instant_retries(monkeypatch):
    """Evita que tenacity duerma de verdad entre reintentos."""
    import asyncio

    async def _no_sleep(_secs: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


@pytest.mark.asyncio
async def test_gdelt_devuelve_vacio_si_5xx_persistente(monkeypatch, _instant_retries) -> None:
    """Tras 3 intentos en 503, devuelve [] en vez de propagar."""
    intentos: list[int] = []

    async def fake_get(self, url, params=None):
        intentos.append(1)
        return httpx.Response(503, text="upstream down", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    senales = await GDELTDetector().detectar(_ctx())
    assert senales == []
    assert len(intentos) == 3, f"se esperaban 3 intentos por retry, hubo {len(intentos)}"


@pytest.mark.asyncio
async def test_gdelt_reintenta_429_y_recupera(monkeypatch, _instant_retries) -> None:
    """429 seguido de 200 → devuelve señales sin propagar excepción."""
    intentos: list[int] = []
    payload_ok = {"articles": [{"url": "https://ex.com/a", "title": "OK", "domain": "ex.com"}]}

    async def fake_get(self, url, params=None):
        intentos.append(1)
        if len(intentos) < 2:
            return httpx.Response(429, request=httpx.Request("GET", url))
        return httpx.Response(200, json=payload_ok, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    senales = await GDELTDetector().detectar(_ctx())
    assert len(senales) == 1
    assert senales[0].termino == "OK"
    assert len(intentos) == 2
