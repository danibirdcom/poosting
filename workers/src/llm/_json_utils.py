"""Utilidades de parseo de JSON tolerante a salidas "sucias" de LLM.

Los modelos a veces devuelven JSON envuelto en code fences (```json ... ```),
o con texto explicativo antes/después. ``parse_json_tolerante`` recoge los
casos comunes y devuelve ``None`` si no logra extraer un objeto JSON.

Mantengo el módulo con guion bajo para señalar que es helper interno: el
caller decide qué hacer con ``None`` (logger.warning + fallback, retry, etc.).
"""

from __future__ import annotations

import json
from typing import Any


def parse_json_tolerante(raw: str) -> dict[str, Any] | None:
    r"""Intenta extraer un objeto JSON de ``raw``.

    Pasos:
    1. Strip de espacios.
    2. Quitar fence inicial ```` ```json ```` o ```` ``` ```` y fence final ```` ``` ````.
    3. Recortar al primer ``{`` y último ``}`` (defensa contra texto extra
       antes o después: "Aquí va el JSON: { ... } Saludos.").
    4. ``json.loads``.

    Devuelve ``dict`` si el resultado es un objeto JSON; ``None`` en
    cualquier otro caso (JSON inválido, vacío, lista o escalar de raíz).
    """
    if not raw:
        return None
    clean = raw.strip()

    # Code fences (``` o ```json).
    if clean.startswith("```"):
        clean = clean[3:]
        if clean.lower().startswith("json"):
            clean = clean[4:]
        clean = clean.strip()
        if clean.endswith("```"):
            clean = clean[:-3].rstrip()

    # Recortar a primer { … último }
    first = clean.find("{")
    last = clean.rfind("}")
    if first == -1 or last == -1 or last < first:
        return None
    clean = clean[first : last + 1]

    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
