"""Abstracción del scheduler.

En Fase 2 los jobs se disparan por scheduled GitHub Actions. En Fase 3+
se mueve a BullMQ con workers daemon. Los detectores no deben saber cómo
se les invoca: reciben un ``(medio_id, fuente_id)`` y devuelven señales.
"""

from .base import JobScheduler, JobSpec
from .github_actions import GithubActionsScheduler

__all__ = ["GithubActionsScheduler", "JobScheduler", "JobSpec"]
