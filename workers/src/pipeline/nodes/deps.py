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

    Kwargs reconocidos por el cliente real (no todos los implementa cada
    proveedor — los desconocidos se ignoran):

    - ``system`` / ``system_instruction`` (str): system prompt.
    - ``max_tokens`` (int): cap de tokens de salida.
    - ``temperature`` (float).
    - ``prefill`` (str): solo Claude — prefill del mensaje assistant para
      forzar formato (ej. ``"{"`` para JSON estricto).
    - ``grounding`` (bool): solo Gemini — activa la tool ``google_search``
      para que el modelo cite fuentes verificables. Usado por ``research``
      al sintetizar hechos.

    Los clientes reales (``ClaudeReal`` / ``GeminiReal``) exponen además
    ``tokens_in_total``, ``tokens_out_total``, ``calls_total`` y un breakdown
    ``*_por_modelo`` que el CLI ``redactar`` lee para calcular coste.
    """

    async def generar(self, prompt: str, modelo: str, **kwargs: object) -> str: ...


class SearchClient(Protocol):
    """Para Brave Search. Implementación real en PR B."""

    async def buscar(self, query: str, max_results: int = 10) -> list[dict]: ...


class ImageBankClient(Protocol):
    """Para Pexels / Unsplash. Implementación real en PR B."""

    async def buscar_imagen(self, query: str) -> dict | None: ...


class EmbeddingsClient(Protocol):
    """Embeddings de Voyage (o equivalente). Usado por ``detect`` para el
    check de canibalización semántica contra ``drafts.embedding``.
    """

    async def embed(
        self, textos: list[str], input_type: str = "document"
    ) -> list[list[float]]: ...


@dataclass
class PipelineDeps:
    """Bundle de clientes inyectados al pipeline."""

    pool: asyncpg.Pool
    claude: LLMClient
    gemini: LLMClient
    search: SearchClient
    images: ImageBankClient
    # Opcional: detect lo necesita para canibalización semántica. Si no se
    # pasa, detect cae a chequeo solo por ``drafts.senal_id`` exacto.
    embeddings: EmbeddingsClient | None = None
