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
from src.trends.persistence import tenant_connection
from src.trends.rss import RSSDetector
from src.trends.runner import ejecutar_fuente
from src.trends.x_api import XApiDetector

logger = structlog.get_logger(__name__)


def _setup_logging() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
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


async def cmd_detect(args: argparse.Namespace) -> int:
    from src.trends.persistence import get_pool

    dsn = os.environ["DATABASE_URL"]
    medio_id = await _resolver_medio(dsn, args.medio_slug)
    if medio_id is None:
        # Esperado en Fase 2 mientras solo Hoy Aragón está onboardeado: el matrix
        # del workflow contiene los 3 medios. No queremos rojo por eso.
        logger.info("medio_no_onboardado_skip", medio=args.medio_slug)
        return 0
    embeddings: EmbeddingsClient = VoyageEmbeddings()
    pool = await get_pool(dsn)

    async with tenant_connection(dsn, medio_id) as conn:
        filtros = ["medio_id = $1", "activo = TRUE"]
        params: list[Any] = [medio_id]
        if args.detector:
            filtros.append(f"detector = ${len(params) + 1}")
            params.append(args.detector)
        fuentes = await conn.fetch(
            "SELECT id, detector FROM fuentes_configuradas WHERE " + " AND ".join(filtros),
            *params,
        )

        if not fuentes:
            logger.info("sin_fuentes", medio=args.medio_slug, detector=args.detector)
            return 0

        for f in fuentes:
            det = _build_detector(f["detector"], pool)
            resultado = await ejecutar_fuente(conn, f["id"], det, embeddings)
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
