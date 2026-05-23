"""Dedupe semántico de señales.

Pipeline: embed(termino) → cosine search en ``senales`` últimas 24h del medio
→ si similitud > umbral, update score+volumen+expira_at; si no, devuelve None
para que el caller inserte.

Diseño: la función ``buscar_similar`` es pura sobre (conn, medio_id, embedding).
Toda interacción con BD se aísla aquí para que la lógica de detección no
tenga que conocer el esquema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import asyncpg

UMBRAL_SIMILITUD = 0.85
VENTANA_DEDUPE_HORAS = 24


@dataclass(frozen=True)
class SenalSimilar:
    id: UUID
    similitud: float       # cosine similarity [0, 1]
    score_actual: float
    volumen_actual: int | None


async def buscar_similar(
    conn: asyncpg.Connection,
    medio_id: UUID,
    embedding: list[float],
    umbral: float = UMBRAL_SIMILITUD,
    ventana_horas: int = VENTANA_DEDUPE_HORAS,
) -> SenalSimilar | None:
    """Devuelve la señal más similar dentro de la ventana, si supera el umbral.

    Usa el índice HNSW sobre ``senales.embedding`` (vector_cosine_ops).
    En pgvector el operador ``<=>`` es cosine DISTANCE = 1 - cosine_sim.
    """
    # asyncpg envía listas como arrays — pgvector acepta strings tipo '[0.1,0.2,...]'.
    vec = "[" + ",".join(f"{x:.7f}" for x in embedding) + "]"
    distancia_max = 1.0 - umbral

    row = await conn.fetchrow(
        """
        SELECT id, score, volumen, (embedding <=> $1::vector) AS distancia
          FROM senales
         WHERE medio_id = $2
           AND embedding IS NOT NULL
           AND detectado_at > NOW() - ($3 || ' hours')::interval
         ORDER BY embedding <=> $1::vector
         LIMIT 1
        """,
        vec,
        medio_id,
        str(ventana_horas),
    )
    if row is None:
        return None
    distancia = float(row["distancia"])
    if distancia > distancia_max:
        return None
    return SenalSimilar(
        id=row["id"],
        similitud=1.0 - distancia,
        score_actual=float(row["score"]),
        volumen_actual=row["volumen"],
    )


async def actualizar_similar(
    conn: asyncpg.Connection,
    senal_id: UUID,
    nuevo_score: float,
    nuevo_volumen: int | None,
    extender_horas: int,
) -> None:
    """En vez de insertar duplicada, actualiza la señal existente.

    Política: el score se queda con el máximo (no decae al ver un eco más débil),
    el volumen se suma (acumulamos menciones), expira_at se extiende.
    """
    await conn.execute(
        """
        UPDATE senales
           SET score = GREATEST(score, $1),
               volumen = COALESCE(volumen, 0) + COALESCE($2, 0),
               expira_at = GREATEST(
                 expira_at,
                 NOW() + ($3 || ' hours')::interval
               )
         WHERE id = $4
        """,
        nuevo_score,
        nuevo_volumen,
        str(extender_horas),
        senal_id,
    )


def calcular_freshness_horas(detectado_at_unix: float, now_unix: float) -> float:
    """Helper para el scorer. Mantiene la fórmula en un solo sitio."""
    delta = max(0.0, now_unix - detectado_at_unix)
    return delta / 3600.0


# Reexport para el test
_VENTANA_TIMEDELTA = timedelta(hours=VENTANA_DEDUPE_HORAS)
