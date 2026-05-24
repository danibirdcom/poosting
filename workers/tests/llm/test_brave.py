"""Tests del cliente Brave Search (parsing y manejo de errores).

httpx se mockea con ``MockTransport`` — no se hace red real.
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.llm.brave import BraveSearch, _dominio_de


def _respuesta_brave_ok() -> dict:
    """Estructura simplificada de la respuesta real de Brave Web Search."""
    return {
        "web": {
            "results": [
                {
                    "url": "https://aragondigital.es/articulo-uno",
                    "title": "Artículo uno",
                    "description": "Resumen del artículo uno sobre presupuestos.",
                    "age": "2026-05-23T10:00:00Z",
                },
                {
                    "url": "https://europapress.es/articulo-dos",
                    "title": "Artículo dos",
                    "description": "Segundo resumen.",
                },
                {
                    # Sin url — debe descartarse.
                    "title": "Sin URL",
                    "description": "x",
                },
            ]
        }
    }


def _client_con_handler(handler) -> BraveSearch:
    """Construye un BraveSearch con un httpx.MockTransport inyectado.

    Truco: monkey-patch httpx.AsyncClient para que use el transport mock.
    Como BraveSearch instancia AsyncClient internamente, parcheamos el
    constructor en el test.
    """
    return BraveSearch(api_key="test-key")


async def test_brave_parsing_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock httpx con una respuesta Brave realista. Validamos parsing."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Subscription-Token") == "test-key"
        assert request.url.path == "/res/v1/web/search"
        assert request.url.params.get("q") == "presupuestos aragón"
        return httpx.Response(200, json=_respuesta_brave_ok())

    transport = httpx.MockTransport(handler)
    orig_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return orig_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    client = BraveSearch(api_key="test-key")
    resultados = await client.buscar("presupuestos aragón", max_results=10)

    assert len(resultados) == 2  # el item sin url se descarta
    assert resultados[0]["url"] == "https://aragondigital.es/articulo-uno"
    assert resultados[0]["titulo"] == "Artículo uno"
    assert resultados[0]["contenido_md"] == "Resumen del artículo uno sobre presupuestos."
    assert resultados[0]["dominio"] == "aragondigital.es"
    assert resultados[0]["paywall"] is False
    assert resultados[1]["dominio"] == "europapress.es"


async def test_brave_sin_api_key_lanza() -> None:
    client = BraveSearch(api_key="")
    with pytest.raises(RuntimeError, match="BRAVE_SEARCH_API_KEY"):
        await client.buscar("q")


async def test_brave_count_capado_a_20(monkeypatch: pytest.MonkeyPatch) -> None:
    """Brave acepta count 1..20; pedir 50 debe traducirse a 20."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["count"] = request.url.params.get("count")
        return httpx.Response(200, json={"web": {"results": []}})

    transport = httpx.MockTransport(handler)
    orig_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return orig_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    client = BraveSearch(api_key="test-key")
    await client.buscar("q", max_results=50)
    assert captured["count"] == "20"


async def test_brave_respuesta_vacia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Respuesta sin clave `web` no rompe el parser."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    orig_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return orig_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    client = BraveSearch(api_key="test-key")
    assert await client.buscar("q") == []


def test_dominio_de_normaliza_www() -> None:
    assert _dominio_de("https://www.aragondigital.es/x") == "aragondigital.es"
    assert _dominio_de("https://EUROPAPRESS.ES/y") == "europapress.es"
    assert _dominio_de("not-a-url") is None


def test_brave_ok_payload_es_json() -> None:
    """Sanity: el payload de fixture es JSON serializable."""
    assert json.loads(json.dumps(_respuesta_brave_ok()))
