"""Tests críticos del PR B: write longitud, enrich JSON-LD, review happy,
publish persistencia con sincronización de senal_id.

Mismo patrón que test_pipeline_mocked.py: BD real (skipea sin DATABASE_URL),
LLMs mockeados con FakeLLM.
"""

from __future__ import annotations

import json
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from src.pipeline import build_graph
from src.pipeline.nodes.deps import PipelineDeps
from src.pipeline.nodes.enrich import _build_jsonld, _mapear_tipo_schema
from src.pipeline.nodes.review import review_node
from src.pipeline.nodes.write import RANGOS_PALABRAS
from src.pipeline.persistence import crear_run
from src.pipeline.state import PipelineState
from src.trends.persistence import close_pool, get_pool

from .fakes import FakeImageBank, FakeLLM, FakeSearch, fuente_falsa

APP_DSN = os.environ.get("DATABASE_URL", "")
ADMIN_DSN = os.environ.get("DATABASE_URL_ADMIN", APP_DSN)
_skip_sin_db = pytest.mark.skipif(not APP_DSN, reason="DATABASE_URL no definido")


META_DESCR_OK = (
    "Resumen SEO de longitud apropiada para el artículo de prueba del "
    "pipeline B sobre los presupuestos autonómicos de Aragón en sanidad y obras."
)
assert 140 <= len(META_DESCR_OK) <= 160, f"len={len(META_DESCR_OK)}"


def _detect_json(tema: str = "Tema X", urgencia: str = "evergreen") -> str:
    return json.dumps(
        {"tema_final": tema, "angulo": "general", "urgencia": urgencia},
        ensure_ascii=False,
    )


def _write_json(
    titulo: str,
    cuerpo: str,
    slug: str = "tema-x-presupuestos-aragon",
    meta_title_extra: str = "análisis",
) -> str:
    """JSON estricto que un Sonnet bien comportado devuelve. meta_title
    distinto del titulo (30-60 chars)."""
    base = titulo[:35] if len(titulo) > 35 else titulo
    return json.dumps(
        {
            "titulo": titulo,
            "meta_title": f"{base} | {meta_title_extra}",
            "meta_descr": META_DESCR_OK,
            "slug": slug,
            "cuerpo_md": cuerpo,
        },
        ensure_ascii=False,
    )


def _cuerpo_para_rango(urls: list[str], min_w: int, max_w: int) -> str:
    """Genera un cuerpo entre min_w y max_w palabras con ≥2 URLs inline."""
    parrafo = (
        "El Gobierno de Aragón presenta los presupuestos para 2026 "
        "con un incremento del cinco por ciento respecto al año anterior, "
        "destacando partidas para sanidad y educación. "
    )
    target = (min_w + max_w) // 2
    cuerpo = ""
    while len(cuerpo.split()) < target:
        cuerpo += parrafo
    sufijo = "\n\n".join(f"Ver: {u}" for u in urls[:3])
    cuerpo += "\n\n" + sufijo
    palabras = cuerpo.split()
    if len(palabras) > max_w:
        palabras = palabras[: max_w - 8]
        cuerpo = " ".join(palabras) + "\n\n" + sufijo
    return cuerpo


async def _crear_medio(admin: asyncpg.Connection) -> tuple[str, str]:
    slug = f"prb-{uuid4().hex[:8]}"
    medio_id = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) "
        "VALUES ($1, 'PR B Test', 'custom') RETURNING id",
        slug,
    )
    return str(medio_id), slug


async def _cleanup(slug: str) -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute("DELETE FROM medios WHERE slug = $1", slug)
    finally:
        await admin.close()


async def _construir_deps(
    *,
    search_resultados: list[dict],
    claude_respuestas: list[str],
    gemini_respuestas: list[str],
    imagen: dict | None = None,
) -> PipelineDeps:
    pool = await get_pool(APP_DSN)
    return PipelineDeps(
        pool=pool,
        gemini=FakeLLM(respuestas=gemini_respuestas),
        claude=FakeLLM(respuestas=claude_respuestas),
        search=FakeSearch(resultados=search_resultados),
        images=FakeImageBank(imagen=imagen),
    )


# ==========================================================================
# 1. test_write_longitud_segun_urgencia
# ==========================================================================
@pytest.mark.parametrize(
    "urgencia,target_min,target_max",
    [
        ("breaking", 400, 600),
        ("normal", 600, 900),
        ("evergreen", 800, 1000),
    ],
)
@_skip_sin_db
async def test_write_longitud_segun_urgencia(
    urgencia: str, target_min: int, target_max: int
) -> None:
    """Para cada urgencia, write genera un cuerpo en el rango correcto y
    review NO marca error de longitud."""
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id_str, slug = await _crear_medio(admin)
    await admin.close()
    try:
        fuente_urls = [
            "https://aragondigital.es/a",
            "https://europapress.es/b",
            "https://20minutos.es/c",
        ]
        # Para señales, urgencia=normal por defecto; usamos tema_libre con
        # detect que devuelve la urgencia parametrizada. 'breaking' lo
        # generamos con señal (tema libre lo bloquea) — pero para este test
        # simplificamos: state inicial pasa urgencia directamente.
        cuerpo = _cuerpo_para_rango(fuente_urls, target_min, target_max)
        deps = await _construir_deps(
            search_resultados=[fuente_falsa(u) for u in fuente_urls],
            claude_respuestas=[
                _detect_json("Tema X", urgencia),  # detect
                "persona|Jorge Azcón",              # NER
                _write_json("Titulo válido sobre presupuestos Aragón 2026", cuerpo),
                "",                                  # review LLM
            ],
            gemini_respuestas=[
                json.dumps(
                    {"hechos": [{"afirmacion": "Hecho", "fuentes": [fuente_urls[0]]}]}
                ),
            ],
            imagen={"url": "https://images.pexels.com/photos/x.jpg"},
        )
        medio_id = UUID(medio_id_str)
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await admin.execute(
                "SELECT set_config('app.medio_actual', $1, false)", medio_id_str
            )
            # Para breaking necesitamos señal, no tema libre
            if urgencia == "breaking":
                senal_id = await admin.fetchval(
                    "INSERT INTO senales (medio_id, origen, termino, score) "
                    "VALUES ($1, 'rss', 'Tema X', 0.9) RETURNING id",
                    medio_id_str,
                )
            else:
                senal_id = None
            run_id = await crear_run(
                admin,
                medio_id=medio_id,
                redactor_id=None,
                trigger_tipo="manual",
                senal_id=senal_id,
                tema_input=None if urgencia == "breaking" else "Tema X",
            )
        finally:
            await admin.close()

        state_inicial: PipelineState = {
            "medio_id": medio_id,
            "run_id": run_id,
            "trigger_tipo": "manual",
        }
        if senal_id is not None:
            state_inicial["senal_id"] = senal_id
        else:
            state_inicial["tema_input"] = "Tema X"

        graph = build_graph(deps)
        state_final = await graph.ainvoke(state_inicial)

        # El cuerpo debe estar en el rango y review NO debe reportar longitud.
        cuerpo_final = state_final.get("cuerpo_md", "")
        n = len(cuerpo_final.split())
        min_w, max_w = RANGOS_PALABRAS[urgencia]
        assert min_w <= n <= max_w, (
            f"cuerpo {n} palabras fuera de [{min_w},{max_w}] para urgencia={urgencia}"
        )
        # Verificar que no haya error de longitud en review_errores.
        errores = state_final.get("review_errores", []) or []
        errores_longitud = [e for e in errores if "palabras, fuera del rango" in e]
        assert not errores_longitud, (
            f"review marcó longitud incorrecta para {urgencia}: {errores_longitud}"
        )
    finally:
        await close_pool()
        await _cleanup(slug)


# ==========================================================================
# 2. test_enrich_genera_jsonld_valido
# ==========================================================================
def test_enrich_jsonld_estructura_newsarticle_minima() -> None:
    """``_build_jsonld`` produce un dict con campos schema.org NewsArticle.

    Validación de campos mínimos exigidos:
    - @context = schema.org
    - @type = NewsArticle
    - headline, description, datePublished, dateModified
    - author.Person, publisher.Organization
    - about[] con @type mapeado por tipo de entidad
    - mainEntityOfPage.WebPage
    """
    state: dict = {
        "titulo": "Azcón presenta los presupuestos de Aragón para 2026",
        "meta_descr": "Resumen de los presupuestos autonómicos de Aragón.",
        "cms_url": "https://hoyaragon.com/presupuestos-2026",
    }
    entidades = [
        {"tipo": "persona", "nombre": "Jorge Azcón"},
        {"tipo": "organizacion", "nombre": "DGA"},
        {"tipo": "lugar", "nombre": "Zaragoza"},
        {"tipo": "evento", "nombre": "Pleno DGA"},
    ]
    schema = _build_jsonld(
        state=state,  # type: ignore[arg-type]
        entidades=entidades,
        imagen_url="https://images.pexels.com/photos/x.jpg",
        author_name="Pepe Redactor",
        publisher_name="Hoy Aragón",
    )

    assert schema["@context"] == "https://schema.org"
    assert schema["@type"] == "NewsArticle"
    assert schema["headline"] == state["titulo"]
    assert schema["description"] == state["meta_descr"]
    assert isinstance(schema["datePublished"], str)
    assert isinstance(schema["dateModified"], str)
    assert schema["author"] == {"@type": "Person", "name": "Pepe Redactor"}
    assert schema["publisher"] == {
        "@type": "Organization",
        "name": "Hoy Aragón",
    }
    assert schema["image"] == ["https://images.pexels.com/photos/x.jpg"]
    assert schema["mainEntityOfPage"]["@type"] == "WebPage"
    assert schema["mainEntityOfPage"]["@id"] == "https://hoyaragon.com/presupuestos-2026"
    about = schema["about"]
    assert isinstance(about, list)
    tipos_about = {item["@type"] for item in about}
    nombres_about = {item["name"] for item in about}
    assert tipos_about == {"Person", "Organization", "Place", "Event"}
    assert nombres_about == {"Jorge Azcón", "DGA", "Zaragoza", "Pleno DGA"}


def test_enrich_mapear_tipo_schema_fallback_thing() -> None:
    """Tipos desconocidos caen a ``Thing`` (no rompen el JSON-LD)."""
    assert _mapear_tipo_schema("persona") == "Person"
    assert _mapear_tipo_schema("xyz") == "Thing"
    assert _mapear_tipo_schema(None) == "Thing"


# ==========================================================================
# 3. test_review_pasa_con_cuerpo_correcto
# ==========================================================================
@_skip_sin_db
async def test_review_pasa_con_cuerpo_correcto() -> None:
    """Caso happy path: cuerpo en rango, slug/meta válidos, ≥2 citas, sin
    invenciones → review_aprobado=True en primer intento."""
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id_str, slug = await _crear_medio(admin)
    await admin.close()
    try:
        fuente_urls = [
            "https://aragondigital.es/a",
            "https://europapress.es/b",
            "https://20minutos.es/c",
        ]
        cuerpo = _cuerpo_para_rango(fuente_urls, 800, 1000)
        deps = await _construir_deps(
            search_resultados=[fuente_falsa(u) for u in fuente_urls],
            claude_respuestas=[""],  # review LLM sin errores
            gemini_respuestas=[],
            imagen=None,
        )
        medio_id = UUID(medio_id_str)
        run_id = uuid4()

        state: PipelineState = {
            "medio_id": medio_id,
            "run_id": run_id,
            "trigger_tipo": "manual",
            "titulo": "Azcón presenta los presupuestos de Aragón para 2026",
            "meta_title": "Presupuestos Aragón 2026 | análisis y datos",
            "meta_descr": META_DESCR_OK,
            "slug": "azcon-presupuestos-aragon-2026",
            "cuerpo_md": cuerpo,
            "urgencia": "evergreen",
            "fuentes": [
                {"url": u, "paywall": False} for u in fuente_urls
            ],
            "hechos_verificados": [
                {
                    "afirmacion": "Los presupuestos crecen un 5%",
                    "fuentes": [fuente_urls[0]],
                }
            ],
            "entidades": [{"tipo": "persona", "nombre": "Jorge Azcón"}],
            "write_intentos": 1,
        }

        out = await review_node(state, deps)
        errores = out.get("review_errores") or []
        assert out["review_aprobado"] is True, (
            f"review rechazó cuerpo correcto. Errores: {errores}"
        )
        assert errores == []
        assert out["requiere_revision_humana"] is False
    finally:
        await close_pool()
        await _cleanup(slug)


# ==========================================================================
# 4. test_publish_persiste_draft_con_senal_id_sincronizado
# ==========================================================================
@_skip_sin_db
async def test_publish_persiste_draft_con_senal_id_sincronizado() -> None:
    """Tras publish: drafts.id existe en BD, drafts.senal_id sincronizado
    desde runs.senal_id por trigger (migración 004), draft_entidades poblado
    para entidades con catalogo_id."""
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id_str, slug = await _crear_medio(admin)
    medio_id = UUID(medio_id_str)
    try:
        await admin.execute(
            "SELECT set_config('app.medio_actual', $1, false)", medio_id_str
        )
        senal_id = await admin.fetchval(
            "INSERT INTO senales (medio_id, origen, termino, score) "
            "VALUES ($1, 'rss', 'Presupuestos Aragón', 0.7) RETURNING id",
            medio_id_str,
        )
        # Necesitamos una entidad en el catálogo con catalogo_id para
        # verificar la inserción en draft_entidades.
        entidad_id = await admin.fetchval(
            "SELECT id FROM entidades_catalogo "
            "WHERE nombre_canonico = 'Jorge Azcón' LIMIT 1"
        )
        assert entidad_id is not None, "seed entidades_aragon no cargada"
    finally:
        await admin.close()

    try:
        from src.pipeline.nodes.publish import publish_node

        pool = await get_pool(APP_DSN)
        deps = PipelineDeps(
            pool=pool,
            gemini=FakeLLM(),
            claude=FakeLLM(),
            search=FakeSearch(),
            images=FakeImageBank(),
        )
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await admin.execute(
                "SELECT set_config('app.medio_actual', $1, false)", medio_id_str
            )
            run_id = await crear_run(
                admin,
                medio_id=medio_id,
                redactor_id=None,
                trigger_tipo="automatizacion",
                senal_id=senal_id,
            )
        finally:
            await admin.close()

        state: PipelineState = {
            "medio_id": medio_id,
            "run_id": run_id,
            "trigger_tipo": "automatizacion",
            "senal_id": senal_id,
            "titulo": "Presupuestos 2026 en Aragón",
            "meta_title": "Presupuestos 2026 | Aragón",
            "meta_descr": META_DESCR_OK,
            "slug": "presupuestos-2026-aragon",
            "cuerpo_md": "Cuerpo de prueba con cita a https://aragondigital.es/a",
            "review_aprobado": True,
            "entidades": [
                {
                    "tipo": "persona",
                    "nombre": "Jorge Azcón",
                    "catalogo_id": str(entidad_id),
                }
            ],
            "imagen_destacada": {
                "url": "https://images.pexels.com/photos/123.jpg",
                "foto_id": "123",
                "fotografo": "Ada Lovelace",
                "alt_texto": "Sala de gobierno",
            },
            "schema_jsonld": {"@type": "NewsArticle"},
            "enlaces_internos": [],
        }
        out = await publish_node(state, deps)

        draft_id = out.get("draft_id")
        assert draft_id is not None
        assert out["editor_url"].startswith("https://redactia.local/drafts/")
        assert out.get("imagen_destacada_id") is not None

        # Verificación en BD: senal_id sincronizado, draft_entidades, imagen
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await admin.execute(
                "SELECT set_config('app.medio_actual', $1, false)", medio_id_str
            )
            row = await admin.fetchrow(
                "SELECT senal_id, imagen_destacada_id, estado FROM drafts WHERE id = $1",
                draft_id,
            )
            assert row is not None
            assert str(row["senal_id"]) == str(senal_id), (
                "trigger no sincronizó senal_id"
            )
            assert row["imagen_destacada_id"] is not None
            assert row["estado"] == "borrador"

            # draft_entidades pobló la fila para Jorge Azcón
            link_count = await admin.fetchval(
                "SELECT COUNT(*) FROM draft_entidades "
                "WHERE draft_id = $1 AND entidad_id = $2",
                draft_id,
                entidad_id,
            )
            assert link_count == 1

            # imagenes_articulo persistió
            img = await admin.fetchrow(
                "SELECT fuente, banco_licencia_tipo, alt_text, declaracion_ia_visible "
                "FROM imagenes_articulo WHERE draft_id = $1",
                draft_id,
            )
            assert img is not None
            assert img["fuente"] == "banco_licencia"
            assert img["banco_licencia_tipo"] == "pexels"
            assert img["declaracion_ia_visible"] is False
            assert "Sala" in img["alt_text"]

            # runs marcado completado
            estado_run = await admin.fetchval(
                "SELECT estado FROM runs WHERE id = $1", run_id
            )
            assert estado_run == "completado"
        finally:
            await admin.close()
    finally:
        await close_pool()
        await _cleanup(slug)
