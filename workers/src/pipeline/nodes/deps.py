"""Dependencias inyectadas a los nodos del pipeline.

Tener un único ``PipelineDeps`` evita pasar 5 argumentos a cada nodo y
facilita el mockeo en tests: en producción se construye con clientes
reales (asyncpg pool, httpx, Anthropic, Gemini, Voyage, Pexels); en tests
se sustituyen por mocks que implementan los mismos Protocols.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import asyncpg


class LLMClient(Protocol):
    """Protocolo común para clientes de Claude / Gemini.

    El test usa un mock que implementa esto. Las implementaciones reales
    viven en ``workers/src/llm/`` y se añaden en PR B.
    """

    async def generar(self, prompt: str, modelo: str, **kwargs: object) -> str: ...


class SearchClient(Protocol):
    """Para Brave Search. Implementación real en PR B."""

    async def buscar(self, query: str, max_results: int = 10) -> list[dict]: ...


class ImageBankClient(Protocol):
    """Para Pexels / Unsplash. Implementación real en PR B."""

    async def buscar_imagen(self, query: str) -> dict | None: ...


@dataclass
class PipelineDeps:
    """Bundle de clientes inyectados al pipeline."""

    pool: asyncpg.Pool
    claude: LLMClient
    gemini: LLMClient
    search: SearchClient
    images: ImageBankClient
