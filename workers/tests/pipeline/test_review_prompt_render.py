"""Tests del prompt review v1.2.0 (Bugs A y B).

Verifica que el prompt renderizado por Jinja2:
- Bug A: incluye <fuentes_contenido> con el texto de las fuentes (no solo
  hechos sintetizados). Y que el prompt instruye al LLM a aceptar
  detalles presentes en fuentes_contenido como válidos.
- Bug B: incluye la sección "INTERPRETACIÓN DEL STYLE_GUIDE" que aclara
  que los rangos del style_guide no son topes estrictos.
"""

from __future__ import annotations

from pathlib import Path

from src.pipeline.nodes.review import _template

PROMPTS_DIR = Path(__file__).parent.parent.parent / "src" / "pipeline" / "prompts"


def test_review_prompt_renderiza_fuentes_contenido() -> None:
    """El template incluye el bloque <fuentes_contenido> cuando se le pasa
    la variable; el LLM verá texto sustantivo de las fuentes.
    """
    tpl = _template()
    rendered = tpl.render(
        hechos=[{"afirmacion": "Récord de asistencia"}],
        fuentes_contenido=[
            {
                "dominio": "heraldo.es",
                "contenido_md": (
                    "El festival se celebra en el Parque Grande José Antonio Labordeta."
                ),
            },
        ],
        entidades_catalogo=["Zaragoza Florece"],
        style_guide_md="frase media 18-25 palabras",
        titulo="Título",
        cuerpo_md="El festival se celebra en el Parque Grande.",
    )
    assert "<fuentes_contenido>" in rendered
    assert "heraldo.es" in rendered
    assert "Parque Grande" in rendered


def test_review_prompt_sin_fuentes_no_renderiza_bloque() -> None:
    """Si no hay fuentes_contenido, el bloque NO se renderiza (Jinja {% if %}).
    El nombre puede seguir apareciendo en las instrucciones del <rol>, lo
    que comprobamos es que NO se inserta el bloque de datos.
    """
    tpl = _template()
    rendered = tpl.render(
        hechos=[{"afirmacion": "X"}],
        fuentes_contenido=[],
        entidades_catalogo=[],
        style_guide_md="",
        titulo="T",
        cuerpo_md="C",
    )
    # El separador de fuentes solo aparece si se renderiza el bloque.
    assert "--- Fuente" not in rendered


def test_review_md_documenta_criterio_invencion_con_fuentes_contenido() -> None:
    """El .md tiene el criterio explícito: invención = ni en hechos ni en
    fuentes_contenido. Defensa contra regresiones de prompt.
    """
    review_md = (PROMPTS_DIR / "review.md").read_text(encoding="utf-8")
    assert "fuentes_contenido" in review_md
    assert "CRITERIO PARA DETERMINAR SI UNA AFIRMACIÓN ES INVENCIÓN" in review_md


def test_review_md_documenta_interpretacion_style_guide() -> None:
    """El .md tiene la sección que aclara que los rangos del style_guide no
    son topes estrictos (Bug B).
    """
    review_md = (PROMPTS_DIR / "review.md").read_text(encoding="utf-8")
    assert "INTERPRETACIÓN DEL STYLE_GUIDE" in review_md
    # Mención explícita a "evitar >N" como aviso, no tope:
    low = review_md.lower()
    assert "no máximos" in low or "no son máximos" in low or "no topes" in low
