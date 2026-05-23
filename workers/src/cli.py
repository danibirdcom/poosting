"""CLI entrypoint para el scheduler de GitHub Actions.

Uso:
    python -m src.cli detect --medio-slug hoy-aragon
    python -m src.cli detect --medio-slug hoy-aragon --detector rss

Lee de BD los perfiles + fuentes activas del medio, instancia los detectores
y ejecuta el runner para cada uno.
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
from src.trends.persistence import get_pool
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
            # Renderiza el traceback como string cuando exc_info=True
            # (lo activa logger.exception). Sin esto el campo aparece como
            # "exc_info": true literal y la traza se pierde.
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )


async def _resolver_medio(dsn: str, slug: str) -> UUID | None:
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow("SELECT id FROM medios WHERE slug = $1 AND activo = TRUE", slug)
        return row["id"] if row else None
    finally:
        await conn.close()


def _build_detector(
    nombre: str, pool: asyncpg.Pool
) -> Any:
    if nombre == "rss":
        return RSSDetector()
    if nombre == "gtrends":
        return GTrendsDetector()
    if nombre == "gdelt":
        return GDELTDetector()
    if nombre == "x":
        # X API necesita pool para acquirir conexión dedicada para budget
        # ops fuera de la transacción del runner. Ver docs/runbooks/budget.md.
        return XApiDetector(pool=pool)
    raise ValueError(f"detector desconocido: {nombre}")


# Umbral de fallo: si la fracción de fuentes en estado 'error' supera este
# valor, el CLI termina con exit code 2 para que el job de GH Actions se
# marque rojo. Configurable vía env REDACTIA_FAIL_FRACTION.
_FAIL_FRACTION_DEFAULT = 0.5


async def cmd_detect(args: argparse.Namespace) -> int:
    dsn = os.environ["DATABASE_URL"]
    medio_id = await _resolver_medio(dsn, args.medio_slug)
    if medio_id is None:
        # Esperado en Fase 2 mientras solo Hoy Aragón está onboardeado: el matrix
        # del workflow contiene los 3 medios. No queremos rojo por eso.
        logger.info("medio_no_onboardado_skip", medio=args.medio_slug)
        print(f"[{args.medio_slug}] medio no onboardado — skip", file=sys.stderr)
        return 0
    embeddings: EmbeddingsClient = VoyageEmbeddings()
    pool = await get_pool(dsn)

    # Lectura de fuentes en una conn aparte (autocommit, sin tx). Cada
    # ``ejecutar_fuente`` adquirirá su propia conn y manejará su transacción.
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

    # Conteo por estado para el resumen final. Cada fuente se ejecuta en
    # aislamiento: si una explota, las demás siguen. ejecutar_fuente captura
    # internamente cualquier excepción y devuelve estado='error'; el try/except
    # aquí es solo defensa en profundidad por si hay un bug en el aislamiento.
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

    # Resumen visible en stdout (NO JSON) para que aparezca legible en el
    # output del step de GH Actions.
    print(
        f"[{args.medio_slug}] {ok}/{total} OK, {sin_resultados} sin_resultados, "
        f"{errores}/{total} errores",
        file=sys.stderr,
    )

    # Exit code != 0 si la fracción de errores supera el umbral. Por defecto
    # 0.5: si más de la mitad de las fuentes fallan, falla el job. Configurable
    # vía env para casos especiales (p.ej. arranque con muchas fuentes nuevas).
    try:
        umbral = float(os.environ.get("REDACTIA_FAIL_FRACTION", _FAIL_FRACTION_DEFAULT))
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

    args = parser.parse_args(argv)
    if args.cmd == "detect":
        return asyncio.run(cmd_detect(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
