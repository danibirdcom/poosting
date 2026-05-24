"""Cliente real de Google Gemini (2.5 Flash por defecto) con grounding.

Soporte para tool ``google_search`` (grounding nativo) cuando se pasa
``grounding=True`` en ``generar()``. El nodo ``research`` lo activa para que
el modelo cite fuentes verificables al sintetizar hechos.

Implementa el Protocol ``LLMClient`` extendido (mismo `generar` que Claude,
con kwargs adicionales). Acumula uso para el CLI redactar.

Retry exponencial en 429/5xx vía ``tenacity``. Log estructurado por llamada.
"""

from __future__ import annotations

import os
import time
from typing import Any

import structlog
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)


def _es_retryable(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        if code is None:
            return False
        return code == 429 or code >= 500
    return False


class GeminiReal:
    """Cliente HTTP de Gemini con retry + tracking + grounding opcional."""

    def __init__(self, api_key: str | None = None) -> None:
        api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY no configurada (o pasada al constructor)"
            )
        self._client = genai.Client(api_key=api_key)

        # Acumuladores leídos por el CLI para reportar coste.
        self.tokens_in_total: int = 0
        self.tokens_out_total: int = 0
        self.calls_total: int = 0
        self.tokens_in_por_modelo: dict[str, int] = {}
        self.tokens_out_por_modelo: dict[str, int] = {}
        # Citas de grounding agregadas (todas las llamadas).
        self.citas_grounding: list[dict[str, Any]] = []

    async def generar(self, prompt: str, modelo: str, **kwargs: Any) -> str:
        """``kwargs`` reconocidos:

        - ``grounding`` (bool): si True, añade tool google_search.
        - ``temperature`` (float): default 0.4.
        - ``system_instruction`` (str): instrucción de sistema.
        """
        return await self._generar_con_retry(prompt, modelo, kwargs)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception(_es_retryable),
        reraise=True,
    )
    async def _generar_con_retry(
        self, prompt: str, modelo: str, kwargs: dict[str, Any]
    ) -> str:
        grounding = bool(kwargs.get("grounding", False))
        temperature = float(kwargs.get("temperature", 0.4))
        system_instruction = kwargs.get("system_instruction")

        config_kwargs: dict[str, Any] = {"temperature": temperature}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if grounding:
            # google_search es el tool de grounding nativo de Gemini.
            config_kwargs["tools"] = [
                genai_types.Tool(google_search=genai_types.GoogleSearch())
            ]

        config = genai_types.GenerateContentConfig(**config_kwargs)

        t0 = time.monotonic()
        try:
            resp = await self._client.aio.models.generate_content(
                model=modelo, contents=prompt, config=config
            )
        except genai_errors.APIError as err:
            code = getattr(err, "code", None)
            if code is not None and (code == 429 or code >= 500):
                logger.warning(
                    "gemini_retry", code=code, modelo=modelo, error=str(err)[:200]
                )
            raise

        duracion_ms = int((time.monotonic() - t0) * 1000)
        usage = getattr(resp, "usage_metadata", None)
        tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)
        tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0)
        self.tokens_in_total += tokens_in
        self.tokens_out_total += tokens_out
        self.calls_total += 1
        self.tokens_in_por_modelo[modelo] = (
            self.tokens_in_por_modelo.get(modelo, 0) + tokens_in
        )
        self.tokens_out_por_modelo[modelo] = (
            self.tokens_out_por_modelo.get(modelo, 0) + tokens_out
        )

        # Extraer citas de grounding si vinieron.
        citas = _extraer_citas(resp)
        if citas:
            self.citas_grounding.extend(citas)

        texto = resp.text or ""
        logger.info(
            "gemini_ok",
            modelo=modelo,
            grounding=grounding,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duracion_ms=duracion_ms,
            n_citas=len(citas),
            preview=texto[:120].replace("\n", " "),
        )
        return texto


def _extraer_citas(resp: Any) -> list[dict[str, Any]]:
    """Devuelve lista de ``{url, titulo}`` desde ``grounding_metadata``.

    Tolerante a ausencia de campos — Gemini devuelve ``grounding_metadata``
    solo cuando hay grounding activo y resultó en consultas.
    """
    out: list[dict[str, Any]] = []
    try:
        candidates = resp.candidates or []
        for c in candidates:
            meta = getattr(c, "grounding_metadata", None)
            if meta is None:
                continue
            chunks = getattr(meta, "grounding_chunks", None) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                if web is None:
                    continue
                out.append(
                    {
                        "url": getattr(web, "uri", None),
                        "titulo": getattr(web, "title", None),
                    }
                )
    except (AttributeError, TypeError):
        return out
    return out
