"""Tests del contador ``calls_total`` en VoyageEmbeddings (bug 1 de cierre).

Antes de PR cierre: el atributo no existía → smoke_redactar_end_to_end.py
petaba con AttributeError. Ahora coherente con ClaudeReal/GeminiReal/Pexels.
"""

from __future__ import annotations

import httpx
import pytest

from src.llm.embeddings import VoyageEmbeddings


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def test_voyage_calls_total_inicializa_en_cero() -> None:
    client = VoyageEmbeddings(api_key="test-key")
    assert hasattr(client, "calls_total")
    assert hasattr(client, "tokens_in_total")
    assert client.calls_total == 0
    assert client.tokens_in_total == 0


async def test_voyage_calls_total_incrementa_en_cada_llamada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1] * 1024, "index": 0},
                ],
                "usage": {"total_tokens": 7},
            },
        )

    _patch_httpx(monkeypatch, handler)
    client = VoyageEmbeddings(api_key="test-key")
    assert client.calls_total == 0
    assert client.tokens_in_total == 0

    await client.embed(["texto 1"])
    assert client.calls_total == 1
    assert client.tokens_in_total == 7

    await client.embed(["texto 2"])
    assert client.calls_total == 2
    assert client.tokens_in_total == 14


async def test_voyage_tokens_in_total_tolera_respuesta_sin_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la respuesta no trae 'usage', tokens_in_total queda en 0 pero la
    llamada cuenta como exitosa.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1] * 1024, "index": 0}]},
        )

    _patch_httpx(monkeypatch, handler)
    client = VoyageEmbeddings(api_key="test-key")
    await client.embed(["x"])
    assert client.calls_total == 1
    assert client.tokens_in_total == 0


async def test_voyage_calls_total_no_incrementa_con_textos_vacios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``embed([])`` devuelve [] sin llamar a la API → no cuenta."""
    client = VoyageEmbeddings(api_key="test-key")
    await client.embed([])
    assert client.calls_total == 0


async def test_voyage_calls_total_no_incrementa_si_falla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la API devuelve 400 (no retryable), el contador NO se incrementa
    (el error se propaga sin contar la llamada como exitosa)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    _patch_httpx(monkeypatch, handler)
    client = VoyageEmbeddings(api_key="test-key")
    with pytest.raises(httpx.HTTPStatusError):
        await client.embed(["x"])
    assert client.calls_total == 0
