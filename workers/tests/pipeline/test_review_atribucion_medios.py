"""Tests del post-filter de atribuciones a medios fuente (bug 3 de cierre).

Verifica que ``review_node`` NO marca como error_factual una mención a un
medio que aparece como dominio en ``state.fuentes``. Y que sí marca como
error las menciones a personas/orgs que NO están en el catálogo NI en
fuentes.

Los helpers ``_normalizar``, ``_extraer_dominios_fuentes`` y
``_es_atribucion_a_medio_fuente`` son testeables como funciones puras —
no necesitan BD.
"""

from __future__ import annotations

from src.pipeline.nodes.review import (
    _es_atribucion_a_medio_fuente,
    _extraer_dominios_fuentes,
    _normalizar,
)


def test_normalizar_quita_acentos_y_separa() -> None:
    assert _normalizar("El Periódico de Aragón") == "elperiodicodearagon"
    assert _normalizar("Heraldo") == "heraldo"
    assert _normalizar("20 minutos") == "20minutos"
    assert _normalizar("Aragón Digital") == "aragondigital"
    assert _normalizar("") == ""


def test_extraer_dominios_de_fuentes_con_dominio_y_url() -> None:
    state = {
        "fuentes": [
            {"url": "https://elperiodicodearagon.com/x", "dominio": "elperiodicodearagon.com"},
            {"url": "https://www.heraldo.es/y"},
            {"url": "https://aragondigital.es/z", "dominio": "aragondigital.es"},
            # Dominio corto se descarta (evita falsos positivos).
            {"url": "https://ok.es/a", "dominio": "ok.es"},
        ]
    }
    domis = _extraer_dominios_fuentes(state)  # type: ignore[arg-type]
    assert "elperiodicodearagon" in domis
    assert "heraldo" in domis
    assert "aragondigital" in domis
    # 'ok' tiene 2 chars, se descarta.
    assert "ok" not in domis


def test_extraer_dominios_sin_fuentes() -> None:
    assert _extraer_dominios_fuentes({}) == set()  # type: ignore[arg-type]
    assert _extraer_dominios_fuentes({"fuentes": []}) == set()  # type: ignore[arg-type]


def test_atribucion_a_medio_fuente_detectada() -> None:
    """Error tipo "mención a 'El Periódico de Aragón'..." se detecta cuando
    el dominio elperiodicodearagon.com está en fuentes.
    """
    domis = {"elperiodicodearagon", "heraldo"}
    assert _es_atribucion_a_medio_fuente(
        "Mención a 'El Periódico de Aragón' no catalogada en entidades",
        domis,
    )
    assert _es_atribucion_a_medio_fuente(
        "El cuerpo cita a Heraldo sin que aparezca en catálogo",
        domis,
    )


def test_atribucion_a_persona_no_se_filtra() -> None:
    """Mención a una persona/org no-media que no está en fuentes SÍ es error."""
    domis = {"elperiodicodearagon"}
    assert not _es_atribucion_a_medio_fuente(
        "Mención a 'Javier Lambán' no catalogada",
        domis,
    )
    assert not _es_atribucion_a_medio_fuente(
        "Se afirma que 'Ibercaja' donó 100M sin respaldo en hechos",
        domis,
    )


def test_atribucion_sin_dominios_no_es_atribucion() -> None:
    """Si no hay fuentes/dominios, ningún error es atribución (no filtra nada)."""
    assert not _es_atribucion_a_medio_fuente("mención a 'X' no catalogada", set())


def test_atribucion_robusta_a_capitalizacion() -> None:
    """Match es case + accent insensitive."""
    domis = {"heraldo"}
    assert _es_atribucion_a_medio_fuente("HERALDO informó que…", domis)
    assert _es_atribucion_a_medio_fuente("heraldo informó que…", domis)
