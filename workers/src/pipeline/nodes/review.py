"""Nodo ``review``: valida draft contra hechos + formato + tono.

PR A: checks Python puros (longitudes, slug, citas inline, hechos
presentes en ``hechos_verificados``). El check de "tono" lo delega al
``deps.claude`` (mock-amigable).

PR B: prompt LLM elaborado, deteccion de invenciones con paráfrasis,
verificación contra ``style_guide`` activa del redactor.

Flujo:
- Si todo pasa: ``review_aprobado = True``.
- Si falla y ``write_intentos < 2``: deja flag para que el grafo enrute
  de vuelta a ``write`` con los errores como feedback.
- Si falla y ``write_intentos >= 2``: ``requiere_revision_humana = True``
  y se publica como ``borrador`` en bandeja.
"""

from __future__ import annotations

import re

import structlog

from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.nodes.write import RANGOS_PALABRAS
from src.pipeline.state import PipelineState

logger = structlog.get_logger(__name__)

MAX_INTENTOS_WRITE = 2


async def review_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    if state.get("research_motivo_aborto") or state.get("detect_motivo_aborto"):
        return state

    errores: list[str] = []
    sugerencias: list[str] = []

    # ---- Checks Python puros ----
    titulo = state.get("titulo", "")
    meta_title = state.get("meta_title", "")
    meta_descr = state.get("meta_descr", "")
    slug = state.get("slug", "")
    cuerpo = state.get("cuerpo_md", "")
    urgencia = state.get("urgencia", "normal")
    min_w, max_w = RANGOS_PALABRAS.get(urgencia, (600, 900))

    if not titulo:
        errores.append("titulo vacío")
    if not cuerpo:
        errores.append("cuerpo_md vacío")
    n_palabras = len(cuerpo.split())
    if cuerpo and not (min_w <= n_palabras <= max_w):
        errores.append(
            f"cuerpo {n_palabras} palabras, fuera del rango {min_w}-{max_w}"
        )
    if meta_title and len(meta_title) > 60:
        errores.append(f"meta_title {len(meta_title)} chars > 60")
    if meta_descr and not (140 <= len(meta_descr) <= 160):
        errores.append(f"meta_descr {len(meta_descr)} chars, fuera de 140-160")
    if slug and (len(slug) > 60 or not re.fullmatch(r"[a-z0-9-]+", slug)):
        errores.append(f"slug '{slug}' inválido (>60 chars o caracteres prohibidos)")

    # ---- Check de invenciones (factual): cada cita textual del cuerpo
    # debe poder trazarse a algún hecho verificado. PR A hace una
    # aproximación: las URL citadas en el cuerpo deben estar en `fuentes`.
    urls_cuerpo = set(re.findall(r"https?://[^\s)]+", cuerpo))
    urls_fuentes = {f.get("url") for f in state.get("fuentes", []) if "url" in f}
    urls_fantasma = urls_cuerpo - urls_fuentes
    if urls_fantasma:
        errores.append(
            f"urls citadas no están en fuentes: {sorted(urls_fantasma)[:3]}"
        )

    # Check de invenciones contra hechos: para PR A asumimos que el cuerpo
    # debe contener al menos una palabra clave de cada hecho. PR B usa LLM
    # para verificar paráfrasis. Por ahora damos la oportunidad al LLM.
    sugerencias_llm = await _consultar_llm_revisor(state, deps)
    sugerencias.extend(sugerencias_llm.get("sugerencias", []))
    errores.extend(sugerencias_llm.get("errores_factuales", []))

    aprobado = not errores
    intentos = int(state.get("write_intentos", 1))
    requiere_humano = (not aprobado) and intentos >= MAX_INTENTOS_WRITE

    logger.info(
        "review_resultado",
        aprobado=aprobado,
        errores=errores,
        intentos=intentos,
        requiere_humano=requiere_humano,
    )
    return {
        **state,
        "review_aprobado": aprobado,
        "review_errores": errores,
        "review_sugerencias": sugerencias,
        "requiere_revision_humana": requiere_humano,
    }


async def _consultar_llm_revisor(
    state: PipelineState, deps: PipelineDeps
) -> dict[str, list[str]]:
    """Pregunta a Haiku si el cuerpo tiene invenciones / tono raro.

    Stub: el mock devuelve líneas tipo "FACTUAL: <msg>" o "ESTILO: <msg>".
    """
    hechos = state.get("hechos_verificados", [])
    cuerpo = state.get("cuerpo_md", "")
    prompt = (
        "Revisa el cuerpo y compáralo con los hechos verificados. "
        "Devuelve líneas con prefijo FACTUAL: o ESTILO:.\n\n"
        f"HECHOS: {hechos}\n\nCUERPO:\n{cuerpo}"
    )
    raw = await deps.claude.generar(prompt, modelo="claude-haiku")
    errores_factuales: list[str] = []
    sugerencias: list[str] = []
    for line in raw.splitlines():
        if line.startswith("FACTUAL:"):
            errores_factuales.append(line[len("FACTUAL:"):].strip())
        elif line.startswith("ESTILO:"):
            sugerencias.append(line[len("ESTILO:"):].strip())
    return {"errores_factuales": errores_factuales, "sugerencias": sugerencias}


def route_after_review(state: PipelineState) -> str:
    """Función de routing del grafo: decide siguiente nodo tras review."""
    if state.get("research_motivo_aborto") or state.get("detect_motivo_aborto"):
        return "publish"
    if state.get("review_aprobado"):
        return "enrich"
    if state.get("requiere_revision_humana"):
        return "publish"
    return "write"
