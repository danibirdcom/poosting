"""Nodo ``enrich``: SEO + internal linking + JSON-LD + imagen.

Programático (no LLM):
1. Imagen destacada vía banco con licencia (Pexels). Si Pexels falla o no
   devuelve, el draft entra sin imagen (warning, no aborta).
2. Internal linking: vector search sobre ``drafts.embedding`` publicados
   últimos 180 días del mismo medio, cosine sim > 0.7, top 3. Anchor por
   n-grama léxico común con el título del candidato.
3. JSON-LD ``NewsArticle`` (schema.org) con publisher = medio, author =
   redactor, ``about`` = entidades catalogadas.
4. OpenGraph + Twitter cards.
5. Tags CMS = nombres canónicos de entidades.

Persistencia: este nodo NO escribe a BD. ``publish`` toma el estado
enriquecido y persiste ``drafts``, ``imagenes_articulo`` y ``draft_entidades``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.state import EnlaceInterno, PipelineState

logger = structlog.get_logger(__name__)

MAX_ENLACES_INTERNOS = 3
UMBRAL_SIMILITUD_ENLACES = 0.7
VENTANA_ENLACES_DIAS = 180
NGRAM_MIN_PALABRAS = 2
NGRAM_MAX_PALABRAS = 5


async def enrich_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    if state.get("research_motivo_aborto") or state.get("detect_motivo_aborto"):
        return state

    titulo = state.get("titulo", "")
    cuerpo = state.get("cuerpo_md", "")
    entidades: list[dict[str, Any]] = list(state.get("entidades", []))
    medio_id = state["medio_id"]

    # 1. Imagen destacada (banco con licencia, NO IA en Fase 3).
    imagen_destacada = await _buscar_imagen(deps, titulo, entidades)
    imagen_url = imagen_destacada.get("url") if imagen_destacada else None

    # 2. Internal linking via vector search.
    enlaces_internos, cuerpo_con_enlaces = await _internal_linking(
        state, deps, cuerpo, medio_id
    )

    # 3. Author + publisher para JSON-LD.
    author_name, publisher_name = await _cargar_author_publisher(
        state, deps, medio_id
    )

    # 4. JSON-LD NewsArticle.
    schema_jsonld = _build_jsonld(
        state=state,
        entidades=entidades,
        imagen_url=imagen_url,
        author_name=author_name,
        publisher_name=publisher_name,
    )

    # 5. OpenGraph + Twitter cards.
    og_tags = _build_open_graph(state, imagen_url, publisher_name)

    # 6. Tags CMS = nombres canónicos de entidades.
    tags_cms = [e["nombre"] for e in entidades if e.get("nombre")]

    logger.info(
        "enrich_ok",
        n_enlaces=len(enlaces_internos),
        tiene_imagen=imagen_url is not None,
        n_tags=len(tags_cms),
        n_entidades_catalogadas=sum(1 for e in entidades if e.get("catalogo_id")),
    )
    return {
        **state,
        "cuerpo_md": cuerpo_con_enlaces,
        "enlaces_internos": enlaces_internos,
        "schema_jsonld": schema_jsonld,
        "open_graph": og_tags,
        "imagen_destacada": imagen_destacada,
        "imagen_destacada_url": imagen_url,
        "tags_cms": tags_cms,
    }


# ---------------------------------------------------------------------------
# 1. Imagen
# ---------------------------------------------------------------------------
async def _buscar_imagen(
    deps: PipelineDeps, titulo: str, entidades: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Query Pexels con titulo + top 2-3 nombres de entidades.

    Pexels devuelve None ante fallo — el pipeline NO aborta (política §6.1
    permite draft sin imagen destacada, queda como ``requiere_imagen_humana``
    de facto).
    """
    nombres = [e["nombre"] for e in entidades[:3] if e.get("nombre")]
    query = " ".join([titulo[:80], *nombres[:2]]).strip()
    if not query:
        return None
    try:
        return await deps.images.buscar_imagen(query)
    except Exception as err:
        # buscar_imagen NO debería lanzar (PexelsClient cazó errores y devuelve
        # None), pero defensivo: cualquier excepción se loguea sin abortar.
        logger.warning("enrich_imagen_fallo", error=str(err)[:200])
        return None


# ---------------------------------------------------------------------------
# 2. Internal linking
# ---------------------------------------------------------------------------
async def _internal_linking(
    state: PipelineState,
    deps: PipelineDeps,
    cuerpo: str,
    medio_id: UUID,
) -> tuple[list[EnlaceInterno], str]:
    """Devuelve (lista de enlaces, cuerpo con enlaces inline insertados).

    Estrategia:
    1. Embed del título + meta_descr (query corta, representativa).
    2. Cosine search en ``drafts`` con índice HNSW.
    3. Para cada candidato, buscar el n-grama más largo (2-5 palabras) del
       título del candidato presente en el cuerpo. Si no hay match léxico,
       descartar (mejor sin enlace que enlace forzado).
    4. Insertar ``[anchor](url)`` en la primera ocurrencia del n-grama en el
       cuerpo. Cada anchor solo se enlaza una vez (evita auto-canibalización).
    """
    if not cuerpo or deps.embeddings is None:
        return [], cuerpo

    query_text = (
        f"{state.get('titulo', '')} {state.get('meta_descr', '')}".strip()
    )
    if not query_text:
        return [], cuerpo

    vectors = await deps.embeddings.embed([query_text], input_type="query")
    if not vectors:
        return [], cuerpo
    emb_lit = "[" + ",".join(f"{x:.7f}" for x in vectors[0]) + "]"
    distancia_max = 1.0 - UMBRAL_SIMILITUD_ENLACES

    async with deps.pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
        )
        rows = await conn.fetch(
            """
            SELECT id, titulo, slug, cms_url,
                   (embedding <=> $1::vector) AS distancia
              FROM drafts
             WHERE medio_id = $2
               AND embedding IS NOT NULL
               AND publicado_at IS NOT NULL
               AND publicado_at > NOW() - ($3 || ' days')::INTERVAL
               AND (embedding <=> $1::vector) <= $4
             ORDER BY embedding <=> $1::vector ASC
             LIMIT 10
            """,
            emb_lit,
            medio_id,
            str(VENTANA_ENLACES_DIAS),
            distancia_max,
        )

    enlaces: list[EnlaceInterno] = []
    cuerpo_modificado = cuerpo
    anchors_usados: set[str] = set()
    for row in rows:
        if len(enlaces) >= MAX_ENLACES_INTERNOS:
            break
        anchor = _mejor_anchor(row["titulo"] or "", cuerpo_modificado, anchors_usados)
        if anchor is None:
            continue
        url = row["cms_url"] or f"/drafts/{row['id']}"
        # Insertar [anchor](url) en la primera ocurrencia case-insensitive.
        cuerpo_modificado = _reemplazar_primera_ocurrencia(
            cuerpo_modificado, anchor, f"[{anchor}]({url})"
        )
        anchors_usados.add(anchor.lower())
        similitud = 1.0 - float(row["distancia"])
        enlaces.append(
            EnlaceInterno(anchor=anchor, draft_id=str(row["id"]), score=similitud)
        )
    return enlaces, cuerpo_modificado


def _mejor_anchor(
    titulo_candidato: str, cuerpo: str, ya_usados: set[str]
) -> str | None:
    """N-grama más largo (2-5 palabras) del título presente en cuerpo.

    Comparación case-insensitive, ignora puntuación. ``ya_usados`` evita
    reutilizar el mismo anchor en dos enlaces.
    """
    tokens = re.findall(r"\w+", titulo_candidato)
    if not tokens:
        return None
    cuerpo_lower = cuerpo.lower()
    mejor: str | None = None
    for n in range(NGRAM_MAX_PALABRAS, NGRAM_MIN_PALABRAS - 1, -1):
        for i in range(len(tokens) - n + 1):
            frag = " ".join(tokens[i : i + n])
            if frag.lower() in ya_usados:
                continue
            if frag.lower() in cuerpo_lower:
                mejor = _recuperar_caso_original(cuerpo, frag)
                if mejor is not None:
                    return mejor
    return None


def _recuperar_caso_original(cuerpo: str, fragmento: str) -> str | None:
    """Devuelve el fragmento con la capitalización tal cual aparece en cuerpo."""
    m = re.search(re.escape(fragmento), cuerpo, flags=re.IGNORECASE)
    return m.group(0) if m else None


def _reemplazar_primera_ocurrencia(cuerpo: str, anchor: str, reemplazo: str) -> str:
    """Sustituye solo la primera ocurrencia case-insensitive de anchor."""
    m = re.search(re.escape(anchor), cuerpo, flags=re.IGNORECASE)
    if m is None:
        return cuerpo
    return cuerpo[: m.start()] + reemplazo + cuerpo[m.end() :]


# ---------------------------------------------------------------------------
# 3. Author + publisher (para JSON-LD)
# ---------------------------------------------------------------------------
async def _cargar_author_publisher(
    state: PipelineState, deps: PipelineDeps, medio_id: UUID
) -> tuple[str, str]:
    redactor_id = state.get("redactor_id")
    async with deps.pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
        )
        publisher_name = (
            await conn.fetchval("SELECT nombre FROM medios WHERE id = $1", medio_id)
        ) or "el medio"
        author_name = "Redacción"
        if redactor_id is not None:
            row = await conn.fetchrow(
                "SELECT nombre_publico FROM redactores WHERE id = $1", redactor_id
            )
            if row is not None:
                author_name = row["nombre_publico"]
    return author_name, publisher_name


# ---------------------------------------------------------------------------
# 4. JSON-LD
# ---------------------------------------------------------------------------
def _build_jsonld(
    *,
    state: PipelineState,
    entidades: list[dict[str, Any]],
    imagen_url: str | None,
    author_name: str,
    publisher_name: str,
) -> dict[str, Any]:
    now_iso = datetime.now(tz=UTC).isoformat()
    main_url = (
        state.get("cms_url")
        or f"https://redactia.local/drafts/{state.get('run_id', 'pending')}"
    )

    about = [
        {
            "@type": _mapear_tipo_schema(e.get("tipo")),
            "name": e["nombre"],
        }
        for e in entidades
        if e.get("nombre")
    ]

    schema: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": state.get("titulo", ""),
        "description": state.get("meta_descr", ""),
        "datePublished": now_iso,
        "dateModified": now_iso,
        "author": {"@type": "Person", "name": author_name},
        "publisher": {
            "@type": "Organization",
            "name": publisher_name,
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": main_url},
    }
    if imagen_url:
        schema["image"] = [imagen_url]
    if about:
        schema["about"] = about
    return schema


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


# ---------------------------------------------------------------------------
# 5. OpenGraph + Twitter cards
# ---------------------------------------------------------------------------
def _build_open_graph(
    state: PipelineState, imagen_url: str | None, publisher: str
) -> dict[str, str]:
    titulo = state.get("meta_title") or state.get("titulo", "")
    descr = state.get("meta_descr", "")
    og: dict[str, str] = {
        "og:type": "article",
        "og:title": titulo,
        "og:description": descr,
        "og:site_name": publisher,
        "twitter:card": "summary_large_image",
        "twitter:title": titulo,
        "twitter:description": descr,
    }
    if imagen_url:
        og["og:image"] = imagen_url
        og["twitter:image"] = imagen_url
    return og
