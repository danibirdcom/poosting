"""Interfaz del scheduler de jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class JobSpec:
    """Descripción de un job a ejecutar.

    El scheduler concreto decide CÓMO se ejecuta (subproceso CLI, mensaje
    a BullMQ, etc.). El llamador sólo dice QUÉ y CUÁNDO.
    """

    medio_id: UUID
    job_tipo: str          # 'detect_signals' por ahora
    payload: dict[str, object]
    cron_expr: str | None = None


class JobScheduler(Protocol):
    """Contrato del scheduler.

    Implementaciones previstas:
    - GithubActionsScheduler: no-op, los workflows YAML disparan vía CLI.
    - BullMQScheduler: encola en Redis para workers daemon (Fase 3+).
    """

    async def schedule(self, spec: JobSpec) -> None: ...
    async def cancel(self, medio_id: UUID, job_tipo: str) -> None: ...
