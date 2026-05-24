"""Configuración de modelos LLM.

Los IDs se pinnean via env var con defaults estables a 2026-05. Para
cambiar de modelo basta con setear la env var en el workflow YAML —
no requiere redeploy de código.

Antes de la primera llamada real (modo live), ``validar_modelos()`` hace
GET al endpoint `/v1/models` de cada proveedor para confirmar que el
string responde. Si alguno no existe, lanza ``ModelosNoDisponibles`` con
el detalle exacto y pide actualización del env var.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger(__name__)


# Pinned defaults (2026-05). Sobrescribibles via env.
CLAUDE_SONNET_MODEL = os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-6")
CLAUDE_HAIKU_MODEL = os.environ.get("CLAUDE_HAIKU_MODEL", "claude-haiku-4-5-20251001")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


class ModelosNoDisponiblesError(RuntimeError):
    """Algún model id pinneado no existe en el proveedor. Levantar al inicio
    del flujo live para fallar rápido en lugar de en la primera llamada real.
    """


# Alias retro-compat para imports antiguos. Eliminar tras Fase 4.
ModelosNoDisponibles = ModelosNoDisponiblesError


@dataclass(frozen=True)
class ResultadoValidacion:
    proveedor: str
    modelo: str
    disponible: bool
    detalle: str | None = None


async def _verificar_anthropic(api_key: str, modelo: str) -> ResultadoValidacion:
    """GET https://api.anthropic.com/v1/models/{modelo}."""
    if not api_key:
        return ResultadoValidacion("anthropic", modelo, False, "ANTHROPIC_API_KEY vacía")
    url = f"https://api.anthropic.com/v1/models/{modelo}"
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 200:
        return ResultadoValidacion("anthropic", modelo, True)
    if resp.status_code == 404:
        return ResultadoValidacion(
            "anthropic", modelo, False, f"404: modelo '{modelo}' no existe en Anthropic"
        )
    return ResultadoValidacion(
        "anthropic", modelo, False, f"status {resp.status_code}: {resp.text[:120]}"
    )


async def _verificar_gemini(api_key: str, modelo: str) -> ResultadoValidacion:
    """GET https://generativelanguage.googleapis.com/v1beta/models/{modelo}."""
    if not api_key:
        return ResultadoValidacion("gemini", modelo, False, "GEMINI_API_KEY vacía")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params={"key": api_key})
    if resp.status_code == 200:
        return ResultadoValidacion("gemini", modelo, True)
    if resp.status_code == 404:
        return ResultadoValidacion(
            "gemini", modelo, False, f"404: modelo '{modelo}' no existe en Gemini"
        )
    return ResultadoValidacion(
        "gemini", modelo, False, f"status {resp.status_code}: {resp.text[:120]}"
    )


async def validar_modelos(
    anthropic_key: str | None = None,
    gemini_key: str | None = None,
) -> list[ResultadoValidacion]:
    """Verifica que los 3 modelos pinneados responden a `/v1/models`.

    Llamar al inicio del CLI live ANTES de empezar el pipeline. Si alguno
    devuelve 404, lanza ``ModelosNoDisponibles`` con detalles.

    Devuelve la lista de resultados para que el caller pueda loggearla.
    """
    anthropic_key = anthropic_key or os.environ.get("ANTHROPIC_API_KEY", "")
    gemini_key = gemini_key or os.environ.get("GEMINI_API_KEY", "")

    resultados = [
        await _verificar_anthropic(anthropic_key, CLAUDE_SONNET_MODEL),
        await _verificar_anthropic(anthropic_key, CLAUDE_HAIKU_MODEL),
        await _verificar_gemini(gemini_key, GEMINI_MODEL),
    ]

    no_disponibles = [r for r in resultados if not r.disponible]
    if no_disponibles:
        mensajes = "; ".join(
            f"{r.proveedor}/{r.modelo}: {r.detalle}" for r in no_disponibles
        )
        raise ModelosNoDisponiblesError(
            f"Modelos no disponibles: {mensajes}. "
            "Actualiza CLAUDE_SONNET_MODEL / CLAUDE_HAIKU_MODEL / GEMINI_MODEL "
            "en el entorno con el string correcto."
        )

    for r in resultados:
        logger.info("modelo_disponible", proveedor=r.proveedor, modelo=r.modelo)
    return resultados
