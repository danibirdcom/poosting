"""Cliente de Pexels (banco de imágenes con licencia).

Endpoint: ``GET https://api.pexels.com/v1/search``.
Doc: https://www.pexels.com/api/documentation/

Política de imagen (CLAUDE.md §6.1): banco con licencia es la opción
preferente para fotorrealismo. No genera imágenes IA. Devuelve URL con
licencia + atribución que el enrich puede insertar en ``imagenes_articulo``.

Retry exponencial en 429/5xx (mismo patrón que Brave/Voyage).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)

BASE_URL = "https://api.pexels.com/v1/search"
TIMEOUT_S = 15.0


def _es_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, httpx.TransportError | httpx.TimeoutException)


class PexelsClient:
    """Cliente HTTP de Pexels Search.

    Implementa el Protocol ``ImageBankClient`` (``async buscar_imagen(query)``).
    Acumula ``calls_total`` para el reporte de coste del CLI (Pexels es gratis,
    pero registramos llamadas).
    """

    def __init__(self, api_key: str | None = None) -> None:
        api_key = api_key or os.environ.get("PEXELS_API_KEY", "")
        if not api_key:
            raise RuntimeError("PEXELS_API_KEY no configurada")
        self._api_key = api_key
        self.calls_total: int = 0

    async def buscar_imagen(self, query: str) -> dict[str, Any] | None:
        """Devuelve la imagen mejor rankeada por Pexels para la query.

        Estructura: ``{url, foto_id, fotografo, fotografo_url, alt_texto,
        ancho, alto, src_landscape}``. ``None`` si no hay resultados.

        Orientación landscape y tamaño large (preferentes para imagen
        destacada en artículos).
        """
        try:
            return await self._buscar_with_retry(query)
        except httpx.HTTPError as err:
            logger.warning("pexels_fallo", error=str(err)[:200], query=query[:80])
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception(_es_retryable),
        reraise=True,
    )
    async def _buscar_with_retry(self, query: str) -> dict[str, Any] | None:
        headers = {"Authorization": self._api_key}
        params = {
            "query": query,
            "per_page": 5,
            "orientation": "landscape",
            "size": "large",
        }
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.get(BASE_URL, headers=headers, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning("pexels_retry", status=resp.status_code, query=query[:80])
                resp.raise_for_status()
            resp.raise_for_status()
            data = resp.json()
        self.calls_total += 1

        fotos = data.get("photos") or []
        if not fotos:
            logger.info("pexels_sin_resultados", query=query[:80])
            return None
        foto = fotos[0]
        src = foto.get("src") or {}
        return {
            "url": src.get("landscape") or src.get("large") or foto.get("url"),
            "foto_id": str(foto.get("id")),
            "fotografo": foto.get("photographer"),
            "fotografo_url": foto.get("photographer_url"),
            "alt_texto": foto.get("alt") or "",
            "ancho": foto.get("width"),
            "alto": foto.get("height"),
            "src_landscape": src.get("landscape"),
            "url_pexels": foto.get("url"),
        }
