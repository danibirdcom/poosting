"""Smoke test manual end-to-end del pipeline B contra staging real.

Lanza los 6 nodos (detect → research → write → review → enrich → publish)
con clientes reales y vuelca:
- Estado final del state.
- Draft persistido (titulo, meta_descr, primeras 300 chars de cuerpo_md).
- JSON-LD generado.
- Imagen destacada (URL + atribución).
- Tokens consumidos + coste EUR estimado.

Uso:
    uv run python -m scripts.smoke_redactar_end_to_end \
        --senal-id <UUID> \
        --redactor-id <UUID> \
        --medio-id <UUID>

Variables de entorno requeridas:
    DATABASE_URL_STAGING   DSN asyncpg.
    ANTHROPIC_API_KEY      Sonnet + Haiku.
    GEMINI_API_KEY         Gemini con grounding.
    BRAVE_SEARCH_API_KEY   Brave Web Search.
    VOYAGE_API_KEY         Embeddings (ejemplos del redactor + canib).
    PEXELS_API_KEY         Banco con licencia (si falta, draft sin imagen).

NO está pensado para correr en CI: persiste un draft real en la BD de
staging. Cleanup manual si hace falta.

Si peta, captura traceback completo y exit != 0.
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

import asyncpg
import structlog

from src.llm.brave import BraveSearch
from src.llm.claude import ClaudeReal
from src.llm.config import (
    CLAUDE_HAIKU_MODEL,
    CLAUDE_SONNET_MODEL,
    GEMINI_MODEL,
)
from src.llm.embeddings import VoyageEmbeddings
from src.llm.gemini import GeminiReal
from src.llm.pexels import PexelsClient
from src.llm.precios import calcular_coste_eur
from src.pipeline import build_graph
from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.persistence import crear_run
from src.pipeline.state import PipelineState
from src.trends.persistence import _init_conn

logger = structlog.get_logger(__name__)


class _NoImages:
    """Fallback si PEXELS_API_KEY no está configurada."""

    calls_total: int = 0

    async def buscar_imagen(self, query: str) -> dict | None:  # noqa: ARG002
        return None


def pretty(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str, sort_keys=False)


async def run(senal_id: UUID, redactor_id: UUID, medio_id: UUID) -> int:
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
        dsn=dsn, min_size=1, max_size=3, command_timeout=60, init=_init_conn
    )
    try:
        claude = ClaudeReal()
        gemini = GeminiReal()
        embeddings = VoyageEmbeddings()
        search = BraveSearch()
        try:
            images: Any = PexelsClient()
        except RuntimeError:
            print("WARN: PEXELS_API_KEY no configurada; draft sin imagen", file=sys.stderr)
            images = _NoImages()

        deps = PipelineDeps(
            pool=pool,
            claude=claude,
            gemini=gemini,
            search=search,
            images=images,
            embeddings=embeddings,
        )

        print("=" * 72)
        print("MODELOS PINNEADOS")
        print("=" * 72)
        print(f"  claude_sonnet: {CLAUDE_SONNET_MODEL}")
        print(f"  claude_haiku:  {CLAUDE_HAIKU_MODEL}")
        print(f"  gemini:        {GEMINI_MODEL}")
        print()

        # Crear el run en BD.
        async with pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
            )
            run_id = await crear_run(
                conn,
                medio_id=medio_id,
                redactor_id=redactor_id,
                trigger_tipo="manual",
                senal_id=senal_id,
            )

        state_inicial: PipelineState = {
            "medio_id": medio_id,
            "run_id": run_id,
            "redactor_id": redactor_id,
            "trigger_tipo": "manual",
            "senal_id": senal_id,
        }

        print("=" * 72)
        print(f"LANZANDO PIPELINE — run_id={run_id}")
        print("=" * 72)
        graph = build_graph(deps)
        state_final = await graph.ainvoke(state_inicial)

        # ----- Resultado -----
        print()
        print("=" * 72)
        print("RESULTADO")
        print("=" * 72)
        estado = _estado(state_final)
        print(f"Estado: {estado}")
        draft_id = state_final.get("draft_id")
        if draft_id:
            print(f"Draft ID: {draft_id}")
            print(f"URL editor: {state_final.get('editor_url')}")
        for k in (
            "detect_motivo_aborto",
            "research_motivo_aborto",
        ):
            v = state_final.get(k)
            if v:
                print(f"{k}: {v}")
        if state_final.get("requiere_revision_humana"):
            print("Requiere revisión humana. Errores:")
            for e in state_final.get("review_errores") or []:
                print(f"  - {e}")

        # ----- Draft persistido (re-fetch desde BD) -----
        if draft_id:
            async with pool.acquire() as conn:
                await conn.execute(
                    "SELECT set_config('app.medio_actual', $1, false)",
                    str(medio_id),
                )
                row = await conn.fetchrow(
                    "SELECT titulo, meta_title, meta_descr, slug, cuerpo_md, "
                    "       schema_jsonld, imagen_destacada_id "
                    "FROM drafts WHERE id = $1",
                    draft_id,
                )
                img_row = None
                if row and row["imagen_destacada_id"]:
                    img_row = await conn.fetchrow(
                        "SELECT url_publica, alt_text, pie_foto, fuente "
                        "FROM imagenes_articulo WHERE id = $1",
                        row["imagen_destacada_id"],
                    )
                entidades_link = await conn.fetch(
                    "SELECT ec.nombre_canonico FROM draft_entidades de "
                    "JOIN entidades_catalogo ec ON ec.id = de.entidad_id "
                    "WHERE de.draft_id = $1",
                    draft_id,
                )

            print()
            print("DRAFT PERSISTIDO:")
            print(f"  titulo:     {row['titulo']}")
            print(f"  meta_title: {row['meta_title']}")
            print(f"  meta_descr: {row['meta_descr']}")
            print(f"  slug:       {row['slug']}")
            print()
            cuerpo = row["cuerpo_md"] or ""
            print("CUERPO (primeras 300 chars):")
            print(cuerpo[:300] + ("…" if len(cuerpo) > 300 else ""))
            print()
            print(f"CUERPO total: {len(cuerpo.split())} palabras")
            print()
            print("JSON-LD:")
            print(pretty(row["schema_jsonld"]))
            print()
            if img_row:
                print("IMAGEN DESTACADA:")
                print(f"  url:       {img_row['url_publica']}")
                print(f"  alt:       {img_row['alt_text']}")
                print(f"  pie_foto:  {img_row['pie_foto']}")
                print(f"  fuente:    {img_row['fuente']}")
            else:
                print("IMAGEN DESTACADA: (sin imagen)")
            print()
            if entidades_link:
                print(
                    "draft_entidades: "
                    + ", ".join(r["nombre_canonico"] for r in entidades_link)
                )
            else:
                print("draft_entidades: (sin entidades catalogadas)")

        # ----- Tokens y coste -----
        print()
        print("=" * 72)
        print("TOKENS CONSUMIDOS")
        print("=" * 72)
        total = 0.0
        unknown = False
        for modelo, tin in claude.tokens_in_por_modelo.items():
            tout = claude.tokens_out_por_modelo.get(modelo, 0)
            coste = calcular_coste_eur(modelo, tin, tout)
            cs = f"{coste:.4f} EUR" if coste is not None else "coste desconocido"
            if coste is None:
                unknown = True
            else:
                total += coste
            print(
                f"  {modelo}: {tin/1000:.1f}k in / {tout/1000:.1f}k out → {cs}"
            )
        for modelo, tin in gemini.tokens_in_por_modelo.items():
            tout = gemini.tokens_out_por_modelo.get(modelo, 0)
            coste = calcular_coste_eur(modelo, tin, tout)
            cs = f"{coste:.4f} EUR" if coste is not None else "coste desconocido"
            if coste is None:
                unknown = True
            else:
                total += coste
            print(
                f"  {modelo}: {tin/1000:.1f}k in / {tout/1000:.1f}k out → {cs}"
            )
        print(f"  voyage-3-large: {embeddings.calls_total} llamadas")
        print(f"  brave:          {getattr(search, 'calls_total', 0)} llamadas")
        if hasattr(images, "calls_total"):
            print(f"  pexels:         {images.calls_total} llamadas (gratis)")
        sufijo = " (incompleto)" if unknown else ""
        print(f"TOTAL ESTIMADO: {total:.4f} EUR{sufijo}")
        print("=" * 72)

        if estado == "completado":
            return 0
        if estado == "requiere_revision":
            return 0
        return 1
    finally:
        await pool.close()


def _estado(state: dict) -> str:
    if state.get("detect_motivo_aborto") or state.get("research_motivo_aborto"):
        return "rechazado"
    if state.get("requiere_revision_humana"):
        return "requiere_revision"
    if state.get("draft_id") and state.get("review_aprobado"):
        return "completado"
    return "fallido"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--senal-id", required=True)
    parser.add_argument("--redactor-id", required=True)
    parser.add_argument("--medio-id", required=True)
    args = parser.parse_args()
    try:
        senal_id = UUID(args.senal_id)
        redactor_id = UUID(args.redactor_id)
        medio_id = UUID(args.medio_id)
    except ValueError as err:
        print(f"ERROR: UUID inválido: {err}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run(senal_id, redactor_id, medio_id))
    except Exception:
        print("ERROR — traceback completo:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
