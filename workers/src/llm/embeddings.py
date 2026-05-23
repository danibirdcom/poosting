"""Cliente de embeddings (Voyage AI por defecto).

Usa ``voyage-3-large`` (1024 dims) — coincide con las columnas ``vector(1024)``
del esquema. La interfaz ``EmbeddingsClient`` está aislada para poder mockear
en tests sin pegar a la API real.
"""

from __future__ import annotations

import os
from typing import Literal, Protocol

import httpx
import structlog

logger = structlog.get_logger(__name__)


InputType = Literal["document", "query"]


class EmbeddingsClient(Protocol):
    async def embed(
        self, textos: list[str], input_type: InputType = "document"
    ) -> list[list[float]]: ...


class VoyageEmbeddings:
    """Cliente HTTP de Voyage AI.

    Doc: https://docs.voyageai.com/reference/embeddings-api
    """

    BASE_URL = "https://api.voyageai.com/v1/embeddings"
    MODEL = "voyage-3-large"
    DIMS = 1024

    def __init__(self, api_key: str | None = None, timeout_s: float = 20.0) -> None:
        self._api_key = api_key or os.environ.get("VOYAGE_API_KEY", "")
        self._timeout_s = timeout_s

    async def embed(
        self, textos: list[str], input_type: InputType = "document"
    ) -> list[list[float]]:
        if not textos:
            return []
        if not self._api_key:
            raise RuntimeError("VOYAGE_API_KEY no configurada")

        payload = {
            "input": textos,
            "model": self.MODEL,
            "input_type": input_type,
            "output_dimension": self.DIMS,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return [item["embedding"] for item in data["data"]]
