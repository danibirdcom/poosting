"""Smoke test manual de detect + research contra staging real.

Uso:
    uv run python -m scripts.smoke_detect_research \
        --senal-id <UUID> \
        --medio-id <UUID>

Variables de entorno requeridas:
    DATABASE_URL_STAGING   DSN a la BD de staging (asyncpg)
    ANTHROPIC_API_KEY      Para Claude Haiku (detect classification, NER)
    GEMINI_API_KEY         Para Gemini 2.5 Flash (síntesis de hechos)
    BRAVE_SEARCH_API_KEY   Para Brave Web Search
    VOYAGE_API_KEY         Para Voyage (fallback si la señal no trae embedding)

Pinning de modelos (opcional; defaults en src/llm/config.py):
    CLAUDE_HAIKU_MODEL, GEMINI_MODEL

NO commitea, NO inserta nada. Solo ejecuta detect y research y
imprime el state final con pretty-print JSON.

Si peta, captura traceback completo y exit code != 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from typing import Any
from uuid import UUID

import anthropic
import asyncpg
import structlog
from google import genai

from src.llm.brave import BraveSearch
from src.llm.config import CLAUDE_HAIKU_MODEL, GEMINI_MODEL
from src.llm.embeddings import VoyageEmbeddings
from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.nodes.detect import detect_node
from src.pipeline.nodes.research import research_node
from src.pipeline.state import PipelineState
from src.trends.persistence import _init_conn

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Clientes reales (no mocks)
# ---------------------------------------------------------------------------
class AnthropicReal:
    """Wrapper minimal del SDK Anthropic que satisface el Protocol LLMClient.

    Solo se usa en este smoke test — el pipeline live mantendrá su propio
    wrapper más completo cuando se integre.
    """

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generar(self, prompt: str, modelo: str, **kwargs: Any) -> str:
        max_tokens = int(kwargs.get("max_tokens", 2048))
        msg = await self._client.messages.create(
            model=modelo,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        partes = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
        return "".join(partes)


class GeminiReal:
    """Wrapper minimal del SDK google-genai."""

    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def generar(self, prompt: str, modelo: str, **kwargs: Any) -> str:
        resp = await self._client.aio.models.generate_content(
            model=modelo, contents=prompt
        )
        return resp.text or ""


class _NoImageBank:
    """Stub: research no usa imágenes. Solo para llenar PipelineDeps."""

    async def buscar_imagen(self, query: str) -> dict | None:  # noqa: ARG002
        return None


# ---------------------------------------------------------------------------
# Pretty print
# ---------------------------------------------------------------------------
def pretty(obj: object) -> str:
    """JSON con UUIDs, datetimes y vectores serializables."""
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str, sort_keys=False)


def _redactar_state(state: dict) -> dict:
    """Recorta campos verbose para que el log sea legible."""
    out = dict(state)
    fuentes = out.get("fuentes") or []
    out["fuentes"] = [
        {
            **f,
            "contenido_md": (
                (f.get("contenido_md") or "")[:200] + "…"
                if f.get("contenido_md") and len(f.get("contenido_md") or "") > 200
                else f.get("contenido_md")
            ),
        }
        for f in fuentes
    ]
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run(senal_id: UUID, medio_id: UUID) -> int:
    requeridas = {
        "DATABASE_URL_STAGING": os.environ.get("DATABASE_URL_STAGING", ""),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "BRAVE_SEARCH_API_KEY": os.environ.get("BRAVE_SEARCH_API_KEY", ""),
        "VOYAGE_API_KEY": os.environ.get("VOYAGE_API_KEY", ""),
    }
    faltantes = [k for k, v in requeridas.items() if not v]
    if faltantes:
        print(f"ERROR: env vars sin definir: {', '.join(faltantes)}", file=sys.stderr)
        return 2

    dsn = requeridas["DATABASE_URL_STAGING"]
    pool = await asyncpg.create_pool(
        dsn=dsn, min_size=1, max_size=3, command_timeout=30, init=_init_conn
    )
    try:
        deps = PipelineDeps(
            pool=pool,
            claude=AnthropicReal(requeridas["ANTHROPIC_API_KEY"]),
            gemini=GeminiReal(requeridas["GEMINI_API_KEY"]),
            search=BraveSearch(api_key=requeridas["BRAVE_SEARCH_API_KEY"]),
            images=_NoImageBank(),
            embeddings=VoyageEmbeddings(api_key=requeridas["VOYAGE_API_KEY"]),
        )

        print("=" * 72)
        print("MODELOS PINNEADOS")
        print("=" * 72)
        print(f"  claude_haiku: {CLAUDE_HAIKU_MODEL}")
        print(f"  gemini:       {GEMINI_MODEL}")
        print()

        state_inicial: PipelineState = {
            "medio_id": medio_id,
            "run_id": UUID("00000000-0000-0000-0000-000000000000"),  # smoke; no se persiste
            "trigger_tipo": "manual",
            "senal_id": senal_id,
        }

        print("=" * 72)
        print("DETECT")
        print("=" * 72)
        state_post_detect = await detect_node(state_inicial, deps)
        print(pretty(_redactar_state(dict(state_post_detect))))
        print()

        if state_post_detect.get("detect_motivo_aborto"):
            print(
                f"detect abortó ({state_post_detect['detect_motivo_aborto']}); "
                "no se ejecuta research.",
                file=sys.stderr,
            )
            return 1

        print("=" * 72)
        print("RESEARCH")
        print("=" * 72)
        state_post_research = await research_node(state_post_detect, deps)
        print(pretty(_redactar_state(dict(state_post_research))))
        print()

        if state_post_research.get("research_motivo_aborto"):
            print(
                f"research abortó: {state_post_research['research_motivo_aborto']}",
                file=sys.stderr,
            )
            return 1

        print("OK — detect + research completados sin abort.")
        return 0
    finally:
        await pool.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--senal-id", required=True, help="UUID de la señal a procesar")
    parser.add_argument("--medio-id", required=True, help="UUID del medio (tenant)")
    args = parser.parse_args()

    try:
        senal_id = UUID(args.senal_id)
        medio_id = UUID(args.medio_id)
    except ValueError as err:
        print(f"ERROR: UUID inválido: {err}", file=sys.stderr)
        return 2

    try:
        return asyncio.run(run(senal_id, medio_id))
    except Exception:
        print("ERROR — traceback completo:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
