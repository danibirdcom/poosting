"""Tests específicos de PR A.1: detect y research con implementación real.

Cubre los cuatro escenarios pedidos en el spec:

1. ``test_detect_breaking_requiere_senal``: tema_libre + urgencia='breaking'
   del LLM → aborta con ``detect_motivo_aborto='breaking_requiere_senal'``.
2. ``test_detect_canibalizacion_semantica``: señal con embedding idéntico al
   de un draft publicado hace 5 días → ``tipo_run='actualizacion'``.
3. ``test_research_blacklist_filtra_dominio``: dominio en blacklist NO entra
   en ``state.fuentes`` ni en hechos.
4. ``test_research_paywall_de_senal_no_entra_en_fuentes``: señal con
   paywall=True no entra como fuente.
"""

from __future__ import annotations

import json
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from src.pipeline.nodes.detect import detect_node
from src.pipeline.nodes.research import research_node
from src.pipeline.state import PipelineState
from src.trends.persistence import close_pool, get_pool

from .fakes import FakeEmbeddings, FakeImageBank, FakeLLM, FakeSearch, fuente_falsa

APP_DSN = os.environ.get("DATABASE_URL", "")
ADMIN_DSN = os.environ.get("DATABASE_URL_ADMIN", APP_DSN)
pytestmark = pytest.mark.skipif(not APP_DSN, reason="DATABASE_URL no definido")


def _detect_json(
    tema_final: str = "Tema X",
    urgencia: str = "evergreen",
    angulo: str = "general",
) -> str:
    return json.dumps(
        {"tema_final": tema_final, "angulo": angulo, "urgencia": urgencia},
        ensure_ascii=False,
    )


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


async def _crear_medio(admin: asyncpg.Connection) -> tuple[str, str]:
    slug = f"pra1-{uuid4().hex[:8]}"
    medio_id = await admin.fetchval(
        "INSERT INTO medios (slug, nombre, cms_tipo) "
        "VALUES ($1, 'PRA.1 Test', 'custom') RETURNING id",
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
    embeddings: FakeEmbeddings | None = None,
):
    from src.pipeline.nodes.deps import PipelineDeps

    pool = await get_pool(APP_DSN)
    return PipelineDeps(
        pool=pool,
        gemini=FakeLLM(respuestas=gemini_respuestas),
        claude=FakeLLM(respuestas=claude_respuestas),
        search=FakeSearch(resultados=search_resultados),
        images=FakeImageBank(),
        embeddings=embeddings,
    )


# ==========================================================================
# 1. tema_libre + urgencia='breaking' → aborta
# ==========================================================================
async def test_detect_breaking_requiere_senal() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id_str, slug = await _crear_medio(admin)
    await admin.close()
    try:
        deps = await _construir_deps(
            search_resultados=[],
            claude_respuestas=[
                _detect_json("Suceso urgente", urgencia="breaking"),
            ],
            gemini_respuestas=[],
        )
        state: PipelineState = {
            "medio_id": UUID(medio_id_str),
            "run_id": uuid4(),
            "trigger_tipo": "manual",
            "tema_input": "Algo está pasando ahora mismo",
        }
        out = await detect_node(state, deps)
        assert out.get("detect_motivo_aborto") == "breaking_requiere_senal"
        # Las urgencias/temas se devuelven igual para debugging, pero el aborto
        # impide al grafo continuar a research.
        assert out.get("urgencia") == "breaking"
    finally:
        await close_pool()
        await _cleanup(slug)


# ==========================================================================
# 2. señal con embedding idéntico a draft de hace 5 días → actualización
# ==========================================================================
async def test_detect_canibalizacion_semantica() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id_str, slug = await _crear_medio(admin)
    medio_id = UUID(medio_id_str)
    embedding = [0.1] * 1024
    emb_lit = _vector_literal(embedding)
    try:
        await admin.execute(
            "SELECT set_config('app.medio_actual', $1, false)", medio_id_str
        )
        # Draft publicado hace 5 días con embedding fijo.
        run_previo = await admin.fetchval(
            "INSERT INTO runs (medio_id, trigger_tipo, estado) "
            "VALUES ($1, 'manual', 'completado') RETURNING id",
            medio_id_str,
        )
        draft_id = await admin.fetchval(
            """
            INSERT INTO drafts (
              run_id, medio_id, titulo, cuerpo_md, estado,
              embedding, publicado_at
            )
            VALUES ($1, $2, 'Original', 'cuerpo original', 'publicado',
                    $3::vector, NOW() - INTERVAL '5 days')
            RETURNING id
            """,
            run_previo,
            medio_id_str,
            emb_lit,
        )
        # Señal con MISMO embedding → cosine = 1.0 > 0.85 → actualización.
        senal_id = await admin.fetchval(
            """
            INSERT INTO senales (medio_id, origen, termino, score, embedding)
            VALUES ($1, 'rss', 'Tema idéntico', 0.5, $2::vector)
            RETURNING id
            """,
            medio_id_str,
            emb_lit,
        )
    finally:
        await admin.close()

    try:
        deps = await _construir_deps(
            search_resultados=[],
            claude_respuestas=[
                _detect_json("Tema idéntico", "normal"),
            ],
            gemini_respuestas=[],
        )
        state: PipelineState = {
            "medio_id": medio_id,
            "run_id": uuid4(),
            "trigger_tipo": "automatizacion",
            "senal_id": senal_id,
        }
        out = await detect_node(state, deps)
        assert out.get("detect_motivo_aborto") is None
        assert out.get("tipo_run") == "actualizacion"
        assert str(out.get("draft_actualizar_id")) == str(draft_id)
    finally:
        await close_pool()
        await _cleanup(slug)


# ==========================================================================
# 3. blacklist: dominio bloqueado no llega a fuentes
# ==========================================================================
async def test_research_blacklist_filtra_dominio() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id_str, slug = await _crear_medio(admin)
    medio_id = UUID(medio_id_str)
    dominio_baneado = f"baneado-{uuid4().hex[:6]}.example"
    try:
        await admin.execute(
            "INSERT INTO blacklist_dominios (dominio, razon) VALUES ($1, $2) "
            "ON CONFLICT DO NOTHING",
            dominio_baneado,
            "test PR A.1",
        )
    finally:
        await admin.close()

    try:
        deps = await _construir_deps(
            search_resultados=[
                fuente_falsa(f"https://{dominio_baneado}/articulo"),
                fuente_falsa("https://aragondigital.es/x"),
                fuente_falsa("https://europapress.es/y"),
                fuente_falsa("https://20minutos.es/z"),
            ],
            claude_respuestas=[
                "persona|Jorge Azcón",  # NER
            ],
            gemini_respuestas=[
                json.dumps(
                    {
                        "hechos": [
                            {
                                "afirmacion": "Hecho A",
                                "fuentes": ["https://aragondigital.es/x"],
                            }
                        ]
                    }
                ),
            ],
        )
        state: PipelineState = {
            "medio_id": medio_id,
            "run_id": uuid4(),
            "trigger_tipo": "manual",
            "tema_final": "Tema test",
            "urgencia": "normal",
        }
        out = await research_node(state, deps)
        urls = {f["url"] for f in out.get("fuentes", [])}
        assert f"https://{dominio_baneado}/articulo" not in urls
        assert "https://aragondigital.es/x" in urls
        # Y los hechos tampoco pueden citar el dominio baneado.
        for h in out.get("hechos_verificados", []):
            for u in h.get("fuentes", []):
                assert dominio_baneado not in u
    finally:
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await admin.execute(
                "DELETE FROM blacklist_dominios WHERE dominio = $1", dominio_baneado
            )
        finally:
            await admin.close()
        await close_pool()
        await _cleanup(slug)


# ==========================================================================
# 4. señal paywall=True NO entra en fuentes
# ==========================================================================
async def test_research_paywall_de_senal_no_entra_en_fuentes() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id_str, slug = await _crear_medio(admin)
    medio_id = UUID(medio_id_str)
    url_paywall = "https://heraldo.es/articulo-tras-paywall"
    try:
        await admin.execute(
            "SELECT set_config('app.medio_actual', $1, false)", medio_id_str
        )
        senal_id = await admin.fetchval(
            """
            INSERT INTO senales (
              medio_id, origen, termino, score, paywall, url_origen
            )
            VALUES ($1, 'rss', 'Tema heraldo', 0.7, TRUE, $2)
            RETURNING id
            """,
            medio_id_str,
            url_paywall,
        )
    finally:
        await admin.close()

    try:
        deps = await _construir_deps(
            search_resultados=[
                fuente_falsa("https://aragondigital.es/a"),
                fuente_falsa("https://europapress.es/b"),
                fuente_falsa("https://20minutos.es/c"),
            ],
            claude_respuestas=[
                "persona|Jorge Azcón",
            ],
            gemini_respuestas=[
                json.dumps(
                    {
                        "hechos": [
                            {
                                "afirmacion": "Hecho B",
                                "fuentes": ["https://aragondigital.es/a"],
                            }
                        ]
                    }
                ),
            ],
        )
        state: PipelineState = {
            "medio_id": medio_id,
            "run_id": uuid4(),
            "trigger_tipo": "automatizacion",
            "senal_id": senal_id,
            "tema_final": "Tema heraldo",
            "urgencia": "normal",
        }
        out = await research_node(state, deps)
        urls = {f["url"] for f in out.get("fuentes", [])}
        assert url_paywall not in urls, (
            "señal paywall=True NO debe entrar como fuente"
        )
        # 3 fuentes no-paywall sí
        assert "https://aragondigital.es/a" in urls
        assert len(urls) == 3
        # Hechos tampoco pueden citarla
        for h in out.get("hechos_verificados", []):
            assert url_paywall not in h.get("fuentes", [])
    finally:
        await close_pool()
        await _cleanup(slug)


# ==========================================================================
# Bonus: señal SIN paywall (paywall=False) con url_origen SÍ entra como fuente.
# Espejo del test anterior para validar que la lógica no es "siempre excluir".
# ==========================================================================
async def test_research_senal_sin_paywall_entra_como_fuente() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    medio_id_str, slug = await _crear_medio(admin)
    medio_id = UUID(medio_id_str)
    url_senal = "https://aragondigital.es/origen-de-la-senal"
    try:
        await admin.execute(
            "SELECT set_config('app.medio_actual', $1, false)", medio_id_str
        )
        senal_id = await admin.fetchval(
            """
            INSERT INTO senales (
              medio_id, origen, termino, score, paywall, url_origen
            )
            VALUES ($1, 'rss', 'Tema libre', 0.5, FALSE, $2)
            RETURNING id
            """,
            medio_id_str,
            url_senal,
        )
    finally:
        await admin.close()

    try:
        deps = await _construir_deps(
            search_resultados=[
                fuente_falsa("https://europapress.es/x"),
                fuente_falsa("https://20minutos.es/y"),
            ],
            claude_respuestas=["persona|X"],
            gemini_respuestas=[
                json.dumps({"hechos": []}),
            ],
        )
        state: PipelineState = {
            "medio_id": medio_id,
            "run_id": uuid4(),
            "trigger_tipo": "automatizacion",
            "senal_id": senal_id,
            "tema_final": "Tema libre",
            "urgencia": "normal",
        }
        out = await research_node(state, deps)
        urls = {f["url"] for f in out.get("fuentes", [])}
        # 1 señal (no paywall) + 2 search = 3 fuentes → cumple mínimo de
        # 'normal' (3) sin abortar.
        assert url_senal in urls
        assert len(urls) == 3
        assert out.get("research_motivo_aborto") is None
    finally:
        await close_pool()
        await _cleanup(slug)
