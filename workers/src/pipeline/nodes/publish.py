"""Nodo ``publish``: persiste el draft.

Fase 3 sólo soporta modo ``bandeja``: inserta en ``drafts`` con
``estado='borrador'`` (o ``rechazado`` si los nodos previos abortaron)
y devuelve la URL del editor. NO publica al CMS — eso es Fase 5.
"""

from __future__ import annotations

import structlog

from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.persistence import insertar_draft
from src.pipeline.state import PipelineState

logger = structlog.get_logger(__name__)

EDITOR_URL_TEMPLATE = "https://redactia.local/drafts/{draft_id}"


async def publish_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    motivo = state.get("detect_motivo_aborto") or state.get("research_motivo_aborto")
    medio_id = state["medio_id"]
    run_id = state["run_id"]

    if motivo:
        # Run abortado en un nodo previo. Marcamos el run como rechazado
        # y NO insertamos draft (no hay contenido que persistir).
        async with deps.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
            )
            await conn.execute(
                "UPDATE runs SET estado = 'fallido', finalizado_at = NOW() "
                "WHERE id = $1",
                run_id,
            )
        logger.info("publish_abortado", run_id=str(run_id), motivo=motivo)
        return {**state, "draft_id": None, "editor_url": None}

    estado_draft = (
        "borrador"
        if state.get("review_aprobado") or state.get("requiere_revision_humana")
        else "rechazado"
    )

    async with deps.pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
        )
        draft_id = await insertar_draft(
            conn,
            run_id=run_id,
            medio_id=medio_id,
            titulo=state.get("titulo", ""),
            meta_title=state.get("meta_title"),
            meta_descr=state.get("meta_descr"),
            slug=state.get("slug"),
            cuerpo_md=state.get("cuerpo_md", ""),
            entidades=state.get("entidades", []),
            enlaces_internos=state.get("enlaces_internos", []),
            schema_jsonld=state.get("schema_jsonld", {}),
            estado=estado_draft,
        )

    editor_url = EDITOR_URL_TEMPLATE.format(draft_id=draft_id)
    logger.info(
        "publish_bandeja",
        draft_id=str(draft_id),
        run_id=str(run_id),
        estado=estado_draft,
        editor_url=editor_url,
    )
    return {
        **state,
        "draft_id": draft_id,
        "modo_publish": "bandeja",
        "editor_url": editor_url,
    }
