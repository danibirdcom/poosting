"""Tests del helper ``preparar_fuentes_contenido`` (Bug A de cierre v2).

El nodo review pasa al LLM no solo ``hechos_verificados`` sino también el
``contenido_md`` íntegro de las fuentes, para que un detalle presente en
una fuente pero no en hechos sintetizados NO se marque como invención.
"""

from __future__ import annotations

from src.pipeline.nodes._fuentes import (
    MAX_CHARS_FUENTES_CONTENIDO,
    preparar_fuentes_contenido,
)


def test_preparar_fuentes_filtra_fuentes_sin_contenido() -> None:
    state = {
        "fuentes": [
            {"url": "https://a.es/x", "contenido_md": "tx" * 100},
            {"url": "https://b.es/x", "contenido_md": "demasiado corto"},  # <50 chars
            {"url": "https://c.es/x", "contenido_md": None},
            {"url": "https://d.es/x"},  # sin contenido_md
        ]
    }
    salida = preparar_fuentes_contenido(state)  # type: ignore[arg-type]
    assert len(salida) == 1
    assert salida[0]["dominio"] == "a.es"


def test_preparar_fuentes_trunca_dentro_del_cupo() -> None:
    """Si una fuente supera su cuota, se trunca limpiamente en espacio."""
    huge = "lorem ipsum dolor " * 5000  # >> cupo
    state = {"fuentes": [{"url": "https://x.es/y", "contenido_md": huge}]}
    salida = preparar_fuentes_contenido(state)  # type: ignore[arg-type]
    assert len(salida) == 1
    contenido = salida[0]["contenido_md"]
    assert len(contenido) <= MAX_CHARS_FUENTES_CONTENIDO + 10
    assert contenido.endswith(" […]")


def test_preparar_fuentes_extrae_dominio_de_url() -> None:
    state = {
        "fuentes": [
            {"url": "https://www.zaragoza.es/sede/x", "contenido_md": "z" * 100},
        ]
    }
    salida = preparar_fuentes_contenido(state)  # type: ignore[arg-type]
    assert salida[0]["dominio"] == "zaragoza.es"


def test_preparar_fuentes_usa_campo_dominio_si_existe() -> None:
    state = {
        "fuentes": [
            {"url": "https://x", "dominio": "heraldo.es", "contenido_md": "z" * 100},
        ]
    }
    salida = preparar_fuentes_contenido(state)  # type: ignore[arg-type]
    assert salida[0]["dominio"] == "heraldo.es"


def test_preparar_fuentes_total_no_excede_cupo() -> None:
    """Con N fuentes grandes, el total acumulado no excede el cupo."""
    base = "palabra " * 2000
    state = {"fuentes": [{"url": f"https://f{i}.es/x", "contenido_md": base} for i in range(5)]}
    salida = preparar_fuentes_contenido(state)  # type: ignore[arg-type]
    total_chars = sum(len(f["contenido_md"]) for f in salida)
    assert total_chars <= MAX_CHARS_FUENTES_CONTENIDO


def test_preparar_fuentes_vacio() -> None:
    assert preparar_fuentes_contenido({}) == []  # type: ignore[arg-type]
    assert preparar_fuentes_contenido({"fuentes": []}) == []  # type: ignore[arg-type]
