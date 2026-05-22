"""Contrato común de los detectores de tendencias."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

Origen = Literal["rss", "gtrends", "gdelt", "x"]


@dataclass(frozen=True)
class DetectorContext:
    """Contexto de ejecución que recibe cada detector.

    El detector NO accede a la BD directamente para leer config — el runner
    le pasa todo lo que necesita aquí.
    """

    medio_id: UUID
    perfil_id: UUID
    fuente_id: UUID
    categoria_destino: str
    pais: str                       # 'ES'
    idiomas: tuple[str, ...]        # ('es',) — tupla para hashable
    keywords_obligatorias: tuple[str, ...]
    keywords_negativas: tuple[str, ...]
    config: dict[str, Any]          # config específica del detector
    usar_solo_como_senal: bool      # marcar señales como paywall


@dataclass(frozen=True)
class SenalCruda:
    """Salida de un detector antes de pasar por scorer/dedupe/persist."""

    origen: Origen
    termino: str                    # string de búsqueda u objeto detectado
    categoria: str | None
    pais: str | None
    region: str | None              # ES, ES-AR, etc.
    velocidad: float | None         # delta/min normalizado por detector
    volumen: int | None
    url_origen: str | None
    paywall: bool
    expira_en_horas: int
    metadatos: dict[str, Any] = field(default_factory=dict)


class TrendDetector(Protocol):
    """Cada implementación es una función pura ``(ctx) -> [SenalCruda]``.

    Sin side effects (no BD, no caché global). Las llamadas a APIs externas
    sí están permitidas pero deben ser ``async`` y respetar timeouts.
    """

    nombre: Origen

    async def detectar(self, ctx: DetectorContext) -> list[SenalCruda]: ...
