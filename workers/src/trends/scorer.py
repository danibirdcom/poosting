"""Scoring compuesto de señales.

Función pura ``score_compuesto`` que combina cuatro factores normalizados
[0,1] usando los pesos almacenados en ``scoring_pesos`` (por medio+categoría).

Diseño consciente: nada de magic numbers en el cuerpo de la función. Las
normalizaciones son explícitas y testeables por separado. Misma entrada
→ misma salida, siempre.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringPesos:
    """Pesos por categoría (vienen de la tabla scoring_pesos)."""

    peso_velocidad: float
    peso_volumen: float
    peso_freshness: float
    peso_intent: float


# Normalizaciones — explícitas para que sean auditables y ajustables.

# Saturación logarítmica del volumen. 1000 menciones → ~0.5; 1M → ~1.0.
_VOLUMEN_SATURACION = 1_000_000.0


def normalizar_volumen(volumen: int | None) -> float:
    if volumen is None or volumen <= 0:
        return 0.0
    # log10(1 + v) / log10(1 + saturacion), clamp a [0, 1]
    raw = math.log10(1 + volumen) / math.log10(1 + _VOLUMEN_SATURACION)
    return max(0.0, min(1.0, raw))


# Velocidad: delta de menciones por minuto. 10/min → ~0.5; 100/min → ~1.0.
_VELOCIDAD_SATURACION = 100.0


def normalizar_velocidad(velocidad: float | None) -> float:
    if velocidad is None or velocidad <= 0:
        return 0.0
    raw = math.log10(1 + velocidad) / math.log10(1 + _VELOCIDAD_SATURACION)
    return max(0.0, min(1.0, raw))


# Decay temporal: una señal de hace 1h vale ~0.9; 24h → ~0.37; 72h → ~0.05.
_FRESHNESS_TAU_HORAS = 24.0


def decay_freshness(horas_desde_deteccion: float) -> float:
    if horas_desde_deteccion <= 0:
        return 1.0
    return math.exp(-horas_desde_deteccion / _FRESHNESS_TAU_HORAS)


def normalizar_intent(intent: float | None) -> float:
    """Intent ya viene normalizado [0,1] por el detector (TODO: por ahora 0.5)."""
    if intent is None:
        return 0.5
    return max(0.0, min(1.0, intent))


def score_compuesto(
    velocidad: float | None,
    volumen: int | None,
    freshness_horas: float,
    intent: float | None,
    pesos: ScoringPesos,
    multiplicador_region: float = 1.0,
) -> float:
    """Score final.

    El ``multiplicador_region`` se aplica al final para casos como GTrends
    con mezcla ES-AR / ES (ver ``docs/agents/trend_detector.md`` §regiones).
    """
    componente = (
        pesos.peso_velocidad * normalizar_velocidad(velocidad)
        + pesos.peso_volumen * normalizar_volumen(volumen)
        + pesos.peso_freshness * decay_freshness(freshness_horas)
        + pesos.peso_intent * normalizar_intent(intent)
    )
    suma_pesos = (
        pesos.peso_velocidad
        + pesos.peso_volumen
        + pesos.peso_freshness
        + pesos.peso_intent
    )
    if suma_pesos <= 0:
        return 0.0
    base = componente / suma_pesos
    return round(base * multiplicador_region, 3)
