"""Persistencia del pipeline: ``runs``, ``run_steps`` y ``drafts``.

Patrón de uso por nodo:

    async with with_step(pool, run_id, "research", input_payload) as step:
        ...  # trabajo del nodo
        step.output = {"fuentes": [...], "hechos": [...]}

Al salir del ``async with`` se actualiza la fila de ``run_steps`` con
output, modelo, tokens, duración y estado. Si el cuerpo lanza, se marca
``fallido`` y se persiste el error antes de re-lanzar.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import asyncpg
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class StepRecord:
    """Mutable: el cuerpo del nodo asigna ``output``, ``modelo``, etc."""

    step_id: UUID
    run_id: UUID
    step_nombre: str
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    modelo: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    prompt_usado: str | None = None
    error: str | None = None


async def crear_run(
    conn: asyncpg.Connection,
    *,
    medio_id: UUID,
    redactor_id: UUID | None,
    trigger_tipo: str,
    senal_id: UUID | None = None,
    tema_input: str | None = None,
    categoria: str | None = None,
    trigger_id: UUID | None = None,
) -> UUID:
    """Inserta un ``runs`` row en estado ``pendiente`` y devuelve su id."""
    return await conn.fetchval(
        """
        INSERT INTO runs (
          medio_id, redactor_id, trigger_tipo, trigger_id, senal_id,
          tema_input, categoria, estado
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'pendiente')
        RETURNING id
        """,
        medio_id,
        redactor_id,
        trigger_tipo,
        trigger_id,
        senal_id,
        tema_input,
        categoria,
    )


async def marcar_run_ejecutando(conn: asyncpg.Connection, run_id: UUID) -> None:
    await conn.execute(
        "UPDATE runs SET estado = 'ejecutando' WHERE id = $1", run_id
    )


async def marcar_run_completado(
    conn: asyncpg.Connection, run_id: UUID, coste_eur: float | None = None
) -> None:
    await conn.execute(
        "UPDATE runs SET estado = 'completado', finalizado_at = NOW(), "
        "coste_eur = COALESCE($2, coste_eur) WHERE id = $1",
        run_id,
        coste_eur,
    )


async def marcar_run_fallido(
    conn: asyncpg.Connection, run_id: UUID, error: str
) -> None:
    await conn.execute(
        "UPDATE runs SET estado = 'fallido', finalizado_at = NOW() WHERE id = $1",
        run_id,
    )
    logger.error("run_fallido", run_id=str(run_id), error=error)


@asynccontextmanager
async def with_step(
    pool: asyncpg.Pool,
    medio_id: UUID,
    run_id: UUID,
    step_nombre: str,
    input_payload: dict[str, Any],
) -> AsyncIterator[StepRecord]:
    """Context manager que envuelve un nodo en una fila de ``run_steps``.

    Conn dedicada del pool, autocommit (cada UPDATE persiste de inmediato).
    La fila se inserta al entrar; al salir se actualiza con output, duración
    y estado. Si el cuerpo lanza, se marca fallido y se re-lanza.
    """
    t0 = time.monotonic()
    async with pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
        )
        step_id = await conn.fetchval(
            """
            INSERT INTO run_steps (
              run_id, medio_id, step_nombre, estado, input, iniciado_at
            )
            VALUES ($1, $2, $3, 'ejecutando', $4, NOW())
            ON CONFLICT (run_id, step_nombre) DO UPDATE SET
              estado = 'ejecutando',
              input = EXCLUDED.input,
              iniciado_at = NOW(),
              finalizado_at = NULL,
              output = NULL,
              error = NULL
            RETURNING id
            """,
            run_id,
            medio_id,
            step_nombre,
            input_payload,
        )
        record = StepRecord(
            step_id=step_id,
            run_id=run_id,
            step_nombre=step_nombre,
            input=input_payload,
        )
        try:
            yield record
        except Exception as err:
            duracion_ms = int((time.monotonic() - t0) * 1000)
            record.error = f"{type(err).__name__}: {err}"
            await conn.execute(
                """
                UPDATE run_steps
                   SET estado = 'fallido',
                       output = $1,
                       modelo = $2,
                       tokens_in = $3,
                       tokens_out = $4,
                       prompt_usado = $5,
                       duracion_ms = $6,
                       error = $7,
                       finalizado_at = NOW()
                 WHERE id = $8
                """,
                record.output,
                record.modelo,
                record.tokens_in,
                record.tokens_out,
                record.prompt_usado,
                duracion_ms,
                record.error,
                step_id,
            )
            raise

        duracion_ms = int((time.monotonic() - t0) * 1000)
        await conn.execute(
            """
            UPDATE run_steps
               SET estado = 'completado',
                   output = $1,
                   modelo = $2,
                   tokens_in = $3,
                   tokens_out = $4,
                   prompt_usado = $5,
                   duracion_ms = $6,
                   finalizado_at = NOW()
             WHERE id = $7
            """,
            record.output,
            record.modelo,
            record.tokens_in,
            record.tokens_out,
            record.prompt_usado,
            duracion_ms,
            step_id,
        )


async def insertar_draft(
    conn: asyncpg.Connection,
    *,
    run_id: UUID,
    medio_id: UUID,
    titulo: str,
    meta_title: str | None,
    meta_descr: str | None,
    slug: str | None,
    cuerpo_md: str,
    entidades: list[dict[str, Any]] | None,
    enlaces_internos: list[dict[str, Any]] | None,
    schema_jsonld: dict[str, Any] | None,
    estado: str = "borrador",
) -> UUID:
    """Inserta un draft. ``senal_id`` se sincroniza por trigger desde ``runs``."""
    return await conn.fetchval(
        """
        INSERT INTO drafts (
          run_id, medio_id, titulo, meta_title, meta_descr, slug,
          cuerpo_md, entidades, enlaces_internos, schema_jsonld, estado
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING id
        """,
        run_id,
        medio_id,
        titulo,
        meta_title,
        meta_descr,
        slug,
        cuerpo_md,
        entidades or [],
        enlaces_internos or [],
        schema_jsonld or {},
        estado,
    )
