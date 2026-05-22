"""Tests del scorer puro: reproducibilidad y propiedades esperadas."""

from __future__ import annotations

from itertools import pairwise

import pytest

from src.trends.scorer import (
    ScoringPesos,
    decay_freshness,
    normalizar_velocidad,
    normalizar_volumen,
    score_compuesto,
)

PESOS_UNIF = ScoringPesos(1.0, 1.0, 1.0, 1.0)


def test_misma_entrada_mismo_score() -> None:
    s1 = score_compuesto(10.0, 5000, 2.0, 0.7, PESOS_UNIF)
    s2 = score_compuesto(10.0, 5000, 2.0, 0.7, PESOS_UNIF)
    assert s1 == s2


def test_score_en_rango_0_1() -> None:
    for v, n, h, i in [(0, 0, 0, 0), (1000, 1_000_000, 0, 1), (1, 1, 1000, 0)]:
        s = score_compuesto(v, n, h, i, PESOS_UNIF)
        assert 0.0 <= s <= 1.0, f"score fuera de rango para ({v},{n},{h},{i}): {s}"


def test_freshness_decae_monotono() -> None:
    valores = [decay_freshness(h) for h in [0, 1, 6, 12, 24, 48, 96]]
    for a, b in pairwise(valores):
        assert a >= b


def test_volumen_satura() -> None:
    assert normalizar_volumen(0) == 0.0
    assert normalizar_volumen(None) == 0.0
    # Más volumen → más score, hasta saturar
    v_pequeno = normalizar_volumen(100)
    v_grande = normalizar_volumen(100_000)
    v_enorme = normalizar_volumen(10_000_000)
    assert v_pequeno < v_grande < v_enorme
    assert v_enorme <= 1.0


def test_velocidad_satura() -> None:
    assert normalizar_velocidad(0) == 0.0
    assert normalizar_velocidad(None) == 0.0
    assert normalizar_velocidad(1) < normalizar_velocidad(10) < normalizar_velocidad(1000)
    assert normalizar_velocidad(1000) <= 1.0


def test_multiplicador_region_baja_score() -> None:
    base = score_compuesto(10.0, 5000, 2.0, 0.7, PESOS_UNIF, multiplicador_region=1.0)
    rebajado = score_compuesto(10.0, 5000, 2.0, 0.7, PESOS_UNIF, multiplicador_region=0.3)
    assert rebajado == pytest.approx(base * 0.3, abs=0.01)


def test_pesos_distintos_priorizan_componentes() -> None:
    pesos_solo_freshness = ScoringPesos(0.0, 0.0, 10.0, 0.0)
    s_fresco = score_compuesto(0, 0, 0.5, 0, pesos_solo_freshness)
    s_viejo = score_compuesto(0, 0, 100, 0, pesos_solo_freshness)
    assert s_fresco > s_viejo
