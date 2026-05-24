"""Cliente real de Anthropic Claude (Sonnet + Haiku).

Implementa el Protocol ``LLMClient`` (``async generar(prompt, modelo, **kwargs) -> str``).
Acumula uso en ``tokens_in_total`` / ``tokens_out_total`` / ``calls_total``
para que el CLI ``redactar`` calcule coste estimado al final.

Retry exponencial en 429/5xx vía ``tenacity`` (mismo patrón que VoyageEmbeddings
y BraveSearch). Log estructurado por llamada con tokens, modelo y duración.

Helper ``json_output_kwargs``: añade ``response_format`` style mediante
prefill del primer mensaje (Claude no tiene response_format JSON nativo, pero
prefill con "{" fuerza al modelo a continuar el JSON sin texto extra).
"""

from __future__ import annotations

import os
import time
from typing import Any

import anthropic
import structlog
from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
)
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)


def _es_retryable(exc: BaseException) -> bool:
    """429 y 5xx son transitorios. 4xx (auth, schema) NO se reintentan."""
    if isinstance(exc, APIStatusError):
        code = exc.status_code
        return code == 429 or code >= 500
    return isinstance(exc, APIConnectionError | APITimeoutError)


class ClaudeReal:
    """Cliente HTTP de Anthropic con retry + tracking de coste."""

    def __init__(
        self,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        max_tokens_default: int = 4096,
    ) -> None:
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY no configurada (o pasada al constructor)"
            )
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_s)
        self._max_tokens_default = max_tokens_default

        # Acumuladores que el CLI lee al final para reportar coste.
        self.tokens_in_total: int = 0
        self.tokens_out_total: int = 0
        self.calls_total: int = 0
        # Tracking por-modelo (Sonnet y Haiku se tarifican distinto).
        self.tokens_in_por_modelo: dict[str, int] = {}
        self.tokens_out_por_modelo: dict[str, int] = {}

    async def generar(self, prompt: str, modelo: str, **kwargs: Any) -> str:
        """``prompt``: contenido del único mensaje user.

        kwargs reconocidos:
        - ``system``: system prompt (str).
        - ``max_tokens``: int (default 4096).
        - ``prefill``: str inicial para el mensaje assistant (útil para forzar
          JSON: prefill="{" + parse el resultado como "{" + respuesta).
        - ``temperature``: float (default 0.7).
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
        system = kwargs.get("system")
        max_tokens = int(kwargs.get("max_tokens", self._max_tokens_default))
        temperature = float(kwargs.get("temperature", 0.7))
        prefill = kwargs.get("prefill")

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        if prefill:
            messages.append({"role": "assistant", "content": prefill})

        request_kwargs: dict[str, Any] = {
            "model": modelo,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            request_kwargs["system"] = system

        t0 = time.monotonic()
        try:
            resp = await self._client.messages.create(**request_kwargs)
        except APIStatusError as err:
            if err.status_code == 429 or err.status_code >= 500:
                logger.warning(
                    "claude_retry",
                    status=err.status_code,
                    modelo=modelo,
                    error=str(err)[:200],
                )
            raise

        duracion_ms = int((time.monotonic() - t0) * 1000)
        tokens_in = resp.usage.input_tokens
        tokens_out = resp.usage.output_tokens
        self.tokens_in_total += tokens_in
        self.tokens_out_total += tokens_out
        self.calls_total += 1
        self.tokens_in_por_modelo[modelo] = (
            self.tokens_in_por_modelo.get(modelo, 0) + tokens_in
        )
        self.tokens_out_por_modelo[modelo] = (
            self.tokens_out_por_modelo.get(modelo, 0) + tokens_out
        )

        partes = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        texto = "".join(partes)
        if prefill:
            texto = prefill + texto

        logger.info(
            "claude_ok",
            modelo=modelo,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duracion_ms=duracion_ms,
            preview=texto[:120].replace("\n", " "),
        )
        return texto


def json_output_kwargs(extra_system: str = "") -> dict[str, Any]:
    """Helper para pedir JSON estricto a Claude.

    Uso::

        raw = await claude.generar(prompt, modelo=..., **json_output_kwargs())
        data = json.loads(raw)

    Devuelve kwargs con ``system`` que pide JSON puro y ``prefill="{"`` para
    forzar al modelo a continuar el JSON. La salida final ya empieza por ``{``.
    """
    base = (
        "Responde EXCLUSIVAMENTE con un objeto JSON válido, sin texto antes "
        "ni después, sin markdown, sin bloques de código. Empieza por { y "
        "termina por }."
    )
    system = f"{extra_system}\n{base}" if extra_system else base
    return {"system": system, "prefill": "{", "temperature": 0.3}
