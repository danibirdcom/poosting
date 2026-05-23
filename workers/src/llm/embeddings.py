"""Cliente de embeddings (Voyage AI por defecto).

Usa ``voyage-3-large`` (1024 dims) — coincide con las columnas ``vector(1024)``
del esquema. La interfaz ``EmbeddingsClient`` está aislada para poder mockear
en tests sin pegar a la API real.

Retry exponencial en 429 y 5xx vía ``tenacity``:
- 3 intentos máximo.
- Esperas 2s, 4s entre intentos (cap a 8s).
- 4xx que no sean 429 NO se reintentan (no es transitorio).
"""

from __future__ import annotations

import os
from typing import Literal, Protocol

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)


InputType = Literal["document", "query"]


def _es_retryable(exc: BaseException) -> bool:
    """429 y 5xx son transitorios; el resto NO se reintenta."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    # Errores de red transitorios también
    return isinstance(exc, httpx.TransportError | httpx.TimeoutException)


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

        return await self._embed_with_retry(textos, input_type)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception(_es_retryable),
        reraise=True,
    )
    async def _embed_with_retry(
        self, textos: list[str], input_type: InputType
    ) -> list[list[float]]:
        payload = {
            "input": textos,
            "model": self.MODEL,
            "input_type": input_type,
            "output_dimension": self.DIMS,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning(
                    "voyage_retry", status=resp.status_code, n_textos=len(textos)
                )
                resp.raise_for_status()  # dispara HTTPStatusError → retry
            resp.raise_for_status()
            data = resp.json()
        return [item["embedding"] for item in data["data"]]
