"""Nodo ``detect``: consolida QUÉ se va a escribir.

PR A: stub funcional que satisface el contrato del grafo. Acepta
``senal_id`` o ``tema_input`` y rellena ``tema_final``, ``angulo``,
``urgencia``, ``tipo_run``.

PR B (con secrets de LLM): clasificación real con Haiku, check de
canibalización exacta (``drafts.senal_id``) y semántica (embedding +
cosine 0.85).
"""

from __future__ import annotations

import structlog

from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.state import PipelineState

logger = structlog.get_logger(__name__)


async def detect_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    senal_id = state.get("senal_id")
    tema_input = state.get("tema_input")

    if senal_id is None and not tema_input:
        return {
            **state,
            "detect_motivo_aborto": "ni_senal_ni_tema",
        }

    # Stub: PR B reemplazará con clasificación Haiku + check canibalización.
    if senal_id is not None:
        # Cargar la señal y verificar no haber escrito sobre ella en 30 días.
        tema_final, angulo, urgencia, tipo_run = await _resolver_desde_senal(
            state, deps
        )
    else:
        assert tema_input is not None
        tema_final = tema_input
        angulo = "general"
        urgencia = "evergreen"  # tema libre = evergreen por defecto
        tipo_run = "nuevo"

    logger.info(
        "detect_ok",
        run_id=str(state.get("run_id")),
        tema_final=tema_final[:80],
        urgencia=urgencia,
        tipo_run=tipo_run,
    )
    return {
        **state,
        "tema_final": tema_final,
        "angulo": angulo,
        "urgencia": urgencia,
        "tipo_run": tipo_run,
        "detect_motivo_aborto": None,
    }


async def _resolver_desde_senal(
    state: PipelineState, deps: PipelineDeps
) -> tuple[str, str, str, str]:
    """Resuelve tema/ángulo/urgencia desde la señal.

    Implementación stub: lee `senales.termino` y devuelve valores por
    defecto. La versión LLM (PR B) clasifica con Haiku y verifica
    canibalización vía `drafts.senal_id` y embedding cosine.
    """
    medio_id = state["medio_id"]
    senal_id = state["senal_id"]
    async with deps.pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
        )
        row = await conn.fetchrow(
            "SELECT termino, categoria, paywall FROM senales WHERE id = $1",
            senal_id,
        )
    if row is None:
        return ("(señal no encontrada)", "general", "normal", "nuevo")
    return (row["termino"], "general", "normal", "nuevo")
