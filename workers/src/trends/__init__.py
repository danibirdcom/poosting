"""Detección de tendencias multi-fuente.

Cada detector implementa ``TrendDetector`` y devuelve ``SenalCruda``.
La pipeline en ``runner.py`` orquesta: detector → dedupe → score → persist.
"""

from .base import DetectorContext, SenalCruda, TrendDetector

__all__ = ["DetectorContext", "SenalCruda", "TrendDetector"]
