"""Nodo ``research``: recopila fuentes verificables y extrae hechos.

PR A: stub que cumple el contrato. Asume que ``deps.search`` y
``deps.gemini`` están mockeados en tests. En live (sin mocks) lanza
``NotImplementedError`` con mensaje claro.

PR B: implementación real con Brave + Gemini grounding + Haiku NER.

**Hard constraints incluso en el stub:**
- Mínimo 3 fuentes para urgencia ``breaking`` o ``normal``.
- Mínimo 2 fuentes para ``evergreen``.
- Ninguna señal con ``paywall=TRUE`` se incluye en ``hechos_verificados``.
"""

from __future__ import annotations

import structlog

from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.state import Fuente, Hecho, PipelineState

logger = structlog.get_logger(__name__)

MIN_FUENTES_NEWS = 3
MIN_FUENTES_EVERGREEN = 2


async def research_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    if state.get("detect_motivo_aborto"):
        # Detect abortó; research no tiene nada que investigar.
        return state

    tema = state["tema_final"]
    urgencia = state.get("urgencia", "normal")

    # 1. Búsqueda web (mock-amigable).
    resultados = await deps.search.buscar(tema, max_results=10)

    # 2. Filtrar paywall y dominios prohibidos.
    fuentes: list[Fuente] = []
    for r in resultados:
        if r.get("paywall"):
            continue
        fuentes.append(
            Fuente(
                url=r["url"],
                titulo=r.get("titulo"),
                publicado_at=r.get("publicado_at"),
                autoridad_score=r.get("autoridad_score"),
                contenido_md=r.get("contenido_md"),
                dominio=r.get("dominio"),
                paywall=False,
            )
        )

    minimo = MIN_FUENTES_EVERGREEN if urgencia == "evergreen" else MIN_FUENTES_NEWS
    if len(fuentes) < minimo:
        logger.warning(
            "research_fuentes_insuficientes",
            fuentes_disponibles=len(fuentes),
            minimo=minimo,
            urgencia=urgencia,
        )
        return {
            **state,
            "fuentes": fuentes,
            "hechos_verificados": [],
            "entidades": [],
            "research_motivo_aborto": "fuentes_insuficientes",
        }

    # 3. Síntesis de hechos vía Gemini grounding (stub: el cliente mock
    # devuelve hechos preformateados).
    hechos: list[Hecho] = await _sintetizar_hechos(tema, fuentes, deps)

    # 4. NER (stub: cliente mock devuelve entidades preformateadas).
    entidades = await _extraer_entidades(tema, hechos, deps)

    logger.info(
        "research_ok",
        n_fuentes=len(fuentes),
        n_hechos=len(hechos),
        n_entidades=len(entidades),
    )
    return {
        **state,
        "fuentes": fuentes,
        "hechos_verificados": hechos,
        "entidades": entidades,
        "research_motivo_aborto": None,
    }


async def _sintetizar_hechos(
    tema: str, fuentes: list[Fuente], deps: PipelineDeps
) -> list[Hecho]:
    """Stub: pide al cliente gemini que produzca hechos. En live se llama
    al endpoint con ``tools: [{google_search: {}}]``."""
    urls = [f["url"] for f in fuentes if "url" in f]
    prompt = f"Sintetiza los hechos verificables sobre: {tema}\n\nFuentes:\n" + "\n".join(urls)
    raw = await deps.gemini.generar(prompt, modelo="gemini-2.5-flash")
    # Parseo placeholder: en PR B esto valida JSON con esquema Pydantic.
    # En el stub el mock devuelve una lista serializada de forma trivial.
    if not raw:
        return []
    return [
        Hecho(afirmacion=line.strip(), fuentes=urls[:3])
        for line in raw.split("\n")
        if line.strip()
    ]


async def _extraer_entidades(
    tema: str, hechos: list[Hecho], deps: PipelineDeps
) -> list[dict]:
    """Stub: NER vía Haiku. En live se mapea cada entidad al catálogo
    (``entidades_catalogo``) por similitud trigram + alias."""
    afirmaciones = [h["afirmacion"] for h in hechos]
    prompt = "Extrae entidades de:\n" + "\n".join(afirmaciones)
    raw = await deps.claude.generar(prompt, modelo="claude-haiku")
    if not raw:
        return []
    # En el stub asumimos que el mock devuelve líneas "tipo|nombre".
    out: list[dict] = []
    for line in raw.split("\n"):
        if "|" not in line:
            continue
        tipo, nombre = line.split("|", 1)
        out.append({"tipo": tipo.strip(), "nombre": nombre.strip()})
    return out
