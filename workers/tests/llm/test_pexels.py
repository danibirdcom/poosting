"""Tests del cliente PexelsClient con MockTransport (sin red real)."""

from __future__ import annotations

import httpx
import pytest

from src.llm.pexels import PexelsClient


def _resp_pexels_ok() -> dict:
    return {
        "total_results": 100,
        "photos": [
            {
                "id": 12345,
                "url": "https://www.pexels.com/photo/12345/",
                "photographer": "Ada Lovelace",
                "photographer_url": "https://www.pexels.com/@ada",
                "alt": "Un jardín en Zaragoza",
                "width": 1920,
                "height": 1080,
                "src": {
                    "landscape": "https://images.pexels.com/photos/12345/x_landscape.jpg",
                    "large": "https://images.pexels.com/photos/12345/x_large.jpg",
                },
            }
        ],
    }


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


async def test_pexels_buscar_imagen_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "test-key"
        assert request.url.params.get("query") == "Zaragoza flores"
        assert request.url.params.get("orientation") == "landscape"
        return httpx.Response(200, json=_resp_pexels_ok())

    _patch_httpx(monkeypatch, handler)
    client = PexelsClient(api_key="test-key")
    out = await client.buscar_imagen("Zaragoza flores")
    assert out is not None
    assert out["url"] == "https://images.pexels.com/photos/12345/x_landscape.jpg"
    assert out["foto_id"] == "12345"
    assert out["fotografo"] == "Ada Lovelace"
    assert out["alt_texto"] == "Un jardín en Zaragoza"
    assert client.calls_total == 1


async def test_pexels_sin_resultados_devuelve_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"photos": [], "total_results": 0})

    _patch_httpx(monkeypatch, handler)
    client = PexelsClient(api_key="test-key")
    out = await client.buscar_imagen("xyz")
    assert out is None


async def test_pexels_500_persistente_devuelve_none_no_lanza(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    _patch_httpx(monkeypatch, handler)
    client = PexelsClient(api_key="test-key")
    # No queremos que el pipeline aborte por un fallo de Pexels.
    out = await client.buscar_imagen("xyz")
    assert out is None


def test_pexels_sin_api_key_lanza() -> None:
    with pytest.raises(RuntimeError, match="PEXELS_API_KEY"):
        PexelsClient(api_key="")
