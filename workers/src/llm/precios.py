"""Precios por proveedor para cálculo de coste estimado en CLI ``redactar``.

Unidad: EUR por millón de tokens (input / output).
Voyage embeddings: solo input (no hay tokens "output").
Modelos no listados → ``None`` (CLI loguea warning y reporta "coste desconocido").

Pinning: revisar contra las tarifas vigentes del proveedor antes de cambiar
de modelo. Doc internal: ver actualización en `docs/runbooks/costes.md`.

Las claves son los strings ``modelo`` que se pasan a ``client.generar()``;
deben coincidir con ``CLAUDE_SONNET_MODEL``, ``CLAUDE_HAIKU_MODEL`` y
``GEMINI_MODEL`` de ``llm/config.py``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Precio:
    input_eur_por_mil_millon: float
    output_eur_por_mil_millon: float = 0.0


# EUR por 1_000_000 de tokens. Snapshots a 2026-05.
PRECIOS: dict[str, Precio] = {
    "claude-sonnet-4-6": Precio(3.0, 15.0),
    "claude-sonnet-4-7": Precio(3.0, 15.0),
    "claude-haiku-4-5-20251001": Precio(0.8, 4.0),
    "claude-haiku-4-5": Precio(0.8, 4.0),
    "gemini-2.5-flash": Precio(0.075, 0.30),
    "voyage-3-large": Precio(0.18, 0.0),
}


def calcular_coste_eur(modelo: str, tokens_in: int, tokens_out: int) -> float | None:
    """Devuelve el coste en EUR, o ``None`` si el modelo no está tarificado.

    El CLI usa ``None`` para mostrar "coste desconocido" en vez de fallar —
    así se puede probar un modelo nuevo sin tener que actualizar precios.
    """
    precio = PRECIOS.get(modelo)
    if precio is None:
        return None
    return (
        tokens_in * precio.input_eur_por_mil_millon
        + tokens_out * precio.output_eur_por_mil_millon
    ) / 1_000_000.0
