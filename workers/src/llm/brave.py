"""Cliente Brave Search API.

Doc: https://api.search.brave.com/app/documentation/web-search/get-started

Endpoint usado: ``GET /res/v1/web/search`` con ``X-Subscription-Token``.
Devuelve una lista de dicts compatibles con el Protocol ``SearchClient`` de
``pipeline/nodes/deps.py``:

    {
      "url": str,
      "titulo": str | None,
      "publicado_at": str | None,
      "contenido_md": str | None,        # description/snippet de Brave
      "dominio": str | None,
      "autoridad_score": float | None,   # rellena el nodo research, no Brave
      "paywall": False,                  # Brave no lo sabe; research filtra
    }

Retry exponencial vía ``tenacity`` en 429 y 5xx (mismo patrón que Voyage).
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)

BASE_URL = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_TIMEOUT_S = 15.0


def _es_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, httpx.TransportError | httpx.TimeoutException)


def _dominio_de(url: str) -> str | None:
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


class BraveSearch:
    """Wrapper HTTP de Brave Search Web API.

    Se construye en producción con ``BRAVE_SEARCH_API_KEY`` desde env;
    en tests se sustituye por ``FakeSearch`` que implementa el mismo
    Protocol.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        country: str = "ES",
        search_lang: str = "es",
    ) -> None:
        self._api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY", "")
        self._timeout_s = timeout_s
        self._country = country
        self._search_lang = search_lang
        # Coherente con ClaudeReal/GeminiReal/PexelsClient/VoyageEmbeddings:
        # el smoke script y el CLI leen este contador para reportar uso.
        # Se incrementa una vez por llamada exitosa (no por reintento).
        self.calls_total: int = 0

    async def buscar(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        if not self._api_key:
            raise RuntimeError(
                "BRAVE_SEARCH_API_KEY no configurada. Setea la env var o inyecta un mock en tests."
            )
        resultados = await self._buscar_with_retry(query, max_results)
        # Solo cuenta en éxito (mismo criterio que Voyage).
        self.calls_total += 1
        return resultados

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception(_es_retryable),
        reraise=True,
    )
    async def _buscar_with_retry(self, query: str, max_results: int) -> list[dict[str, Any]]:
        headers = {
            "X-Subscription-Token": self._api_key,
            "Accept": "application/json",
        }
        # Brave: count 1..20; pedimos lo que pide el caller capado a 20.
        params: dict[str, Any] = {
            "q": query,
            "count": max(1, min(max_results, 20)),
            "country": self._country,
            "search_lang": self._search_lang,
            "safesearch": "moderate",
        }
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            resp = await client.get(BASE_URL, headers=headers, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning("brave_retry", status=resp.status_code, q=query[:60])
                resp.raise_for_status()
            resp.raise_for_status()
            data = resp.json()

        web = (data or {}).get("web") or {}
        results = web.get("results") or []
        out: list[dict[str, Any]] = []
        for r in results:
            url = r.get("url")
            if not url:
                continue
            out.append(
                {
                    "url": url,
                    "titulo": r.get("title"),
                    "publicado_at": r.get("age") or r.get("page_age"),
                    "contenido_md": r.get("description"),
                    "dominio": _dominio_de(url),
                    "autoridad_score": None,
                    "paywall": False,
                }
            )
        logger.info("brave_ok", q=query[:60], n_resultados=len(out))
        return out


async def fetch_url_content(
    url: str,
    timeout_s: float = 10.0,
    max_bytes: int = 500_000,
    user_agent: str = "Mozilla/5.0 (compatible; RedactiaBot/1.0; +https://redactia.local)",
) -> str | None:
    """Descarga el contenido de una URL con timeout y User-Agent realista.

    Devuelve el cuerpo de la respuesta (texto) o ``None`` si falla. NO lanza
    excepciones — los errores se loguean y el caller decide qué hacer con la
    fuente. Se corta a ``max_bytes`` para evitar OOM con páginas gigantes.
    """
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            body = resp.text[:max_bytes]
            return body
    except (httpx.HTTPError, httpx.InvalidURL) as err:
        logger.warning("fetch_url_fallido", url=url[:120], error=str(err)[:200])
        return None
