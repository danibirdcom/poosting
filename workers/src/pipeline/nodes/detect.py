"""Nodo ``detect``: consolida QUÉ se va a escribir.

Resuelve el tema final, ángulo y urgencia, y decide si se trata de un
artículo nuevo o de una actualización de uno previo (canibalización
semántica contra ``drafts`` publicados en los últimos 30 días).

Inputs aceptados en ``state``:
- ``senal_id``: si viene de automatización por señales. detect carga el
  término, calcula embedding y busca drafts similares.
- ``tema_input``: si es disparo manual. detect bloquea ``urgencia='breaking'``
  (las breakings exigen señal verificada) y pide clasificación al LLM.

Modelo: Haiku 4.5 (string desde ``llm/config.CLAUDE_HAIKU_MODEL``).

Salida (claves añadidas a ``state``):
- ``tema_final``, ``angulo``, ``urgencia``, ``tipo_run``
- ``draft_actualizar_id`` (si ``tipo_run='actualizacion'``)
- ``detect_motivo_aborto`` (si abortamos)
"""

from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

import structlog
from pydantic import BaseModel, Field, ValidationError

from src.llm.config import CLAUDE_HAIKU_MODEL
from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.state import PipelineState

logger = structlog.get_logger(__name__)

# Similitud coseno por encima de la cual consideramos canibalización.
SIMILITUD_CANIBALIZACION = 0.85
# Ventana temporal para el check.
VENTANA_DIAS = 30


class DetectClassification(BaseModel):
    """Schema estricto de la salida del LLM."""

    tema_final: str = Field(min_length=3, max_length=500)
    angulo: str = Field(min_length=1, max_length=300)
    urgencia: Literal["breaking", "normal", "evergreen"]


PROMPT_TEMPLATE = (
    "Eres un editor de noticias. Clasifica el siguiente material y devuelve "
    "JSON ESTRICTO (sin texto extra, sin markdown) con las claves:\n"
    "- tema_final: el tema concreto del artículo a redactar (string).\n"
    "- angulo: el ángulo editorial recomendado (string corto).\n"
    "- urgencia: una de 'breaking', 'normal', 'evergreen'.\n\n"
    "Reglas de urgencia:\n"
    "- 'breaking': solo si el material describe un suceso de impacto público "
    "ocurrido en las últimas horas.\n"
    "- 'normal': noticia con relevancia pero no urgente (24-72h).\n"
    "- 'evergreen': contenido atemporal, explicativo o de fondo.\n\n"
    "MATERIAL:\n"
    "Origen: {origen}\n"
    "Tema/Término: {termino}\n"
    "Categoría sugerida: {categoria}\n\n"
    "Responde SOLO el JSON."
)


async def detect_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    senal_id = state.get("senal_id")
    tema_input = state.get("tema_input")

    if senal_id is None and not tema_input:
        return {**state, "detect_motivo_aborto": "ni_senal_ni_tema"}

    if senal_id is not None:
        return await _resolver_desde_senal(state, deps)
    assert tema_input is not None
    return await _resolver_desde_tema_libre(state, deps, tema_input)


# ---------------------------------------------------------------------------
# Caso 1: viene una señal
# ---------------------------------------------------------------------------
async def _resolver_desde_senal(
    state: PipelineState, deps: PipelineDeps
) -> PipelineState:
    medio_id = state["medio_id"]
    senal_id = state["senal_id"]
    assert senal_id is not None

    async with deps.pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
        )
        senal = await conn.fetchrow(
            "SELECT termino, categoria, origen, "
            "       (embedding IS NOT NULL) AS tiene_embedding "
            "FROM senales WHERE id = $1",
            senal_id,
        )
        if senal is None:
            logger.warning("detect_senal_no_encontrada", senal_id=str(senal_id))
            return {**state, "detect_motivo_aborto": "senal_no_encontrada"}

        # Canibalización semántica: la mejor estrategia para evitar problemas
        # de codecs de tipo `vector` con asyncpg es mantener el embedding en
        # SQL — no traerlo a Python si no hace falta. Tenemos dos casos:
        #
        # A) La señal YA tiene embedding (lo común: lo calculó el detector).
        #    Hacemos el cosine search con una subquery que lee el embedding
        #    directamente desde la fila de senales.
        #
        # B) La señal NO tiene embedding (edge case: detector legacy o señal
        #    insertada a mano). Si tenemos cliente de embeddings, lo
        #    calculamos on-demand y lo pasamos como parámetro.
        draft_actualizar_id: UUID | None = None
        tipo_run: Literal["nuevo", "actualizacion"] = "nuevo"

        match = None
        if senal["tiene_embedding"]:
            match = await conn.fetchrow(
                """
                WITH ref AS (
                  SELECT embedding FROM senales WHERE id = $1
                )
                SELECT d.id,
                       1 - (d.embedding <=> ref.embedding) AS similitud
                  FROM drafts d, ref
                 WHERE d.medio_id = $2
                   AND d.embedding IS NOT NULL
                   AND d.publicado_at IS NOT NULL
                   AND d.publicado_at > NOW() - ($3 || ' days')::INTERVAL
                 ORDER BY d.embedding <=> ref.embedding ASC
                 LIMIT 1
                """,
                senal_id,
                medio_id,
                str(VENTANA_DIAS),
            )
        elif deps.embeddings is not None:
            vectors = await deps.embeddings.embed(
                [senal["termino"]], input_type="query"
            )
            if vectors:
                emb_lit = _vector_literal(vectors[0])
                match = await conn.fetchrow(
                    """
                    SELECT id, 1 - (embedding <=> $1::vector) AS similitud
                      FROM drafts
                     WHERE medio_id = $2
                       AND embedding IS NOT NULL
                       AND publicado_at IS NOT NULL
                       AND publicado_at > NOW() - ($3 || ' days')::INTERVAL
                     ORDER BY embedding <=> $1::vector ASC
                     LIMIT 1
                    """,
                    emb_lit,
                    medio_id,
                    str(VENTANA_DIAS),
                )

        if match is not None and float(match["similitud"]) > SIMILITUD_CANIBALIZACION:
            draft_actualizar_id = match["id"]
            tipo_run = "actualizacion"
            logger.info(
                "detect_canibalizacion",
                similitud=float(match["similitud"]),
                draft_actualizar_id=str(draft_actualizar_id),
            )

    clasificacion = await _clasificar_con_haiku(
        deps,
        origen=str(senal["origen"]),
        termino=str(senal["termino"]),
        categoria=senal["categoria"],
    )
    if clasificacion is None:
        return {**state, "detect_motivo_aborto": "clasificacion_invalida"}

    logger.info(
        "detect_ok",
        run_id=str(state.get("run_id")),
        tema_final=clasificacion.tema_final[:80],
        urgencia=clasificacion.urgencia,
        tipo_run=tipo_run,
    )
    return {
        **state,
        "tema_final": clasificacion.tema_final,
        "angulo": clasificacion.angulo,
        "urgencia": clasificacion.urgencia,
        "tipo_run": tipo_run,
        "draft_actualizar_id": draft_actualizar_id,
        "detect_motivo_aborto": None,
    }


# ---------------------------------------------------------------------------
# Caso 2: tema libre (sin señal)
# ---------------------------------------------------------------------------
async def _resolver_desde_tema_libre(
    state: PipelineState, deps: PipelineDeps, tema_input: str
) -> PipelineState:
    clasificacion = await _clasificar_con_haiku(
        deps,
        origen="tema_libre",
        termino=tema_input,
        categoria=state.get("categoria"),
    )
    if clasificacion is None:
        return {**state, "detect_motivo_aborto": "clasificacion_invalida"}

    if clasificacion.urgencia == "breaking":
        # Las breakings exigen señal verificada — no aceptamos tema libre
        # marcado como urgente por el LLM (riesgo de fake news).
        logger.warning(
            "detect_breaking_rechazado_sin_senal",
            tema=tema_input[:80],
        )
        return {
            **state,
            "tema_final": clasificacion.tema_final,
            "angulo": clasificacion.angulo,
            "urgencia": clasificacion.urgencia,
            "detect_motivo_aborto": "breaking_requiere_senal",
        }

    logger.info(
        "detect_ok",
        run_id=str(state.get("run_id")),
        tema_final=clasificacion.tema_final[:80],
        urgencia=clasificacion.urgencia,
        tipo_run="nuevo",
    )
    return {
        **state,
        "tema_final": clasificacion.tema_final,
        "angulo": clasificacion.angulo,
        "urgencia": clasificacion.urgencia,
        "tipo_run": "nuevo",
        "draft_actualizar_id": None,
        "detect_motivo_aborto": None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _clasificar_con_haiku(
    deps: PipelineDeps,
    *,
    origen: str,
    termino: str,
    categoria: str | None,
) -> DetectClassification | None:
    prompt = PROMPT_TEMPLATE.format(
        origen=origen,
        termino=termino,
        categoria=categoria or "(sin categoría)",
    )
    raw = await deps.claude.generar(prompt, modelo=CLAUDE_HAIKU_MODEL)
    if not raw or not raw.strip():
        logger.warning("detect_haiku_vacio")
        return None
    try:
        # Tolerante a code fences accidentales (```json ... ```).
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.strip("`")
            if clean.lower().startswith("json"):
                clean = clean[4:].lstrip()
        data = json.loads(clean)
        return DetectClassification.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as err:
        logger.warning("detect_haiku_invalido", error=str(err), raw=raw[:200])
        return None


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"
