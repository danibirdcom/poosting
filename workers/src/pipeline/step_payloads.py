"""Compactadores de input/output para persistencia en ``run_steps``.

Cada nodo del pipeline persiste su entrada y salida en ``run_steps`` para
trazabilidad y auditoría editorial (CLAUDE.md §3.3). El estado completo
contiene blobs grandes (cuerpo_md, contenido_md de fuentes, ejemplos
cargados de BD); persistirlo entero hincharía la BD y haría imposible
revisar runs después. Estos compactadores extraen solo lo relevante:

- Input: metadatos del estado en el momento de entrar al nodo (qué se le
  pidió hacer).
- Output: las claves que el nodo ha escrito (qué entregó), sin duplicar
  blobs que ya viven en otras tablas (drafts.cuerpo_md, fuentes_run).

Los valores deben ser JSON-serializables (asyncpg los persiste como JSONB).
"""

from __future__ import annotations

from typing import Any

from src.pipeline.state import PipelineState

MAX_STR_LEN = 500


def _trunc(s: object) -> str | None:
    """Convierte a str y trunca para evitar persistir blobs."""
    if s is None:
        return None
    txt = str(s)
    if len(txt) <= MAX_STR_LEN:
        return txt
    return txt[:MAX_STR_LEN] + " […]"


def _uuid_str(v: object) -> str | None:
    return str(v) if v is not None else None


def compactar_input(step_nombre: str, state: PipelineState) -> dict[str, Any]:
    """Snapshot ligero del estado al entrar a un nodo."""
    base = {
        "trigger_tipo": state.get("trigger_tipo"),
        "senal_id": _uuid_str(state.get("senal_id")),
        "redactor_id": _uuid_str(state.get("redactor_id")),
        "categoria": state.get("categoria"),
        "tema_input": _trunc(state.get("tema_input")),
    }
    if step_nombre == "detect":
        return base
    if step_nombre == "research":
        return {
            **base,
            "tema_final": _trunc(state.get("tema_final")),
            "angulo": _trunc(state.get("angulo")),
            "urgencia": state.get("urgencia"),
        }
    if step_nombre == "write":
        return {
            "tema_final": _trunc(state.get("tema_final")),
            "angulo": _trunc(state.get("angulo")),
            "urgencia": state.get("urgencia"),
            "n_hechos": len(state.get("hechos_verificados") or []),
            "n_fuentes": len(state.get("fuentes") or []),
            "n_entidades": len(state.get("entidades") or []),
            "redactor_id": _uuid_str(state.get("redactor_id")),
            "intentos_previos": int(state.get("write_intentos") or 0),
        }
    if step_nombre == "review":
        return {
            "titulo": _trunc(state.get("titulo")),
            "cuerpo_palabras": len((state.get("cuerpo_md") or "").split()),
            "write_intentos": int(state.get("write_intentos") or 0),
            "n_hechos": len(state.get("hechos_verificados") or []),
            "n_fuentes": len(state.get("fuentes") or []),
        }
    if step_nombre == "enrich":
        return {
            "titulo": _trunc(state.get("titulo")),
            "n_entidades": len(state.get("entidades") or []),
            "review_aprobado": bool(state.get("review_aprobado")),
            "requiere_revision_humana": bool(state.get("requiere_revision_humana")),
        }
    if step_nombre == "publish":
        return {
            "titulo": _trunc(state.get("titulo")),
            "review_aprobado": bool(state.get("review_aprobado")),
            "requiere_revision_humana": bool(state.get("requiere_revision_humana")),
            "modo_publish": state.get("modo_publish"),
        }
    return base


def compactar_output(step_nombre: str, state: PipelineState) -> dict[str, Any]:
    """Snapshot ligero de lo que el nodo escribió en el estado."""
    if step_nombre == "detect":
        return {
            "tema_final": _trunc(state.get("tema_final")),
            "angulo": _trunc(state.get("angulo")),
            "urgencia": state.get("urgencia"),
            "tipo_run": state.get("tipo_run"),
            "draft_actualizar_id": _uuid_str(state.get("draft_actualizar_id")),
            "motivo_aborto": state.get("detect_motivo_aborto"),
        }
    if step_nombre == "research":
        # Persistimos resumen + listado de URLs y entidades (sin contenido_md
        # completo: eso vive en fuentes_run).
        fuentes = state.get("fuentes") or []
        return {
            "n_fuentes": len(fuentes),
            "urls_fuentes": [f.get("url") for f in fuentes if f.get("url")][:20],
            "hechos_verificados": [
                _trunc(h.get("afirmacion")) for h in (state.get("hechos_verificados") or [])
            ],
            "entidades": [
                {"tipo": e.get("tipo"), "nombre": e.get("nombre")}
                for e in (state.get("entidades") or [])
            ],
            "motivo_aborto": state.get("research_motivo_aborto"),
        }
    if step_nombre == "write":
        return {
            "titulo": _trunc(state.get("titulo")),
            "meta_title": _trunc(state.get("meta_title")),
            "meta_descr": _trunc(state.get("meta_descr")),
            "slug": _trunc(state.get("slug")),
            "cuerpo_palabras": len((state.get("cuerpo_md") or "").split()),
            "write_intentos": int(state.get("write_intentos") or 0),
        }
    if step_nombre == "review":
        return {
            "aprobado": bool(state.get("review_aprobado")),
            "errores": [_trunc(e) for e in (state.get("review_errores") or [])],
            "sugerencias": [_trunc(s) for s in (state.get("review_sugerencias") or [])],
            "requiere_revision_humana": bool(state.get("requiere_revision_humana")),
        }
    if step_nombre == "enrich":
        return {
            "n_enlaces_internos": len(state.get("enlaces_internos") or []),
            "n_tags_cms": len(state.get("tags_cms") or []),
            "imagen_destacada_url": _trunc(state.get("imagen_destacada_url")),
        }
    if step_nombre == "publish":
        return {
            "draft_id": _uuid_str(state.get("draft_id")),
            "modo_publish": state.get("modo_publish"),
            "editor_url": _trunc(state.get("editor_url")),
            "cms_url": _trunc(state.get("cms_url")),
            "cms_id_externo": _trunc(state.get("cms_id_externo")),
        }
    return {}
