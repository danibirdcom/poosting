"""Nodo ``write``: redacta el artículo con tono del redactor.

PR A: stub que pide al ``deps.claude`` un JSON con los campos esperados.
PR B: prompt real desde ``prompts/write.md`` con style_guide y ejemplos
RAG. Validación de longitudes y formato Markdown.
"""

from __future__ import annotations

import json

import structlog

from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.state import PipelineState

logger = structlog.get_logger(__name__)

# Rangos por urgencia (CLAUDE.md §5.3 reglas hard).
RANGOS_PALABRAS = {
    "breaking": (400, 600),
    "normal": (600, 900),
    "evergreen": (800, 1000),
}


async def write_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    if state.get("research_motivo_aborto") or state.get("detect_motivo_aborto"):
        return state

    urgencia = state.get("urgencia", "normal")
    min_w, max_w = RANGOS_PALABRAS.get(urgencia, (600, 900))

    prompt = _build_prompt(state, min_w, max_w)
    raw = await deps.claude.generar(prompt, modelo="claude-sonnet")

    # En live, el LLM debe devolver JSON con los campos esperados. El stub
    # delega esa garantía al mock — el caller del test inyecta respuestas
    # ya formadas.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("write_respuesta_no_json", preview=raw[:200])
        # Devolvemos placeholders; review marcará como inválido y forzará retry.
        data = {}

    intentos = int(state.get("write_intentos", 0)) + 1
    logger.info(
        "write_ok",
        intentos=intentos,
        titulo=data.get("titulo", "")[:80],
        cuerpo_palabras=len(data.get("cuerpo_md", "").split()),
    )
    return {
        **state,
        "titulo": data.get("titulo", ""),
        "meta_title": data.get("meta_title", ""),
        "meta_descr": data.get("meta_descr", ""),
        "slug": data.get("slug", ""),
        "cuerpo_md": data.get("cuerpo_md", ""),
        "write_intentos": intentos,
    }


def _build_prompt(state: PipelineState, min_w: int, max_w: int) -> str:
    """Stub del prompt. PR B usa Jinja2 desde ``prompts/write.md``."""
    tema = state.get("tema_final", "")
    angulo = state.get("angulo", "")
    hechos = state.get("hechos_verificados", [])
    entidades = state.get("entidades", [])

    feedback = ""
    if state.get("review_errores"):
        feedback = "\n\n<feedback_review_previo>\n" + "\n".join(
            f"- {e}" for e in state["review_errores"]
        ) + "\n</feedback_review_previo>"

    return (
        f"Tema: {tema}\nÁngulo: {angulo}\n"
        f"Longitud: {min_w}-{max_w} palabras.\n"
        f"Hechos verificados:\n{json.dumps(hechos, ensure_ascii=False)}\n"
        f"Entidades:\n{json.dumps(entidades, ensure_ascii=False)}"
        f"{feedback}\n"
        "Devuelve JSON con: titulo, meta_title, meta_descr, slug, cuerpo_md."
    )
