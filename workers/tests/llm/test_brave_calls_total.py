"""Tests del contador ``calls_total`` en BraveSearch (bug F de cierre v2).

Coherente con VoyageEmbeddings/ClaudeReal/GeminiReal/PexelsClient: el
smoke script lee este atributo para reportar uso.
"""

from __future__ import annotations

import httpx
import pytest

from src.llm.brave import BraveSearch


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def test_brave_calls_total_inicializa_en_cero() -> None:
    client = BraveSearch(api_key="test-key")
    assert hasattr(client, "calls_total")
    assert client.calls_total == 0


async def test_brave_calls_total_incrementa(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://example.com/x",
                            "title": "Tema",
                            "description": "snippet",
                        }
                    ]
                }
            },
        )

    _patch_httpx(monkeypatch, handler)
    client = BraveSearch(api_key="test-key")
    await client.buscar("q1")
    await client.buscar("q2")
    assert client.calls_total == 2


async def test_brave_calls_total_no_incrementa_si_falla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4xx no-retryable → no se cuenta como llamada exitosa."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad")

    _patch_httpx(monkeypatch, handler)
    client = BraveSearch(api_key="test-key")
    with pytest.raises(httpx.HTTPStatusError):
        await client.buscar("q")
    assert client.calls_total == 0


async def test_brave_calls_total_no_incrementa_sin_api_key() -> None:
    client = BraveSearch(api_key="")
    with pytest.raises(RuntimeError, match="BRAVE_SEARCH_API_KEY"):
        await client.buscar("q")
    assert client.calls_total == 0
