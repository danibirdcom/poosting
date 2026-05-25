"""Tests de los compactadores de input/output para ``run_steps`` (Bug E).

Verifica que cada step produce un payload JSON-serializable con metadatos
útiles para auditoría, sin duplicar blobs grandes (cuerpo_md, contenido_md
de fuentes, ejemplos cargados).
"""

from __future__ import annotations

import json
from uuid import uuid4

from src.pipeline.step_payloads import (
    MAX_STR_LEN,
    compactar_input,
    compactar_output,
)


def _estado_base() -> dict:
    return {
        "medio_id": uuid4(),
        "run_id": uuid4(),
        "trigger_tipo": "manual",
        "redactor_id": uuid4(),
        "tema_input": "Zaragoza Florece 2026",
        "categoria": "cultura",
        "tema_final": "Zaragoza Florece supera el récord",
        "angulo": "afluencia",
        "urgencia": "evergreen",
        "fuentes": [
            {"url": "https://a.es/x", "contenido_md": "z" * 600},
            {"url": "https://b.es/x", "contenido_md": "z" * 600},
        ],
        "hechos_verificados": [{"afirmacion": "Récord de asistencia", "fuentes": []}],
        "entidades": [{"tipo": "evento", "nombre": "Zaragoza Florece"}],
        "titulo": "Zaragoza Florece bate récord en su edición 2026",
        "cuerpo_md": "## Encabezado\n\nTexto " * 500,
        "write_intentos": 1,
        "review_aprobado": True,
        "review_errores": [],
        "review_sugerencias": ["sugerencia A"],
        "requiere_revision_humana": False,
        "enlaces_internos": [{"anchor": "X", "draft_id": str(uuid4()), "score": 0.8}],
        "tags_cms": ["cultura", "zaragoza"],
        "imagen_destacada_url": "https://images/x.jpg",
        "draft_id": uuid4(),
        "modo_publish": "bandeja",
        "editor_url": "https://redactia.local/drafts/abc",
    }


def test_compactar_input_serializable_a_json_para_todos_los_steps() -> None:
    state = _estado_base()
    for step in ("detect", "research", "write", "review", "enrich", "publish"):
        payload = compactar_input(step, state)
        # Debe ser JSON-serializable (asyncpg lo persiste como JSONB).
        json.dumps(payload)


def test_compactar_output_serializable_a_json_para_todos_los_steps() -> None:
    state = _estado_base()
    for step in ("detect", "research", "write", "review", "enrich", "publish"):
        payload = compactar_output(step, state)
        json.dumps(payload)


def test_compactar_output_write_no_incluye_cuerpo_md_entero() -> None:
    state = _estado_base()
    payload = compactar_output("write", state)
    # cuerpo_md tiene >5000 palabras en el estado de prueba; el output debe
    # incluir solo el conteo de palabras.
    assert "cuerpo_md" not in payload
    assert payload["cuerpo_palabras"] > 100


def test_compactar_output_research_persiste_urls_y_entidades() -> None:
    state = _estado_base()
    payload = compactar_output("research", state)
    assert payload["n_fuentes"] == 2
    assert "https://a.es/x" in payload["urls_fuentes"]
    assert payload["entidades"] == [{"tipo": "evento", "nombre": "Zaragoza Florece"}]


def test_compactar_input_write_compactado() -> None:
    state = _estado_base()
    payload = compactar_input("write", state)
    assert payload["urgencia"] == "evergreen"
    assert payload["n_hechos"] == 1
    assert payload["n_fuentes"] == 2
    assert payload["n_entidades"] == 1


def test_compactar_input_review_tiene_n_intentos() -> None:
    state = _estado_base()
    state["write_intentos"] = 2
    payload = compactar_input("review", state)
    assert payload["write_intentos"] == 2
    assert payload["cuerpo_palabras"] > 0


def test_compactar_input_uuid_se_serializa_a_str() -> None:
    state = _estado_base()
    payload = compactar_input("detect", state)
    # senal_id no está en el estado base; redactor_id sí.
    assert isinstance(payload["redactor_id"], str)


def test_compactar_truncado_aplica_max_len() -> None:
    state = _estado_base()
    state["titulo"] = "X" * (MAX_STR_LEN + 200)
    payload = compactar_output("write", state)
    assert payload["titulo"] is not None
    assert len(payload["titulo"]) <= MAX_STR_LEN + 5  # " […]"
