"""CLI entrypoint para el scheduler de GitHub Actions y operaciones manuales.

Subcomandos:
    detect    Ejecuta detectores de señales para un medio (cron).
    redactar  Lanza el pipeline multiagente (6 nodos) para una señal o tema.

Uso:
    python -m src.cli detect --medio-slug hoy-aragon
    python -m src.cli detect --medio-slug hoy-aragon --detector rss
    python -m src.cli redactar --medio-slug hoy-aragon --redactor-id UUID \\
        [--senal-id UUID | --tema-libre "texto"]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from src.llm.embeddings import EmbeddingsClient, VoyageEmbeddings
from src.trends.gdelt import GDELTDetector
from src.trends.gtrends import GTrendsDetector
from src.trends.persistence import close_pool, get_pool
from src.trends.rss import RSSDetector
from src.trends.runner import EjecucionResultado, ejecutar_fuente
from src.trends.x_api import XApiDetector

logger = structlog.get_logger(__name__)


def _setup_logging() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )


async def _resolver_medio(dsn: str, slug: str) -> UUID | None:
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT id FROM medios WHERE slug = $1 AND activo = TRUE", slug
        )
        return row["id"] if row else None
    finally:
        await conn.close()


def _build_detector(nombre: str, pool: asyncpg.Pool) -> Any:
    if nombre == "rss":
        return RSSDetector()
    if nombre == "gtrends":
        return GTrendsDetector()
    if nombre == "gdelt":
        return GDELTDetector()
    if nombre == "x":
        return XApiDetector(pool=pool)
    raise ValueError(f"detector desconocido: {nombre}")


# ===========================================================================
# Subcomando: detect (idéntico a PR A.1)
# ===========================================================================
_FAIL_FRACTION_DEFAULT = 0.5


async def cmd_detect(args: argparse.Namespace) -> int:
    dsn = os.environ["DATABASE_URL"]
    medio_id = await _resolver_medio(dsn, args.medio_slug)
    if medio_id is None:
        logger.info("medio_no_onboardado_skip", medio=args.medio_slug)
        print(f"[{args.medio_slug}] medio no onboardado — skip", file=sys.stderr)
        return 0
    embeddings: EmbeddingsClient = VoyageEmbeddings()
    pool = await get_pool(dsn)

    async with pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
        )
        filtros = ["medio_id = $1", "activo = TRUE"]
        params: list[Any] = [medio_id]
        if args.detector:
            filtros.append(f"detector = ${len(params) + 1}")
            params.append(args.detector)
        fuentes = await conn.fetch(
            "SELECT id, detector FROM fuentes_configuradas WHERE "
            + " AND ".join(filtros),
            *params,
        )

    if not fuentes:
        logger.info("sin_fuentes", medio=args.medio_slug, detector=args.detector)
        print(f"[{args.medio_slug}] sin fuentes activas", file=sys.stderr)
        return 0

    conteo: dict[str, int] = {"ok": 0, "sin_resultados": 0, "error": 0, "otros": 0}
    for f in fuentes:
        det = _build_detector(f["detector"], pool)
        try:
            resultado = await ejecutar_fuente(
                pool, medio_id, f["id"], det, embeddings
            )
        except Exception:
            logger.exception(
                "ejecutar_fuente_exterior_fallo", fuente_id=str(f["id"])
            )
            resultado = EjecucionResultado(f["id"], 0, 0, 0, "error")

        logger.info(
            "fuente_ejecutada",
            medio=args.medio_slug,
            fuente_id=str(resultado.fuente_id),
            detector=f["detector"],
            detectadas=resultado.n_detectadas,
            insertadas=resultado.n_insertadas,
            actualizadas=resultado.n_actualizadas,
            estado=resultado.estado,
        )
        if resultado.estado in conteo:
            conteo[resultado.estado] += 1
        else:
            conteo["otros"] += 1

    total = len(fuentes)
    ok = conteo["ok"]
    sin_resultados = conteo["sin_resultados"]
    errores = conteo["error"] + conteo["otros"]

    print(
        f"[{args.medio_slug}] {ok}/{total} OK, {sin_resultados} sin_resultados, "
        f"{errores}/{total} errores",
        file=sys.stderr,
    )

    try:
        umbral = float(
            os.environ.get("REDACTIA_FAIL_FRACTION", _FAIL_FRACTION_DEFAULT)
        )
    except ValueError:
        umbral = _FAIL_FRACTION_DEFAULT
    if total > 0 and (errores / total) > umbral:
        logger.error(
            "cli_exit_fallo_masivo",
            medio=args.medio_slug,
            errores=errores,
            total=total,
            umbral=umbral,
        )
        return 2
    return 0


# ===========================================================================
# Subcomando: redactar (PR B)
# ===========================================================================
async def cmd_redactar(args: argparse.Namespace) -> int:  # noqa: PLR0915
    # Imports diferidos para que `python -m src.cli detect ...` siga arrancando
    # rápido (no toca anthropic/google-genai si no se va a redactar).
    from src.llm.brave import BraveSearch
    from src.llm.claude import ClaudeReal
    from src.llm.gemini import GeminiReal
    from src.llm.pexels import PexelsClient
    from src.pipeline import build_graph
    from src.pipeline.nodes.deps import PipelineDeps
    from src.pipeline.persistence import crear_run
    from src.pipeline.state import PipelineState

    dsn = os.environ["DATABASE_URL"]
    medio_id = await _resolver_medio(dsn, args.medio_slug)
    if medio_id is None:
        print(f"ERROR: medio '{args.medio_slug}' no encontrado o inactivo", file=sys.stderr)
        return 2

    if not args.senal_id and not args.tema_libre:
        print("ERROR: requiere --senal-id O --tema-libre", file=sys.stderr)
        return 2
    if args.senal_id and args.tema_libre:
        print("ERROR: --senal-id y --tema-libre son mutuamente excluyentes", file=sys.stderr)
        return 2

    try:
        redactor_id = UUID(args.redactor_id)
        senal_uuid = UUID(args.senal_id) if args.senal_id else None
    except ValueError as err:
        print(f"ERROR: UUID inválido: {err}", file=sys.stderr)
        return 2

    pool = await get_pool(dsn)
    try:
        # Clientes reales con tracking de tokens.
        claude = ClaudeReal()
        gemini = GeminiReal()
        embeddings = VoyageEmbeddings()
        search = BraveSearch()
        # Pexels es opcional: si no hay API key, draft sin imagen.
        try:
            images: Any = PexelsClient()
        except RuntimeError:
            logger.warning("pexels_no_configurado_sin_imagen")
            images = _NoImages()

        deps = PipelineDeps(
            pool=pool,
            claude=claude,
            gemini=gemini,
            search=search,
            images=images,
            embeddings=embeddings,
        )

        # Crear el run en BD antes de invocar el grafo.
        async with pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
            )
            run_id = await crear_run(
                conn,
                medio_id=medio_id,
                redactor_id=redactor_id,
                trigger_tipo="manual",
                senal_id=senal_uuid,
                tema_input=args.tema_libre,
            )

        state_inicial: PipelineState = {
            "medio_id": medio_id,
            "run_id": run_id,
            "redactor_id": redactor_id,
            "trigger_tipo": "manual",
        }
        if senal_uuid is not None:
            state_inicial["senal_id"] = senal_uuid
        if args.tema_libre:
            state_inicial["tema_input"] = args.tema_libre

        graph = build_graph(deps)
        state_final = await graph.ainvoke(state_inicial)

        # Resumen de salida.
        _imprimir_resumen(
            state_final=state_final,
            run_id=run_id,
            claude=claude,
            gemini=gemini,
            embeddings=embeddings,
            search=search,
            images=images,
        )

        # Exit code según estado final.
        if state_final.get("detect_motivo_aborto") or state_final.get(
            "research_motivo_aborto"
        ):
            return 1
        if state_final.get("requiere_revision_humana"):
            return 0  # OK, requiere revisión humana
        if not state_final.get("draft_id"):
            return 1
        return 0
    finally:
        await close_pool()


class _NoImages:
    """Fallback cuando PEXELS_API_KEY no está configurada."""

    calls_total: int = 0

    async def buscar_imagen(self, query: str) -> dict | None:  # noqa: ARG002
        return None


def _imprimir_resumen(
    *,
    state_final: dict,
    run_id: UUID,
    claude: Any,
    gemini: Any,
    embeddings: Any,
    search: Any,
    images: Any,
) -> None:
    """Print al stderr del resumen + coste estimado. stdout queda libre para
    quien quiera parsear el state_final (no lo hacemos por ahora)."""
    from src.llm.precios import calcular_coste_eur

    print("=" * 72, file=sys.stderr)
    estado_run = _estado_run_desde_state(state_final)
    print(f"Estado: {estado_run}", file=sys.stderr)
    print(f"Run ID: {run_id}", file=sys.stderr)
    draft_id = state_final.get("draft_id")
    if draft_id:
        print(f"Draft ID: {draft_id}", file=sys.stderr)
        print(f"URL editor: {state_final.get('editor_url')}", file=sys.stderr)
    motivo = state_final.get("detect_motivo_aborto") or state_final.get(
        "research_motivo_aborto"
    )
    if motivo:
        print(f"Motivo aborto: {motivo}", file=sys.stderr)
    if state_final.get("requiere_revision_humana"):
        errores = state_final.get("review_errores") or []
        print(
            f"Requiere revisión humana ({len(errores)} errores):",
            file=sys.stderr,
        )
        for e in errores[:10]:
            print(f"  - {e}", file=sys.stderr)

    print("", file=sys.stderr)
    print("Tokens consumidos:", file=sys.stderr)
    total_eur = 0.0
    coste_desconocido = False
    for modelo in sorted(claude.tokens_in_por_modelo.keys()):
        tin = claude.tokens_in_por_modelo.get(modelo, 0)
        tout = claude.tokens_out_por_modelo.get(modelo, 0)
        coste = calcular_coste_eur(modelo, tin, tout)
        coste_str = f"{coste:.4f} EUR" if coste is not None else "coste desconocido"
        if coste is None:
            coste_desconocido = True
        else:
            total_eur += coste
        print(
            f"  - {modelo}: {tin/1000:.1f}k in / {tout/1000:.1f}k out → {coste_str}",
            file=sys.stderr,
        )
    for modelo in sorted(gemini.tokens_in_por_modelo.keys()):
        tin = gemini.tokens_in_por_modelo.get(modelo, 0)
        tout = gemini.tokens_out_por_modelo.get(modelo, 0)
        coste = calcular_coste_eur(modelo, tin, tout)
        coste_str = f"{coste:.4f} EUR" if coste is not None else "coste desconocido"
        if coste is None:
            coste_desconocido = True
        else:
            total_eur += coste
        print(
            f"  - {modelo}: {tin/1000:.1f}k in / {tout/1000:.1f}k out → {coste_str}",
            file=sys.stderr,
        )
    voyage_calls = getattr(embeddings, "calls_total", None) or 0
    if voyage_calls:
        print(
            f"  - voyage-3-large: {voyage_calls} llamadas (coste según tokens reales)",
            file=sys.stderr,
        )
    if hasattr(images, "calls_total"):
        print(f"  - pexels: {images.calls_total} llamadas (gratis)", file=sys.stderr)
    brave_calls = getattr(search, "calls_total", None) or 0
    if brave_calls:
        print(f"  - brave: {brave_calls} llamadas", file=sys.stderr)

    sufijo = " (incompleto)" if coste_desconocido else ""
    print(f"Total estimado: {total_eur:.4f} EUR{sufijo}", file=sys.stderr)
    print("=" * 72, file=sys.stderr)


def _estado_run_desde_state(state: dict) -> str:
    if state.get("detect_motivo_aborto") or state.get("research_motivo_aborto"):
        return "rechazado"
    if state.get("requiere_revision_humana"):
        return "requiere_revision"
    if state.get("draft_id") and state.get("review_aprobado"):
        return "completado"
    return "fallido"


# ===========================================================================
# Entry point
# ===========================================================================
def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="redactia-workers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_detect = sub.add_parser("detect", help="Ejecuta detectores para un medio")
    p_detect.add_argument("--medio-slug", required=True)
    p_detect.add_argument(
        "--detector",
        choices=["rss", "gtrends", "gdelt", "x"],
        help="Limita a un detector concreto (opcional)",
    )

    p_red = sub.add_parser("redactar", help="Lanza el pipeline multiagente")
    p_red.add_argument("--medio-slug", required=True)
    p_red.add_argument("--redactor-id", required=True, help="UUID del redactor")
    grupo = p_red.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--senal-id", help="UUID de la señal a redactar")
    grupo.add_argument("--tema-libre", help="Tema libre (sin breaking; va a evergreen)")

    args = parser.parse_args(argv)
    if args.cmd == "detect":
        return asyncio.run(cmd_detect(args))
    if args.cmd == "redactar":
        return asyncio.run(cmd_redactar(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
