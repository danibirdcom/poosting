"""Orquestador del pipeline de detección.

Para una ``fuente_configurada`` dada:
1. Carga el perfil y el detector apropiado.
2. Invoca ``detectar(ctx)``.
3. Para cada ``SenalCruda``: embedding → dedupe → score → upsert.
4. Marca el estado de la ejecución en ``fuentes_configuradas``.

**Aislamiento transaccional por fuente:**

Cada llamada a ``ejecutar_fuente`` adquiere su propia conexión del pool y
envuelve los inserts en una transacción local. Si una fuente falla, su
transacción rolling back **sin afectar a las fuentes previas o
posteriores**. El estado (`ok` / `error` / `sin_resultados`) se persiste
en una conexión separada para que sobreviva al rollback del trabajo.

El bug que motivó este diseño: en el primer run real (PR #3 pre-merge),
las señales de Heraldo+El Periódico+X (34 total) se perdieron porque
Voyage devolvió 429 en una fuente posterior, lo que propagó la excepción
hasta el ``async with conn.transaction()`` del CLI y disparó rollback
global. Ahora cada fuente vive en su propio mundo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from src.llm.embeddings import EmbeddingsClient
from src.trends.base import DetectorContext, SenalCruda, TrendDetector
from src.trends.dedupe import (
    actualizar_similar,
    buscar_similar,
    calcular_freshness_horas,
)
from src.trends.persistence import insertar_senal, marcar_ejecucion_fuente
from src.trends.scorer import ScoringPesos, score_compuesto

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EjecucionResultado:
    fuente_id: UUID
    n_detectadas: int
    n_insertadas: int
    n_actualizadas: int
    estado: str          # 'ok' | 'sin_resultados' | 'error' | 'no_existe'


async def ejecutar_fuente(
    pool: asyncpg.Pool,
    medio_id: UUID,
    fuente_id: UUID,
    detector: TrendDetector,
    embeddings: EmbeddingsClient,
) -> EjecucionResultado:
    """Ejecuta el detector para una fuente concreta, aislando su transacción.

    Cualquier excepción que escape del detector o del cliente de embeddings
    se loggea con traza completa, la transacción de inserts rolling back,
    y la fuente queda marcada como ``error`` en una conn separada — pero
    el bucle del CLI puede seguir con la siguiente fuente.
    """
    estado = "error"
    n_detectadas = 0
    n_insert = 0
    n_update = 0

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
            )

            fuente = await conn.fetchrow(
                """
                SELECT f.id, f.medio_id, f.perfil_id, f.detector, f.config,
                       f.usar_solo_como_senal,
                       p.pais, p.idiomas, p.keywords_obligatorias,
                       p.keywords_negativas, p.categoria_destino
                  FROM fuentes_configuradas f
                  JOIN perfiles_deteccion p ON p.id = f.perfil_id
                 WHERE f.id = $1 AND f.activo = TRUE AND p.activo = TRUE
                """,
                fuente_id,
            )
            if fuente is None:
                logger.warning("fuente_no_encontrada", fuente_id=str(fuente_id))
                return EjecucionResultado(fuente_id, 0, 0, 0, "no_existe")

            ctx = DetectorContext(
                medio_id=fuente["medio_id"],
                perfil_id=fuente["perfil_id"],
                fuente_id=fuente["id"],
                categoria_destino=fuente["categoria_destino"],
                pais=fuente["pais"],
                idiomas=tuple(fuente["idiomas"]),
                keywords_obligatorias=tuple(fuente["keywords_obligatorias"]),
                keywords_negativas=tuple(fuente["keywords_negativas"]),
                config=fuente["config"] or {},
                usar_solo_como_senal=fuente["usar_solo_como_senal"],
            )

            senales_crudas = await detector.detectar(ctx)
            n_detectadas = len(senales_crudas)

            if not senales_crudas:
                estado = "sin_resultados"
                return EjecucionResultado(fuente_id, 0, 0, 0, "sin_resultados")

            pesos = await _cargar_pesos(conn, ctx.medio_id, ctx.categoria_destino)
            textos = [s.termino for s in senales_crudas]
            vectores = await embeddings.embed(textos)

            # Inserts de señales en transacción local. Si algo dentro lanza,
            # rollback solo de esta fuente; el resto del pipeline sigue.
            async with conn.transaction():
                now_unix = time.time()
                for senal, vec in zip(senales_crudas, vectores, strict=True):
                    freshness_h = calcular_freshness_horas(now_unix, now_unix)
                    multiplicador = _peso_region(senal, ctx)
                    score = score_compuesto(
                        velocidad=senal.velocidad,
                        volumen=senal.volumen,
                        freshness_horas=freshness_h,
                        intent=None,
                        pesos=pesos,
                        multiplicador_region=multiplicador,
                    )

                    similar = await buscar_similar(conn, ctx.medio_id, vec)
                    if similar is not None:
                        await actualizar_similar(
                            conn,
                            senal_id=similar.id,
                            nuevo_score=score,
                            nuevo_volumen=senal.volumen,
                            extender_horas=senal.expira_en_horas,
                        )
                        n_update += 1
                        continue

                    await insertar_senal(
                        conn,
                        medio_id=ctx.medio_id,
                        perfil_id=ctx.perfil_id,
                        fuente_id=ctx.fuente_id,
                        origen=senal.origen,
                        termino=senal.termino,
                        categoria=senal.categoria,
                        pais=senal.pais,
                        region=senal.region,
                        score=score,
                        velocidad=senal.velocidad,
                        volumen=senal.volumen,
                        url_origen=senal.url_origen,
                        paywall=senal.paywall,
                        expira_en_horas=senal.expira_en_horas,
                        embedding=vec,
                        metadatos=senal.metadatos,
                    )
                    n_insert += 1

            estado = "ok"
    except Exception:
        logger.exception(
            "ejecutar_fuente_excepcion", fuente_id=str(fuente_id), medio_id=str(medio_id)
        )
        estado = "error"

    # Marcar estado en una conn SEPARADA. Si la principal hizo rollback,
    # el marcado de "error" no se debe perder con ella.
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
            )
            await marcar_ejecucion_fuente(conn, fuente_id, estado)
    except Exception:
        logger.exception("marcar_ejecucion_fallo", fuente_id=str(fuente_id))

    return EjecucionResultado(fuente_id, n_detectadas, n_insert, n_update, estado)


async def _cargar_pesos(
    conn: asyncpg.Connection, medio_id: UUID, categoria: str
) -> ScoringPesos:
    row = await conn.fetchrow(
        "SELECT peso_velocidad, peso_volumen, peso_freshness, peso_intent "
        "FROM scoring_pesos WHERE medio_id = $1 AND categoria = $2",
        medio_id,
        categoria,
    )
    if row is None:
        return ScoringPesos(1.0, 1.0, 1.0, 1.0)
    return ScoringPesos(
        peso_velocidad=float(row["peso_velocidad"]),
        peso_volumen=float(row["peso_volumen"]),
        peso_freshness=float(row["peso_freshness"]),
        peso_intent=float(row["peso_intent"]),
    )


def _peso_region(senal: SenalCruda, ctx: DetectorContext) -> float:
    """Para GTrends con mezcla de geos, el config trae el peso por geo."""
    if senal.origen != "gtrends":
        return 1.0
    geos: list[dict[str, Any]] = ctx.config.get("geos") or []
    if not geos:
        return 1.0
    for g in geos:
        if g.get("geo") == senal.region:
            return float(g.get("peso", 1.0))
    return 1.0
