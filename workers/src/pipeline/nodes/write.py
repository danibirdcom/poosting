"""Nodo ``write``: redacta el artículo con tono del redactor.

Carga redactor + estilo activo + ejemplos top N (vector search por embedding
del tema) + correcciones recientes desde BD. Renderiza el prompt Jinja2 de
``prompts/write.md`` y pide a Sonnet un JSON estricto.

Salida: ``titulo``, ``meta_title``, ``meta_descr``, ``slug``, ``cuerpo_md``.
``write_intentos`` se incrementa para que review pueda forzar bandeja tras 2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from jinja2 import Template

from src.llm.claude import json_output_kwargs
from src.llm.config import CLAUDE_SONNET_MODEL
from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.state import PipelineState

logger = structlog.get_logger(__name__)


# Rangos por urgencia (CLAUDE.md §5.3 reglas hard).
RANGOS_PALABRAS = {
    "breaking": (400, 600),
    "normal": (600, 900),
    "evergreen": (800, 1000),
}

EJEMPLOS_TOP_N = 4
CORRECCIONES_TOP_N = 20

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "write.md"


def _cargar_template_write() -> Template:
    """Extrae el bloque Jinja2 dentro de ```...``` del archivo write.md.

    El ``.md`` documenta variables y plantilla; aquí solo nos interesa el
    bloque de código entre el primer ``` y el siguiente ```.
    """
    contenido = _PROMPT_PATH.read_text(encoding="utf-8")
    primera = contenido.find("```")
    if primera == -1:
        raise RuntimeError(f"prompts/write.md sin bloque ``` (path: {_PROMPT_PATH})")
    inicio = contenido.find("\n", primera) + 1
    final = contenido.find("```", inicio)
    if final == -1:
        raise RuntimeError("prompts/write.md sin ``` de cierre")
    return Template(contenido[inicio:final])


_TEMPLATE_CACHE: Template | None = None


def _template() -> Template:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        _TEMPLATE_CACHE = _cargar_template_write()
    return _TEMPLATE_CACHE


async def write_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    if state.get("research_motivo_aborto") or state.get("detect_motivo_aborto"):
        return state

    urgencia = state.get("urgencia", "normal")
    min_w, max_w = RANGOS_PALABRAS.get(urgencia, (600, 900))

    ctx = await _construir_contexto(state, deps, min_w, max_w)
    prompt = _template().render(**ctx)

    raw = await deps.claude.generar(
        prompt,
        modelo=CLAUDE_SONNET_MODEL,
        max_tokens=8192,
        **json_output_kwargs(),
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("write_respuesta_no_json", preview=raw[:200])
        data = {}

    intentos = int(state.get("write_intentos", 0)) + 1
    logger.info(
        "write_ok",
        intentos=intentos,
        urgencia=urgencia,
        titulo=str(data.get("titulo", ""))[:80],
        cuerpo_palabras=len(str(data.get("cuerpo_md", "")).split()),
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


# ---------------------------------------------------------------------------
# Construcción del contexto del prompt
# ---------------------------------------------------------------------------
async def _construir_contexto(
    state: PipelineState, deps: PipelineDeps, min_w: int, max_w: int
) -> dict[str, Any]:
    medio_id = state["medio_id"]
    redactor_id = state.get("redactor_id")
    tema = state.get("tema_final", "")

    async with deps.pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
        )
        medio_nombre = await conn.fetchval(
            "SELECT nombre FROM medios WHERE id = $1", medio_id
        )
        redactor_nombre = "redacción"
        style_guide_md = ""
        variante_md: str | None = None
        ejemplos: list[dict[str, Any]] = []
        correcciones: list[dict[str, Any]] = []

        if redactor_id is not None:
            redactor_row = await conn.fetchrow(
                "SELECT nombre_publico FROM redactores WHERE id = $1", redactor_id
            )
            if redactor_row is not None:
                redactor_nombre = redactor_row["nombre_publico"]

            estilo_row = await conn.fetchrow(
                "SELECT guia_estilo_md FROM estilos_redactor "
                "WHERE redactor_id = $1 AND activo = TRUE "
                "ORDER BY version DESC LIMIT 1",
                redactor_id,
            )
            if estilo_row is not None and estilo_row["guia_estilo_md"]:
                style_guide_md = estilo_row["guia_estilo_md"]

            categoria = state.get("categoria")
            if categoria:
                var_row = await conn.fetchrow(
                    "SELECT ajustes_md FROM variantes_tematicas_redactor "
                    "WHERE redactor_id = $1 AND tema_codigo = $2",
                    redactor_id,
                    categoria,
                )
                if var_row is not None:
                    variante_md = var_row["ajustes_md"]

            ejemplos = await _cargar_ejemplos_top_n(
                conn, redactor_id, tema, deps, EJEMPLOS_TOP_N
            )
            correcciones = await _cargar_correcciones_recientes(
                conn, redactor_id, CORRECCIONES_TOP_N
            )

    return {
        "redactor_nombre": redactor_nombre,
        "medio_nombre": medio_nombre or "el medio",
        "style_guide_md": style_guide_md,
        "variante_tematica_md": variante_md,
        "ejemplos": ejemplos,
        "correcciones_recientes": correcciones,
        "hechos": state.get("hechos_verificados") or [],
        "entidades": state.get("entidades") or [],
        "tema_final": tema,
        "angulo": state.get("angulo", "general"),
        "urgencia": state.get("urgencia", "normal"),
        "min_palabras": min_w,
        "max_palabras": max_w,
        "feedback_review_previo": _formatear_feedback(state),
    }


async def _cargar_ejemplos_top_n(
    conn: Any,
    redactor_id: UUID,
    tema: str,
    deps: PipelineDeps,
    n: int,
) -> list[dict[str, Any]]:
    """Vector search en ``ejemplos_redactor`` por embedding del tema.

    Si no hay cliente de embeddings o el redactor no tiene ejemplos con
    embedding, devuelve los más recientes (fallback ordenado por
    ``pegado_at DESC``).
    """
    if deps.embeddings is None:
        rows = await conn.fetch(
            "SELECT titulo, texto_completo FROM ejemplos_redactor "
            "WHERE redactor_id = $1 "
            "ORDER BY pegado_at DESC LIMIT $2",
            redactor_id,
            n,
        )
        return [
            {"titulo": r["titulo"] or "(sin título)", "texto": r["texto_completo"]}
            for r in rows
        ]

    vectors = await deps.embeddings.embed([tema], input_type="query")
    if not vectors:
        return []
    emb_lit = "[" + ",".join(f"{x:.7f}" for x in vectors[0]) + "]"

    rows = await conn.fetch(
        """
        SELECT titulo, texto_completo
          FROM ejemplos_redactor
         WHERE redactor_id = $1
           AND embedding IS NOT NULL
         ORDER BY embedding <=> $2::vector ASC
         LIMIT $3
        """,
        redactor_id,
        emb_lit,
        n,
    )
    return [
        {"titulo": r["titulo"] or "(sin título)", "texto": r["texto_completo"]}
        for r in rows
    ]


async def _cargar_correcciones_recientes(
    conn: Any, redactor_id: UUID, n: int
) -> list[dict[str, Any]]:
    """Lee últimas N correcciones del redactor desde ``correcciones_redactor``.

    El ``diff`` es JSONB con shape ``{section, before, after}``. Aplanamos
    para el prompt.
    """
    rows = await conn.fetch(
        "SELECT diff, categoria FROM correcciones_redactor "
        "WHERE redactor_id = $1 "
        "ORDER BY creado_at DESC LIMIT $2",
        redactor_id,
        n,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        diff = r["diff"] or {}
        before = diff.get("before") if isinstance(diff, dict) else None
        after = diff.get("after") if isinstance(diff, dict) else None
        if not before or not after:
            continue
        out.append(
            {
                "categoria": r["categoria"],
                "before": str(before)[:200],
                "after": str(after)[:200],
            }
        )
    return out


def _formatear_feedback(state: PipelineState) -> str:
    errores = state.get("review_errores") or []
    if not errores:
        return ""
    return "\n".join(f"- {e}" for e in errores)
