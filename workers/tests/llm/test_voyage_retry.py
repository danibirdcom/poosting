"""Verifica el retry exponencial de Voyage en 429/5xx.

Mockea ``httpx.AsyncClient.post`` con respuestas controladas para no pegar
a la API real. ``tenacity`` espera entre reintentos; usamos ``monkeypatch``
sobre el sleep interno para que el test sea instantáneo.
"""

from __future__ import annotations

import httpx
import pytest

from src.llm.embeddings import VoyageEmbeddings, _es_retryable


def _resp(status: int, body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=body or {"data": [{"embedding": [0.1] * 1024}]},
        request=httpx.Request("POST", "https://api.voyageai.com/v1/embeddings"),
    )


@pytest.fixture(autouse=True)
def _instant_retries(monkeypatch):
    """Hace que tenacity no espere entre reintentos durante los tests."""

    async def _no_sleep(_secs: float) -> None:
        return None

    import asyncio
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


def _http_err(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://x")
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(status, request=req))


def test_es_retryable_clasifica_correctamente() -> None:
    assert _es_retryable(_http_err(429))
    assert _es_retryable(_http_err(503))
    assert not _es_retryable(_http_err(400))
    assert not _es_retryable(_http_err(401))
    assert _es_retryable(httpx.ConnectError("net down"))
    assert not _es_retryable(ValueError("unrelated"))


async def test_voyage_reintenta_en_429_y_eventualmente_pasa(monkeypatch) -> None:
    """Dos 429 seguidos de un 200 → resultado OK tras 3 intentos."""
    intentos: list[int] = []

    async def fake_post(self, url, json=None, headers=None):
        intentos.append(1)
        if len(intentos) < 3:
            return _resp(429)
        return _resp(200)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    client = VoyageEmbeddings(api_key="fake")
    result = await client.embed(["hola"])
    assert len(intentos) == 3, f"esperados 3 intentos, hubo {len(intentos)}"
    assert len(result) == 1
    assert len(result[0]) == 1024


async def test_voyage_no_reintenta_en_4xx_no_429(monkeypatch) -> None:
    """400 (bad request) NO se reintenta — no es transitorio."""
    intentos: list[int] = []

    async def fake_post(self, url, json=None, headers=None):
        intentos.append(1)
        return _resp(400)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    client = VoyageEmbeddings(api_key="fake")
    with pytest.raises(httpx.HTTPStatusError):
        await client.embed(["hola"])
    assert len(intentos) == 1, f"4xx no debe reintentarse, hubo {len(intentos)} intentos"


async def test_voyage_agota_tras_3_intentos(monkeypatch) -> None:
    """Si todos los intentos devuelven 429, levanta tras el 3º."""
    intentos: list[int] = []

    async def fake_post(self, url, json=None, headers=None):
        intentos.append(1)
        return _resp(429)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    client = VoyageEmbeddings(api_key="fake")
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await client.embed(["hola"])
    assert exc.value.response.status_code == 429
    assert len(intentos) == 3
