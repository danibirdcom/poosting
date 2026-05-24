"""Nodo ``research``: recopila fuentes verificables y extrae hechos.

Pipeline:
1. ``deps.search.buscar(tema)`` — Brave Search API (10 resultados).
2. Filtrar dominios de la tabla ``blacklist_dominios`` ANTES de fetch.
3. Filtrar resultados ``paywall=TRUE``.
4. Para top 5-8, fetch del contenido completo vía httpx si la fuente
   no trae ya ``contenido_md`` (snippet de Brave). User-Agent realista,
   timeout 10s. Errores no detienen el nodo (se loguean y la fuente sigue
   con su snippet o sin contenido).
5. ``deps.gemini.generar`` (Gemini 2.5 Flash) con prompt que pide JSON
   estricto: ``{"hechos": [{"afirmacion", "fuentes": [url, ...]}]}``.
6. NER con Haiku → mapeo trigram contra ``entidades_catalogo``.

Hard constraints:
- Mínimo 3 fuentes válidas para ``breaking``/``normal``, 2 para
  ``evergreen``. Si no se llega, se aborta con
  ``research_motivo_aborto='fuentes_insuficientes'``.
- Ninguna fuente con ``paywall=True`` entra en ``fuentes`` ni en
  ``hechos_verificados`` (riesgo copyright/licencia).
- Dominios de ``blacklist_dominios`` se descartan antes del fetch — no se
  citan ni se incluyen en hechos.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlparse

import structlog
from pydantic import BaseModel, Field, ValidationError

from src.llm.brave import fetch_url_content
from src.llm.config import CLAUDE_HAIKU_MODEL, GEMINI_MODEL
from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.state import Entidad, Fuente, Hecho, PipelineState

logger = structlog.get_logger(__name__)

MIN_FUENTES_NEWS = 3
MIN_FUENTES_EVERGREEN = 2
TOP_FUENTES_PARA_FETCH = 8
UMBRAL_TRIGRAM_SIMILITUD = 0.4


# ---------------------------------------------------------------------------
# Schemas de salida estrictos
# ---------------------------------------------------------------------------
class HechoLLM(BaseModel):
    afirmacion: str = Field(min_length=3, max_length=2000)
    fuentes: list[str] = Field(default_factory=list)


class GeminiHechosOutput(BaseModel):
    hechos: list[HechoLLM] = Field(default_factory=list)


class EntidadLLM(BaseModel):
    tipo: str  # validado posteriormente: persona|organizacion|lugar|evento
    nombre: str = Field(min_length=1, max_length=200)


class NERHaikuOutput(BaseModel):
    entidades: list[EntidadLLM] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Nodo principal
# ---------------------------------------------------------------------------
async def research_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    if state.get("detect_motivo_aborto"):
        return state

    tema = state["tema_final"]
    urgencia = state.get("urgencia", "normal")
    medio_id = state["medio_id"]
    senal_id = state.get("senal_id")

    # 1. Búsqueda
    resultados = await deps.search.buscar(tema, max_results=10)

    # 2. Cargar blacklist
    blacklist = await _cargar_blacklist(deps)

    # 3. Si venimos de una señal y NO es paywall, su url_origen entra como
    # fuente prioritaria (la fuente que detonó el run). Si paywall=TRUE, se
    # excluye explícitamente — la señal sirvió para detectar el tema pero
    # NO puede citarse en el artículo (copyright/licencia).
    fuentes: list[Fuente] = []
    if senal_id is not None:
        senal_row = await _cargar_senal_como_fuente(deps, medio_id, senal_id)
        if senal_row is not None and senal_row["url_origen"]:
            url = senal_row["url_origen"]
            dominio = (_dominio_de(url) or "").lower()
            if senal_row["paywall"]:
                logger.info(
                    "research_senal_paywall_excluida",
                    url=url[:120],
                    senal_id=str(senal_id),
                )
            elif dominio in blacklist:
                logger.info(
                    "research_senal_blacklist", url=url[:120], dominio=dominio
                )
            else:
                # Placeholder de contenido_md para evitar fetch HTTP en el
                # paso 5 (la señal solo aporta URL/título; el cuerpo se
                # enriquece luego si hace falta).
                fuentes.append(
                    Fuente(
                        url=url,
                        titulo=senal_row["termino"],
                        publicado_at=None,
                        autoridad_score=None,
                        contenido_md=f"Señal detectada: {senal_row['termino']}",
                        dominio=dominio or None,
                        paywall=False,
                    )
                )

    # 4. Filtrar paywall + blacklist en resultados de búsqueda
    for r in resultados:
        if r.get("paywall"):
            continue
        url = r.get("url")
        if not url:
            continue
        dominio = (r.get("dominio") or _dominio_de(url) or "").lower()
        if dominio in blacklist:
            logger.info(
                "research_blacklist_descartada", dominio=dominio, url=url[:120]
            )
            continue
        fuentes.append(
            Fuente(
                url=url,
                titulo=r.get("titulo"),
                publicado_at=r.get("publicado_at"),
                autoridad_score=r.get("autoridad_score"),
                contenido_md=r.get("contenido_md"),
                dominio=dominio or None,
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

    # 4. Fetch para top N en paralelo — solo si la fuente no trae contenido_md.
    sin_contenido = [
        f for f in fuentes[:TOP_FUENTES_PARA_FETCH]
        if not f.get("contenido_md") and f.get("url")
    ]
    if sin_contenido:
        bodies = await asyncio.gather(
            *(fetch_url_content(f["url"]) for f in sin_contenido),
            return_exceptions=False,
        )
        for f, body in zip(sin_contenido, bodies, strict=True):
            if body:
                f["contenido_md"] = body[:10_000]

    # 5. Síntesis de hechos vía Gemini
    hechos = await _sintetizar_hechos(tema, fuentes, deps)

    # 6. NER + mapeo al catálogo
    entidades = await _extraer_y_mapear_entidades(hechos, deps, medio_id)

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


# ---------------------------------------------------------------------------
# Sub-pasos
# ---------------------------------------------------------------------------
async def _cargar_blacklist(deps: PipelineDeps) -> set[str]:
    """Carga ``blacklist_dominios`` (catálogo global, sin medio_id)."""
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch("SELECT dominio FROM blacklist_dominios")
    return {row["dominio"].lower() for row in rows if row["dominio"]}


async def _cargar_senal_como_fuente(
    deps: PipelineDeps, medio_id: object, senal_id: object
) -> dict[str, Any] | None:
    async with deps.pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
        )
        row = await conn.fetchrow(
            "SELECT url_origen, paywall, termino FROM senales WHERE id = $1",
            senal_id,
        )
    return dict(row) if row is not None else None


async def _sintetizar_hechos(
    tema: str, fuentes: list[Fuente], deps: PipelineDeps
) -> list[Hecho]:
    if not fuentes:
        return []

    fuentes_blob = "\n\n".join(
        f"[{i+1}] {f.get('url')}\nTítulo: {f.get('titulo') or '(sin título)'}\n"
        f"Extracto:\n{(f.get('contenido_md') or '')[:2000]}"
        for i, f in enumerate(fuentes[:TOP_FUENTES_PARA_FETCH])
    )
    prompt = (
        "Eres un verificador de hechos. Sintetiza los hechos verificables "
        "sobre el tema, citando SOLO las fuentes proporcionadas (por URL). "
        "Devuelve JSON ESTRICTO con la forma:\n"
        '{"hechos": [{"afirmacion": "...", "fuentes": ["url1", "url2"]}, ...]}\n'
        "No inventes hechos no respaldados por al menos una fuente.\n\n"
        f"TEMA: {tema}\n\nFUENTES:\n{fuentes_blob}\n\nResponde SOLO el JSON."
    )
    raw = await deps.gemini.generar(prompt, modelo=GEMINI_MODEL)
    if not raw or not raw.strip():
        return []

    parsed = _parse_json_estricto(raw)
    if parsed is None:
        logger.warning("research_gemini_no_json", preview=raw[:200])
        return []

    try:
        out = GeminiHechosOutput.model_validate(parsed)
    except ValidationError as err:
        logger.warning("research_gemini_schema_invalido", error=str(err))
        return []

    # Solo aceptamos hechos cuyas URLs citadas estén entre las fuentes válidas.
    urls_validas = {f.get("url") for f in fuentes}
    hechos_final: list[Hecho] = []
    for h in out.hechos:
        fuentes_ok = [u for u in h.fuentes if u in urls_validas]
        if not fuentes_ok:
            continue
        hechos_final.append(Hecho(afirmacion=h.afirmacion, fuentes=fuentes_ok))
    return hechos_final


async def _extraer_y_mapear_entidades(
    hechos: list[Hecho], deps: PipelineDeps, medio_id: object
) -> list[Entidad]:
    if not hechos:
        return []

    afirmaciones = "\n".join(f"- {h['afirmacion']}" for h in hechos)
    prompt = (
        "Extrae entidades nombradas (personas, organizaciones, lugares, "
        "eventos) del siguiente texto. Devuelve JSON ESTRICTO:\n"
        '{"entidades": [{"tipo": "persona|organizacion|lugar|evento", "nombre": "..."}]}\n\n'
        f"TEXTO:\n{afirmaciones}\n\nResponde SOLO el JSON."
    )
    raw = await deps.claude.generar(prompt, modelo=CLAUDE_HAIKU_MODEL)
    if not raw or not raw.strip():
        return []

    entidades_brutas = _parsear_entidades(raw)
    if not entidades_brutas:
        return []

    # Mapeo trigram contra entidades_catalogo (global + medio).
    out: list[Entidad] = []
    async with deps.pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
        )
        for e in entidades_brutas:
            match = await conn.fetchrow(
                """
                SELECT id, nombre_canonico, contexto_md,
                       GREATEST(
                         similarity(nombre_canonico, $1),
                         COALESCE(
                           (SELECT MAX(similarity(a, $1))
                              FROM unnest(aliases) a),
                           0
                         )
                       ) AS sim
                  FROM entidades_catalogo
                 WHERE activo = TRUE
                 ORDER BY sim DESC
                 LIMIT 1
                """,
                e.nombre,
            )
            tipo_norm = (
                e.tipo
                if e.tipo in {"persona", "organizacion", "lugar", "evento"}
                else "organizacion"
            )
            mapped: Entidad = {"tipo": tipo_norm, "nombre": e.nombre}  # type: ignore[typeddict-item]
            if match is not None and float(match["sim"]) >= UMBRAL_TRIGRAM_SIMILITUD:
                mapped["catalogo_id"] = str(match["id"])
                mapped["nombre"] = match["nombre_canonico"]
                if match["contexto_md"]:
                    mapped["contexto_md"] = match["contexto_md"]
            out.append(mapped)
    return out


# ---------------------------------------------------------------------------
# Helpers de parseo
# ---------------------------------------------------------------------------
def _parse_json_estricto(raw: str) -> dict[str, Any] | None:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:].lstrip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _parsear_entidades(raw: str) -> list[EntidadLLM]:
    """Acepta dos formatos: JSON estricto del schema, o el formato legacy
    ``tipo|nombre`` separado por líneas (mantiene compatibilidad con tests
    de PR A que pasan respuestas como ``persona|Jorge Azcón``).
    """
    parsed = _parse_json_estricto(raw)
    if parsed is not None:
        try:
            return list(NERHaikuOutput.model_validate(parsed).entidades)
        except ValidationError as err:
            logger.warning("research_ner_schema_invalido", error=str(err))
            return []
    out: list[EntidadLLM] = []
    for line in raw.splitlines():
        if "|" not in line:
            continue
        tipo, nombre = line.split("|", 1)
        tipo = tipo.strip().lower()
        nombre = nombre.strip()
        if not nombre or not tipo:
            continue
        try:
            out.append(EntidadLLM(tipo=tipo, nombre=nombre))
        except ValidationError:
            continue
    return out


def _dominio_de(url: str) -> str | None:
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host
