"""Nodo ``enrich``: SEO + internal linking + JSON-LD + imagen.

PR A: estructuras vacías + selección de imagen vía ``deps.images``
(mockeado en tests). Internal linking devuelve [] si no hay drafts
publicados todavía.

PR B: vector search real sobre ``drafts.embedding``, generación completa
de NewsArticle schema con `mainEntity` de ``entidades_catalogo``, OG +
Twitter cards.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.state import PipelineState

logger = structlog.get_logger(__name__)

MAX_ENLACES_INTERNOS = 4


async def enrich_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    if state.get("research_motivo_aborto") or state.get("detect_motivo_aborto"):
        return state
    if not state.get("review_aprobado") and not state.get("requiere_revision_humana"):
        # Solo enriquecemos si review aprobó. En modo "requiere humano"
        # también, para que la bandeja tenga el draft completo.
        return state

    titulo = state.get("titulo", "")
    entidades = state.get("entidades", [])

    # 1. Imagen destacada (banco con licencia, NO IA en Fase 3).
    imagen_url = None
    imagen = await deps.images.buscar_imagen(titulo[:100])
    if imagen:
        imagen_url = imagen.get("url")

    # 2. Internal linking — stub. PR B usa vector search.
    enlaces_internos = await _buscar_enlaces_internos(state, deps)

    # 3. JSON-LD NewsArticle.
    schema_jsonld = _build_jsonld(state, entidades)

    # 4. Tags CMS — para PR A simplemente los nombres canónicos.
    tags_cms = [e["nombre"] for e in entidades if "nombre" in e]

    logger.info(
        "enrich_ok",
        n_enlaces=len(enlaces_internos),
        tiene_imagen=imagen_url is not None,
        n_tags=len(tags_cms),
    )
    return {
        **state,
        "enlaces_internos": enlaces_internos,
        "schema_jsonld": schema_jsonld,
        "imagen_destacada_url": imagen_url,
        "tags_cms": tags_cms,
    }


async def _buscar_enlaces_internos(
    state: PipelineState, deps: PipelineDeps
) -> list:
    """Stub: PR B hace vector search sobre drafts publicados últimos 180 días."""
    # Mock-amigable: el test inyecta enlaces vía estado si quiere verificarlos.
    return []


def _build_jsonld(state: PipelineState, entidades: list) -> dict[str, object]:
    """Construye un esqueleto NewsArticle. PR B completa con publisher real."""
    now = datetime.now(tz=UTC).isoformat()
    return {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": state.get("titulo", ""),
        "datePublished": now,
        "dateModified": now,
        "author": {
            "@type": "Person",
            "name": "Redacción Hoy Aragón",  # PR B: nombre del redactor real
        },
        "publisher": {
            "@type": "Organization",
            "name": "Hoy Aragón",  # PR B: nombre del medio real
        },
        "mainEntity": [
            {"@type": _mapear_tipo_schema(e.get("tipo")), "name": e.get("nombre")}
            for e in entidades
            if e.get("nombre")
        ],
    }


def _mapear_tipo_schema(tipo: str | None) -> str:
    if tipo == "persona":
        return "Person"
    if tipo == "organizacion":
        return "Organization"
    if tipo == "lugar":
        return "Place"
    if tipo == "evento":
        return "Event"
    return "Thing"
