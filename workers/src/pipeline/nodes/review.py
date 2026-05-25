"""Nodo ``review``: valida draft contra hechos + formato + estilo.

Checks Python puros (rápidos, sin LLM):
- Longitud del cuerpo según urgencia (rangos en ``write.RANGOS_PALABRAS``).
- Slug kebab-case, ≤60, sin stopwords.
- Meta title 30-60 chars, DISTINTO del titulo (Discover).
- Meta descr 140-160 chars.
- ≥2 citas inline a fuentes (URLs únicas presentes en ``state.fuentes``).
- Markdown sin H1 (los H1 chocan con el título de la página); H2 ok.

Checks LLM (Haiku, modelo desde ``CLAUDE_HAIKU_MODEL``):
- Cada afirmación factual del cuerpo está respaldada por ``hechos_verificados``.
- Personas reales mencionadas pertenecen al catálogo (``entidades_catalogo``).
- Tono coherente con el ``style_guide`` del redactor.

Routing:
- Si aprobado → ``enrich``.
- Si falla 1ª vez → ``write`` (retry con ``write_intentos < MAX_INTENTOS_WRITE``).
- Si falla 2ª vez → ``state.requiere_revision_humana = True`` y route a
  ``enrich`` (queremos que el draft tenga SEO completo aunque vaya a bandeja
  para revisión humana).
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import structlog
from jinja2 import Template
from pydantic import BaseModel, Field, ValidationError

from src.llm._json_utils import parse_json_tolerante
from src.llm.claude import json_output_kwargs
from src.llm.config import CLAUDE_HAIKU_MODEL
from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.nodes.write import RANGOS_PALABRAS
from src.pipeline.state import PipelineState

logger = structlog.get_logger(__name__)

MAX_INTENTOS_WRITE = 2
MIN_CITAS_INLINE = 2

# Stopwords ES para validar slug.
STOPWORDS_SLUG = {
    "de",
    "la",
    "el",
    "los",
    "las",
    "y",
    "o",
    "con",
    "en",
    "para",
    "por",
    "un",
    "una",
    "del",
    "al",
    "que",
    "se",
    "su",
    "sus",
}

# Medios competidores que NO deben citarse nominalmente en el cuerpo.
# Lista hard-coded por ahora; en Fase 4 movemos a tabla `medios_competencia`
# configurable por medio (la lista varía por cliente). Ver CLAUDE.md §5.4.
# Las claves están en formato normalizado (lowercase + sin acentos).
LISTA_MEDIOS_COMPETIDORES: frozenset[str] = frozenset(
    {
        "el periodico de aragon",
        "el espanol",
        "heraldo de aragon",
        "heraldo",
        "aragon digital",
        "20minutos",
        "20 minutos",
        "el pais",
        "el mundo",
        "abc",
        "la razon",
        "cartv",  # TV pública aragonesa, parcialmente competencia
    }
)

# Nombres que SÍ se pueden citar nominalmente (agencias + institucionales).
# El propio medio destino se añade dinámicamente desde state.medio_nombre.
# Esta lista no se usa para validar (solo se filtra por LISTA_MEDIOS_*); la
# documentamos aquí para que el lector entienda la política completa.
EXCEPCIONES_PERMITIDAS: frozenset[str] = frozenset(
    {
        "efe",
        "europa press",
        "reuters",
        "ap",
        "afp",
        "ayuntamiento de zaragoza",
        "dga",
        "gobierno de aragon",
        "gobierno de espana",
        "boe",
        "boa",
        "ministerio",
        "ine",
    }
)


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "review.md"


def _cargar_template_review() -> Template:
    contenido = _PROMPT_PATH.read_text(encoding="utf-8")
    primera = contenido.find("```")
    if primera == -1:
        raise RuntimeError(f"prompts/review.md sin bloque ``` (path: {_PROMPT_PATH})")
    inicio = contenido.find("\n", primera) + 1
    final = contenido.find("```", inicio)
    if final == -1:
        raise RuntimeError("prompts/review.md sin ``` de cierre")
    return Template(contenido[inicio:final])


_TEMPLATE_CACHE: Template | None = None


def _template() -> Template:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        _TEMPLATE_CACHE = _cargar_template_review()
    return _TEMPLATE_CACHE


# ---------------------------------------------------------------------------
# Schema de salida del LLM revisor
# ---------------------------------------------------------------------------
class ReviewLLMOutput(BaseModel):
    errores_factuales: list[str] = Field(default_factory=list)
    errores_estilo: list[str] = Field(default_factory=list)
    sugerencias: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Nodo principal
# ---------------------------------------------------------------------------
async def review_node(state: PipelineState, deps: PipelineDeps) -> PipelineState:
    if state.get("research_motivo_aborto") or state.get("detect_motivo_aborto"):
        return state

    errores: list[str] = []
    sugerencias: list[str] = []

    titulo = state.get("titulo", "")
    meta_title = state.get("meta_title", "")
    meta_descr = state.get("meta_descr", "")
    slug = state.get("slug", "")
    cuerpo = state.get("cuerpo_md", "")
    urgencia = state.get("urgencia", "normal")
    min_w, max_w = RANGOS_PALABRAS.get(urgencia, (600, 900))

    errores.extend(_checks_estructura(titulo, meta_title, meta_descr, slug, cuerpo))
    errores.extend(_checks_longitud(cuerpo, min_w, max_w))
    errores.extend(_checks_markdown(cuerpo))
    err_citas, sug_citas = _checks_citas(cuerpo, state)
    errores.extend(err_citas)
    sugerencias.extend(sug_citas)

    # Política editorial (CLAUDE.md §5.4): el cuerpo no nombra a medios
    # competidores. Defensa en código por si write se salta la regla del
    # prompt. Bloqueante para retry: si write nombra a un competidor, lo
    # devolvemos a write con feedback claro.
    medio_nombre = await _cargar_medio_nombre(state, deps)
    err_competidores = _detectar_menciones_competidores(cuerpo, medio_nombre)
    errores.extend(err_competidores)

    # LLM check (factual + estilo).
    style_guide_md = await _cargar_style_guide(state, deps)
    llm_resultado = await _consultar_llm_revisor(state, deps, style_guide_md)
    errores.extend(llm_resultado.errores_factuales)
    errores.extend(llm_resultado.errores_estilo)
    sugerencias.extend(llm_resultado.sugerencias)

    aprobado = not errores
    intentos = int(state.get("write_intentos", 1))
    requiere_humano = (not aprobado) and intentos >= MAX_INTENTOS_WRITE

    logger.info(
        "review_resultado",
        aprobado=aprobado,
        n_errores=len(errores),
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


# ---------------------------------------------------------------------------
# Checks Python
# ---------------------------------------------------------------------------
def _checks_estructura(
    titulo: str, meta_title: str, meta_descr: str, slug: str, cuerpo: str
) -> list[str]:
    out: list[str] = []
    if not titulo:
        out.append("titulo vacío")
    elif not (30 <= len(titulo) <= 100):
        out.append(f"titulo {len(titulo)} chars, fuera de 30-100")

    if not cuerpo:
        out.append("cuerpo_md vacío")

    if meta_title:
        if not (30 <= len(meta_title) <= 60):
            out.append(f"meta_title {len(meta_title)} chars, fuera de 30-60")
        if meta_title.strip() == titulo.strip() and titulo:
            out.append("meta_title idéntico al titulo (debe variar para Discover)")
    else:
        out.append("meta_title vacío")

    if meta_descr:
        if not (140 <= len(meta_descr) <= 160):
            out.append(f"meta_descr {len(meta_descr)} chars, fuera de 140-160")
    else:
        out.append("meta_descr vacío")

    if slug:
        if len(slug) > 60:
            out.append(f"slug '{slug}' ({len(slug)} chars) > 60")
        elif not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
            out.append(f"slug '{slug}' no es kebab-case válido")
        else:
            palabras_slug = slug.split("-")
            stopwords_encontradas = [w for w in palabras_slug if w in STOPWORDS_SLUG]
            if stopwords_encontradas:
                out.append(f"slug contiene stopwords: {sorted(set(stopwords_encontradas))}")
    else:
        out.append("slug vacío")

    return out


def _checks_longitud(cuerpo: str, min_w: int, max_w: int) -> list[str]:
    if not cuerpo:
        return []
    n = len(cuerpo.split())
    if not (min_w <= n <= max_w):
        return [f"cuerpo {n} palabras, fuera del rango {min_w}-{max_w}"]
    return []


def _checks_markdown(cuerpo: str) -> list[str]:
    out: list[str] = []
    # No H1 (chocan con titulo de la página).
    for linea in cuerpo.splitlines():
        if re.match(r"^#\s+\S", linea):  # un solo # + espacio + contenido
            out.append("cuerpo contiene H1 ('# ...'); usa H2 ('## ...') o inferior")
            break
    return out


def _checks_citas(cuerpo: str, state: PipelineState) -> tuple[list[str], list[str]]:
    """≥2 citas inline a URLs únicas, todas presentes en state.fuentes.

    Devuelve ``(errores_bloqueantes, sugerencias)``. URLs técnicas de
    twitter/x.com NO bloquean el draft (sugerencia, no error) — es un
    problema cosmético que no justifica disparar requiere_revision_humana
    cuando el resto del draft está correcto.
    """
    errores: list[str] = []
    sugerencias: list[str] = []
    urls_cuerpo = set(re.findall(r"https?://[^\s)\]]+", cuerpo))
    urls_fuentes = {
        (f.get("url") or "").rstrip("/") for f in state.get("fuentes", []) if f.get("url")
    }
    urls_cuerpo_norm = {u.rstrip("/") for u in urls_cuerpo}

    fantasma = urls_cuerpo_norm - urls_fuentes
    fantasma_no_twitter = {u for u in fantasma if "twitter.com" not in u and "x.com" not in u}
    if fantasma_no_twitter:
        errores.append(f"urls citadas no están en fuentes: {sorted(fantasma_no_twitter)[:3]}")

    urls_x = {u for u in urls_cuerpo if "twitter.com" in u or "x.com" in u}
    if urls_x:
        sugerencias.append(
            "el cuerpo cita URLs técnicas de X/Twitter; refiérete a ellas como "
            "'una publicación en X' (no la URL)"
        )

    citas_validas = urls_cuerpo_norm & urls_fuentes
    if len(citas_validas) < MIN_CITAS_INLINE:
        errores.append(
            f"solo {len(citas_validas)} citas inline a fuentes; se requieren ≥{MIN_CITAS_INLINE}"
        )

    return errores, sugerencias


# ---------------------------------------------------------------------------
# LLM checker
# ---------------------------------------------------------------------------
async def _cargar_style_guide(state: PipelineState, deps: PipelineDeps) -> str:
    redactor_id = state.get("redactor_id")
    if redactor_id is None:
        return ""
    async with deps.pool.acquire() as conn:
        await conn.execute(
            "SELECT set_config('app.medio_actual', $1, false)", str(state["medio_id"])
        )
        row = await conn.fetchrow(
            "SELECT guia_estilo_md FROM estilos_redactor "
            "WHERE redactor_id = $1 AND activo = TRUE "
            "ORDER BY version DESC LIMIT 1",
            redactor_id,
        )
    return (row["guia_estilo_md"] or "") if row else ""


async def _consultar_llm_revisor(
    state: PipelineState, deps: PipelineDeps, style_guide_md: str
) -> ReviewLLMOutput:
    """Pregunta a Haiku si el cuerpo tiene invenciones / desviaciones.

    Tolera salidas no-JSON (fallback al parser legacy ``FACTUAL:`` /
    ``ESTILO:``) para retrocompat con tests del PR A.
    """
    cuerpo = state.get("cuerpo_md", "")
    titulo = state.get("titulo", "")
    if not cuerpo:
        return ReviewLLMOutput()

    entidades_nombres = [
        str(e.get("nombre")) for e in (state.get("entidades") or []) if e.get("nombre")
    ]
    ctx = {
        "hechos": state.get("hechos_verificados") or [],
        "entidades_catalogo": entidades_nombres,
        "style_guide_md": style_guide_md,
        "titulo": titulo,
        "cuerpo_md": cuerpo,
    }
    prompt = _template().render(**ctx)

    raw = await deps.claude.generar(
        prompt,
        modelo=CLAUDE_HAIKU_MODEL,
        max_tokens=2048,
        **json_output_kwargs(),
    )
    if not raw or not raw.strip():
        return ReviewLLMOutput()

    parsed = parse_json_tolerante(raw)
    if parsed is not None:
        try:
            return ReviewLLMOutput.model_validate(parsed)
        except ValidationError as err:
            logger.warning("review_llm_schema_invalido", error=str(err))

    return _parse_legacy(raw)


# ---------------------------------------------------------------------------
# Política editorial: detección de menciones a medios competidores
# ---------------------------------------------------------------------------
def _quitar_acentos(s: str) -> str:
    descompuesto = unicodedata.normalize("NFD", s)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _normalizar_texto(s: str) -> str:
    """lowercase + sin acentos. Preserva espacios y guiones para que las
    comparaciones por word-boundary funcionen (a diferencia del normalizador
    legacy, que colapsaba todo a alfanumérico).
    """
    return _quitar_acentos(s).lower()


def _detectar_menciones_competidores(cuerpo: str, medio_nombre: str = "") -> list[str]:
    """Devuelve errores por cada medio competidor nombrado en el cuerpo.

    Política (CLAUDE.md §5.4): el cuerpo no cita a medios competidores por
    su nombre, ni en el anchor de un enlace ni en el texto narrativo. Las
    URLs (``https://...``) se ignoran: el dominio del competidor en el path
    NO cuenta como mención. El nombre del medio destino (``medio_nombre``)
    se excluye dinámicamente — auto-referencia permitida.

    Devuelve lista de errores en español, listos para añadirse a
    ``state.review_errores`` (bloqueantes para retry).
    """
    if not cuerpo:
        return []

    # Quitamos URLs antes de buscar: el dominio en el path no es mención.
    cuerpo_sin_urls = re.sub(r"https?://\S+", " ", cuerpo)
    texto_norm = _normalizar_texto(cuerpo_sin_urls)

    auto_ref = _normalizar_texto((medio_nombre or "").strip())
    errores: list[str] = []
    encontrados: set[str] = set()
    for competidor in LISTA_MEDIOS_COMPETIDORES:
        if auto_ref and competidor == auto_ref:
            continue
        # Word boundaries para evitar matches parciales ("abc" en "abcdef",
        # "ap" en "apenas", etc.). \b funciona con [a-z0-9_].
        patron = r"\b" + re.escape(competidor) + r"\b"
        if re.search(patron, texto_norm) and competidor not in encontrados:
            encontrados.add(competidor)
            errores.append(
                f"atribución nominal a medio competidor en el cuerpo: "
                f"'{competidor}' (política: enlazar sin nombrar al medio)"
            )
    return errores


async def _cargar_medio_nombre(state: PipelineState, deps: PipelineDeps) -> str:
    medio_id = state.get("medio_id")
    if medio_id is None:
        return ""
    async with deps.pool.acquire() as conn:
        await conn.execute("SELECT set_config('app.medio_actual', $1, false)", str(medio_id))
        row = await conn.fetchval("SELECT nombre FROM medios WHERE id = $1", medio_id)
    return row or ""


def _parse_legacy(raw: str) -> ReviewLLMOutput:
    factual: list[str] = []
    estilo: list[str] = []
    for line in raw.splitlines():
        if line.startswith("FACTUAL:"):
            factual.append(line[len("FACTUAL:") :].strip())
        elif line.startswith("ESTILO:"):
            estilo.append(line[len("ESTILO:") :].strip())
    return ReviewLLMOutput(errores_factuales=factual, errores_estilo=estilo)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def route_after_review(state: PipelineState) -> str:
    """Decide siguiente nodo tras review.

    - abort previo → publish (corto-circuito).
    - aprobado → enrich.
    - rechazado con intentos < MAX → write (retry).
    - rechazado con intentos >= MAX → enrich (queremos SEO completo aunque
      vaya a bandeja para revisión humana).
    """
    if state.get("research_motivo_aborto") or state.get("detect_motivo_aborto"):
        return "publish"
    if state.get("review_aprobado"):
        return "enrich"
    if state.get("requiere_revision_humana"):
        return "enrich"
    return "write"
