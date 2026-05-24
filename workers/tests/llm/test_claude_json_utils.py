"""Tests del parser tolerante de JSON (workers/src/llm/_json_utils.py).

Los 4 casos del fix de smoke end-to-end (PR #10 follow-up):
1. JSON puro → dict válido.
2. JSON envuelto en ```json ... ``` → dict válido (recorta fences).
3. JSON con texto explicativo antes y después → dict válido (recorta).
4. String inválido / vacío → None.
"""

from __future__ import annotations

from src.llm._json_utils import parse_json_tolerante


def test_json_puro_se_parsea() -> None:
    raw = '{"titulo": "Hola", "n": 3, "lista": [1, 2]}'
    out = parse_json_tolerante(raw)
    assert out == {"titulo": "Hola", "n": 3, "lista": [1, 2]}


def test_json_con_code_fence_json_se_parsea() -> None:
    raw = '```json\n{"k": "v", "n": 1}\n```'
    out = parse_json_tolerante(raw)
    assert out == {"k": "v", "n": 1}


def test_json_con_code_fence_sin_lang_se_parsea() -> None:
    """Fence sin marcador de lenguaje (` ``` ` solo) también se limpia."""
    raw = '```\n{"k": "v"}\n```'
    out = parse_json_tolerante(raw)
    assert out == {"k": "v"}


def test_json_con_texto_antes_y_despues_se_parsea() -> None:
    """LLM a veces añade explicación: 'Aquí tienes el JSON: { ... } ¿Algo más?'"""
    raw = 'Aquí va el JSON que me pediste:\n{"titulo": "Test", "n": 7}\nSaludos.'
    out = parse_json_tolerante(raw)
    assert out == {"titulo": "Test", "n": 7}


def test_string_invalido_devuelve_none() -> None:
    assert parse_json_tolerante("no es JSON") is None
    assert parse_json_tolerante("") is None
    assert parse_json_tolerante("   ") is None
    # JSON sintácticamente inválido
    assert parse_json_tolerante('{"k": ') is None
    # Array de raíz no es dict → None
    assert parse_json_tolerante("[1, 2, 3]") is None
    # Escalar no es dict → None
    assert parse_json_tolerante('"solo un string"') is None


def test_json_anidado_se_parsea() -> None:
    """Defensa contra el algoritmo `find first {`: si hay objetos anidados,
    el último ``}`` debe ser el del objeto raíz, no el interno.
    """
    raw = '{"outer": {"inner": {"deep": 1}}, "n": 2}'
    out = parse_json_tolerante(raw)
    assert out == {"outer": {"inner": {"deep": 1}}, "n": 2}


def test_json_con_fence_y_texto_extra() -> None:
    """Combinación: fence + texto antes. Caso real visto en producción."""
    raw = (
        "Claro, aquí tienes la respuesta:\n\n"
        '```json\n'
        '{"titulo": "Hola", "ok": true}\n'
        '```\n'
        "Si necesitas más, dime."
    )
    out = parse_json_tolerante(raw)
    assert out == {"titulo": "Hola", "ok": True}
