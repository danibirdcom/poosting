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
    DOMINIOS_COMPETIDORES,
    EXCEPCIONES_PERMITIDAS,
    LISTA_MEDIOS_COMPETIDORES,
    _detectar_menciones_competidores,
    _detectar_urls_competidores,
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
# Detección de URLs competidoras en markdown links (vertiente 2 de la política)
# ---------------------------------------------------------------------------
def test_review_detecta_url_competidor_en_markdown_link() -> None:
    """Anchor neutral + URL del competidor en `(url)` → error (v1.2.0)."""
    cuerpo = (
        "El festival registró [una afluencia récord](https://www.elperiodicodearagon.com/x) "
        "con miles de visitantes."
    )
    # _detectar_menciones_competidores quita la URL; mira solo nombres visibles.
    assert _detectar_menciones_competidores(cuerpo) == []
    # _detectar_urls_competidores sí marca el dominio del enlace.
    errores = _detectar_urls_competidores(cuerpo)
    assert any("elperiodicodearagon.com" in e for e in errores)


def test_review_detecta_url_competidor_con_subdominio() -> None:
    """Subdominios de competidores también bloquean."""
    cuerpo = "Ver [crónica](https://aragon.elespanol.com/x) para más detalle."
    errores = _detectar_urls_competidores(cuerpo)
    assert any("elespanol.com" in e for e in errores)


def test_review_acepta_link_institucional() -> None:
    """Enlace a institución → sin error."""
    cuerpo = "Ver [el Ayuntamiento](https://www.zaragoza.es/sede/) informa."
    assert _detectar_urls_competidores(cuerpo) == []


def test_review_acepta_link_a_agencia_efe() -> None:
    cuerpo = "Una crónica de [EFE](https://efe.com/es/zaragoza/x)."
    assert _detectar_urls_competidores(cuerpo) == []


def test_review_url_desnuda_no_dispara_detectar_urls_competidores() -> None:
    """Solo detectamos URLs DENTRO de markdown links. URLs sueltas no
    cuentan para esta vertiente (las cubre _checks_citas/_consultar_llm).
    """
    cuerpo = "Ver https://elperiodicodearagon.com/x sin formato markdown."
    assert _detectar_urls_competidores(cuerpo) == []


def test_review_url_competidor_no_duplica_si_aparece_dos_veces() -> None:
    cuerpo = (
        "Ver [un reportaje](https://elperiodicodearagon.com/x) y también "
        "[otra crónica](https://www.elperiodicodearagon.com/y) sobre el tema."
    )
    errores = _detectar_urls_competidores(cuerpo)
    # Solo 1 entrada por dominio.
    assert len([e for e in errores if "elperiodicodearagon.com" in e]) == 1


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
def test_review_menciones_competidores_no_mira_urls() -> None:
    """``_detectar_menciones_competidores`` solo mira nombres visibles.
    Las URLs (incluso a dominios competidores) las cubre
    ``_detectar_urls_competidores`` en una validación aparte.
    """
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


def test_dominios_competidores_son_lowercase() -> None:
    for d in DOMINIOS_COMPETIDORES:
        assert d == d.lower()
        assert not d.startswith("www.")
        assert "." in d, "debe ser dominio completo, no nickname"


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


def test_write_prompt_enlaces_externos_opcionales() -> None:
    """v1.2.0: los enlaces externos NO son obligatorios."""
    write_md = (
        Path(__file__).parent.parent.parent / "src" / "pipeline" / "prompts" / "write.md"
    ).read_text(encoding="utf-8")
    # Mensaje de relajación visible.
    low = write_md.lower()
    assert "opcional" in low or "no obligator" in low
    # No debe haber mensaje de "mínimo 2" como dura.
    assert "mínimo 2 enlaces" not in write_md
    assert "≥2 enlaces" not in write_md


def test_write_prompt_bloquea_url_competidor_aunque_anchor_neutral() -> None:
    """v1.2.0 vertiente 2: write.md debe explicar que URLs a dominio
    competidor son inválidas aunque el anchor sea neutral.
    """
    write_md = (
        Path(__file__).parent.parent.parent / "src" / "pipeline" / "prompts" / "write.md"
    ).read_text(encoding="utf-8")
    # La lista de dominios prohibidos aparece explícitamente.
    assert "elperiodicodearagon.com" in write_md
    assert "heraldo.es" in write_md
    # Y un ejemplo INCORRECTO con anchor neutral.
    assert "anchor neutral" in write_md.lower()
