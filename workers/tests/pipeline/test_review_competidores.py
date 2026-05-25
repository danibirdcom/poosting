"""Tests de la política editorial anti-competencia en review.

Política (CLAUDE.md §5.4): el cuerpo NO menciona a medios competidores por
su nombre. Sí puede enlazar a sus URLs sin nombrarlos en el anchor. Las
agencias (EFE, Europa Press…) e instituciones (Ayuntamiento, DGA, BOE…) sí
se pueden citar nominalmente.

Estos tests son puros (no necesitan BD): ejercitan
``_detectar_menciones_competidores`` y la normalización de texto.
"""

from __future__ import annotations

from pathlib import Path

from src.pipeline.nodes.review import (
    EXCEPCIONES_PERMITIDAS,
    LISTA_MEDIOS_COMPETIDORES,
    _detectar_menciones_competidores,
    _normalizar_texto,
)


# ---------------------------------------------------------------------------
# Helpers de normalización
# ---------------------------------------------------------------------------
def test_normalizar_texto_lowercase_sin_acentos() -> None:
    assert _normalizar_texto("El Periódico de Aragón") == "el periodico de aragon"
    assert _normalizar_texto("HERALDO") == "heraldo"
    assert _normalizar_texto("") == ""


# ---------------------------------------------------------------------------
# Detección: el cuerpo nombra a un medio competidor
# ---------------------------------------------------------------------------
def test_review_marca_atribucion_nominal_a_competidor() -> None:
    """'según El Periódico de Aragón, ...' es bloqueante (política editorial)."""
    cuerpo = (
        "Según El Periódico de Aragón, el festival superó las 230.000 "
        "visitas en sus tres primeras jornadas, una cifra récord."
    )
    errores = _detectar_menciones_competidores(cuerpo)
    assert errores, "debe marcar la mención a El Periódico de Aragón"
    assert any("el periodico de aragon" in e for e in errores)


def test_review_marca_aunque_anchor_nombre_competidor() -> None:
    """Anchor que nombra al competidor también es error."""
    cuerpo = (
        "El presupuesto crece según [El Periódico de Aragón](https://elperiodicodearagon.com/x) "
        "en cinco puntos."
    )
    errores = _detectar_menciones_competidores(cuerpo)
    assert any("el periodico de aragon" in e for e in errores)


def test_review_marca_heraldo_y_el_espanol() -> None:
    cuerpo = (
        "Como informa el Heraldo, la previsión es positiva. El Español también "
        "publicó datos similares."
    )
    errores = _detectar_menciones_competidores(cuerpo)
    competidores = {e for e in errores}
    # Ambos competidores deben aparecer en errores distintos.
    assert any("heraldo" in e for e in competidores)
    assert any("el espanol" in e for e in competidores)


# ---------------------------------------------------------------------------
# Aceptación: el cuerpo enlaza sin nombrar al competidor
# ---------------------------------------------------------------------------
def test_review_acepta_enlace_sin_nombrar_competidor() -> None:
    """Anchor neutral + URL del competidor en el path → NO es error."""
    cuerpo = (
        "El festival registró [una afluencia récord en la tercera "
        "jornada](https://www.elperiodicodearagon.com/zaragoza/festival), "
        "con miles de visitantes."
    )
    assert _detectar_menciones_competidores(cuerpo) == []


def test_review_acepta_agencia_efe() -> None:
    """EFE es agencia, no competidor. Citar nominalmente es OK."""
    cuerpo = "Según EFE, el ministro anunció medidas urgentes el martes."
    assert _detectar_menciones_competidores(cuerpo) == []


def test_review_acepta_institucional_ayuntamiento() -> None:
    """Fuente institucional: se puede citar por nombre."""
    cuerpo = (
        "[El Ayuntamiento de Zaragoza informa](https://www.zaragoza.es/sede/) que "
        "el presupuesto aumenta un 3% en 2026."
    )
    assert _detectar_menciones_competidores(cuerpo) == []


def test_review_acepta_europa_press_y_reuters() -> None:
    cuerpo = (
        "Una crónica de [Europa Press](https://europapress.es/x) y otra de "
        "[Reuters](https://reuters.com/y) coinciden en los datos."
    )
    assert _detectar_menciones_competidores(cuerpo) == []


# ---------------------------------------------------------------------------
# Casos límite
# ---------------------------------------------------------------------------
def test_review_no_marca_si_solo_aparece_url_del_competidor() -> None:
    """URL del competidor en el path NO cuenta como mención nominal."""
    cuerpo = (
        "Más detalles en [el reportaje completo](https://www.elperiodicodearagon.com/x) "
        "y en [esta cobertura](https://heraldo.es/y)."
    )
    assert _detectar_menciones_competidores(cuerpo) == []


def test_review_acepta_auto_referencia_al_medio_destino() -> None:
    """Si el medio destino es 'Heraldo' (caso hipotético), 'Heraldo' en el
    cuerpo no es error. Excepción de auto-referencia.
    """
    cuerpo = "Esta semana en Heraldo publicamos una crónica del festival."
    # Sin medio_nombre: marca error.
    assert _detectar_menciones_competidores(cuerpo) != []
    # Con medio_nombre="Heraldo": no marca error.
    assert _detectar_menciones_competidores(cuerpo, medio_nombre="Heraldo") == []


def test_review_word_boundaries_evita_falsos_positivos() -> None:
    """'abc' está en la lista pero no debe matchear dentro de 'abcdef'."""
    cuerpo = "El sistema abcdef no es relevante aquí."
    assert _detectar_menciones_competidores(cuerpo) == []


def test_review_cuerpo_vacio() -> None:
    assert _detectar_menciones_competidores("") == []
    assert _detectar_menciones_competidores("", medio_nombre="X") == []


def test_review_no_duplica_si_competidor_aparece_dos_veces() -> None:
    cuerpo = (
        "Según El País, el dato es 5%. El País también dice que crece "
        "el empleo. Y El País añade más cifras."
    )
    errores = _detectar_menciones_competidores(cuerpo)
    # Una única entrada de error por competidor (no spam).
    matches = [e for e in errores if "el pais" in e]
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
def test_listas_son_disjuntas_y_normalizadas() -> None:
    """Sanity: competidores y excepciones no se solapan, y todo está
    normalizado (lowercase + sin acentos).
    """
    inter = LISTA_MEDIOS_COMPETIDORES & EXCEPCIONES_PERMITIDAS
    assert inter == set()
    for nombre in LISTA_MEDIOS_COMPETIDORES | EXCEPCIONES_PERMITIDAS:
        assert nombre == _normalizar_texto(nombre), f"{nombre!r} no está normalizado"


# ---------------------------------------------------------------------------
# Verificación del prompt write: incluye ejemplos anti-competencia
# ---------------------------------------------------------------------------
def test_write_prompt_tiene_ejemplos_anti_competencia() -> None:
    """El prompt write.md debe mencionar explícitamente que no se nombran
    competidores y dar ejemplos. Verificamos las claves del lenguaje.
    """
    write_md = (
        Path(__file__).parent.parent.parent / "src" / "pipeline" / "prompts" / "write.md"
    ).read_text(encoding="utf-8")
    # Sección con ejemplos incorrectos: nombra a competidores como ❌.
    assert "INCORRECTO" in write_md.upper()
    assert "El Periódico de Aragón" in write_md
    # Sección con permitidos: EFE como ejemplo de cita aceptable.
    assert "EFE" in write_md
    # Política explícita.
    assert "competidor" in write_md.lower()
