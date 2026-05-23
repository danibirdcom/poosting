"""Scheduler basado en GitHub Actions.

En este modo el scheduling REAL vive en archivos YAML
(``.github/workflows/detect-signals.yml``). Este scheduler es un no-op
desde el código Python: existe para satisfacer el contrato y para
loguear lo que el workflow YAML va a hacer.

Cuando movamos a BullMQ (Fase 3+), reemplazamos esta implementación sin
tocar a los detectores.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from .base import JobScheduler, JobSpec

logger = structlog.get_logger(__name__)


class GithubActionsScheduler(JobScheduler):
    async def schedule(self, spec: JobSpec) -> None:
        logger.info(
            "scheduler_noop",
            backend="github_actions",
            medio_id=str(spec.medio_id),
            job_tipo=spec.job_tipo,
            cron=spec.cron_expr,
            note="El scheduling real está en .github/workflows/detect-signals.yml",
        )

    async def cancel(self, medio_id: UUID, job_tipo: str) -> None:
        logger.info(
            "scheduler_cancel_noop",
            backend="github_actions",
            medio_id=str(medio_id),
            job_tipo=job_tipo,
        )
