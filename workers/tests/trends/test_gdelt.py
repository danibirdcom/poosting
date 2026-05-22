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


@pytest.mark.asyncio
async def test_gdelt_devuelve_vacio_si_5xx(monkeypatch) -> None:
    async def fake_get(self, url, params=None):
        req = httpx.Request("GET", url)
        return httpx.Response(503, text="upstream down", request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    senales = await GDELTDetector().detectar(_ctx())
    assert senales == []
