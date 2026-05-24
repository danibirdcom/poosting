"""Fakes deterministas para los Protocols de PipelineDeps.

Cada test puede:
- Construir un fake con scripted responses (``FakeLLM(["resp1", "resp2"])``).
- O sobrescribir métodos puntuales con monkeypatch.

Las llamadas se contabilizan en ``.llamadas`` para asserts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeLLM:
    """Cliente LLM con cola de respuestas predeterminadas.

    Cada llamada a ``generar`` consume el siguiente elemento. Si la cola
    se agota, devuelve "" (vacío) — los nodos deben tolerarlo.
    """

    respuestas: list[str] = field(default_factory=list)
    llamadas: list[dict[str, Any]] = field(default_factory=list)

    async def generar(self, prompt: str, modelo: str, **kwargs: object) -> str:
        self.llamadas.append({"prompt": prompt, "modelo": modelo, **kwargs})
        if not self.respuestas:
            return ""
        return self.respuestas.pop(0)


@dataclass
class FakeSearch:
    resultados: list[dict[str, Any]] = field(default_factory=list)
    llamadas: list[dict[str, Any]] = field(default_factory=list)

    async def buscar(self, query: str, max_results: int = 10) -> list[dict]:
        self.llamadas.append({"query": query, "max_results": max_results})
        return list(self.resultados)


@dataclass
class FakeImageBank:
    imagen: dict[str, Any] | None = None
    llamadas: list[str] = field(default_factory=list)

    async def buscar_imagen(self, query: str) -> dict | None:
        self.llamadas.append(query)
        return self.imagen


def fuente_falsa(
    url: str,
    titulo: str = "",
    paywall: bool = False,
    dominio: str | None = None,
) -> dict[str, Any]:
    """Construye un resultado de search con campos esperados por research."""
    return {
        "url": url,
        "titulo": titulo or f"Titulo de {url}",
        "publicado_at": "2026-05-24T10:00:00Z",
        "autoridad_score": 0.8,
        "contenido_md": f"Contenido de {url}",
        "dominio": dominio or url.split("/")[2] if "//" in url else None,
        "paywall": paywall,
    }
