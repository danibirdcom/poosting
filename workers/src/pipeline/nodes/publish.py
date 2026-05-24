"""Nodo ``publish``: persiste el draft + imagen + linking draft↔entidades.

Fase 3 sólo soporta modo ``bandeja``: inserta en ``drafts`` con
``estado='borrador'`` (o ``rechazado`` si los nodos previos abortaron) y
devuelve la URL del editor. NO publica al CMS — eso es Fase 5.

Operaciones (en orden, mismo connection acquire pero distintos statements;
no transaccional para no bloquear: cada paso es idempotente vía PKs):

1. INSERT en ``drafts`` (trigger sincroniza ``senal_id`` desde ``runs``).
2. Si ``imagen_destacada`` viene de enrich: INSERT en ``imagenes_articulo`` +
   UPDATE ``drafts.imagen_destacada_id`` con el id de la imagen.
3. INSERT en ``draft_entidades`` para cada entidad con ``catalogo_id`` (skip
   las no mapeadas).
4. UPDATE ``runs`` a 'completado' (o 'fallido' si fue rechazado).

El estado final incluye ``draft_id``, ``imagen_destacada_id`` y la URL del
editor.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

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

    imagen_destacada_id: UUID | None = None
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
            entidades=list(state.get("entidades", [])),
            enlaces_internos=list(state.get("enlaces_internos", [])),
            schema_jsonld=dict(state.get("schema_jsonld", {})),
            estado=estado_draft,
        )

        # Imagen destacada (si enrich la trajo).
        imagen = state.get("imagen_destacada")
        if isinstance(imagen, dict) and imagen.get("url"):
            imagen_destacada_id = await _insertar_imagen(
                conn, draft_id=draft_id, medio_id=medio_id, imagen=imagen
            )
            await conn.execute(
                "UPDATE drafts SET imagen_destacada_id = $1 WHERE id = $2",
                imagen_destacada_id,
                draft_id,
            )

        # draft_entidades para cada entidad con catalogo_id mapeado.
        await _insertar_draft_entidades(
            conn,
            draft_id=draft_id,
            medio_id=medio_id,
            entidades=list(state.get("entidades", [])),
        )

        # Marcar el run como completado.
        await conn.execute(
            "UPDATE runs SET estado = 'completado', finalizado_at = NOW() "
            "WHERE id = $1",
            run_id,
        )

    editor_url = EDITOR_URL_TEMPLATE.format(draft_id=draft_id)
    logger.info(
        "publish_bandeja",
        draft_id=str(draft_id),
        run_id=str(run_id),
        estado=estado_draft,
        editor_url=editor_url,
        tiene_imagen=imagen_destacada_id is not None,
    )
    return {
        **state,
        "draft_id": draft_id,
        "modo_publish": "bandeja",
        "editor_url": editor_url,
        "imagen_destacada_id": imagen_destacada_id,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _insertar_imagen(
    conn: Any,
    *,
    draft_id: UUID,
    medio_id: UUID,
    imagen: dict[str, Any],
) -> UUID:
    """Inserta en ``imagenes_articulo`` con la metadata de Pexels.

    fuente='banco_licencia'. Política §6.1: la declaración IA visible se
    deja False (es foto con licencia, no generada). Alt text y pie_foto
    vienen del banco; si no hay alt, se usa un fallback.
    """
    alt = (
        imagen.get("alt_texto")
        or imagen.get("titulo")
        or "Imagen ilustrativa con licencia Pexels"
    )
    pie = f"Foto: {imagen.get('fotografo') or 'Pexels'} / Pexels"
    storage_path = imagen.get("url") or imagen.get("src_landscape") or ""

    image_id = await conn.fetchval(
        """
        INSERT INTO imagenes_articulo (
          draft_id, medio_id, storage_path, url_publica, fuente,
          prompt_usado, modelo_version, c2pa_metadata, synthid_present,
          alt_text, pie_foto, declaracion_ia_visible,
          banco_licencia_id, banco_licencia_tipo
        )
        VALUES ($1, $2, $3, $4, 'banco_licencia',
                NULL, NULL, NULL, FALSE,
                $5, $6, FALSE,
                $7, 'pexels')
        RETURNING id
        """,
        draft_id,
        medio_id,
        storage_path,
        imagen.get("url"),
        alt[:500],
        pie[:500],
        imagen.get("foto_id"),
    )
    return image_id


async def _insertar_draft_entidades(
    conn: Any,
    *,
    draft_id: UUID,
    medio_id: UUID,
    entidades: list[dict[str, Any]],
) -> int:
    """Inserta en ``draft_entidades`` para cada entidad con ``catalogo_id``.

    Las entidades sin catalogo_id (no mapeadas al catálogo) se quedan SOLO en
    el JSONB ``drafts.entidades``. Devuelve el número de filas insertadas.
    """
    insertadas = 0
    for e in entidades:
        cat_id = e.get("catalogo_id")
        if not cat_id:
            continue
        try:
            cat_uuid = UUID(str(cat_id))
        except (ValueError, TypeError):
            continue
        await conn.execute(
            """
            INSERT INTO draft_entidades (draft_id, entidad_id, medio_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (draft_id, entidad_id) DO NOTHING
            """,
            draft_id,
            cat_uuid,
            medio_id,
        )
        insertadas += 1
    return insertadas
