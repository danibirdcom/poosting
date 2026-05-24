"""Clientes de modelos: Claude (write/review), Gemini (research),
Voyage (embeddings).

Los identificadores de modelo van **pinneados via env var** con defaults
sensatos. Cuando un modelo nuevo salga, basta con setear la env var en
el workflow — sin redeploy.

``validar_modelos()`` se llama al inicio de cualquier flujo que use LLMs
en modo live. Hace GET a los endpoints `/v1/models` (o equivalente) para
verificar que cada string responde. Si alguno no existe, falla rápido
con error claro pidiendo el string actualizado.
"""

from .config import (
    CLAUDE_HAIKU_MODEL,
    CLAUDE_SONNET_MODEL,
    GEMINI_MODEL,
    ModelosNoDisponiblesError,
    validar_modelos,
)
from .embeddings import EmbeddingsClient, VoyageEmbeddings

__all__ = [
    "CLAUDE_HAIKU_MODEL",
    "CLAUDE_SONNET_MODEL",
    "EmbeddingsClient",
    "GEMINI_MODEL",
    "ModelosNoDisponiblesError",
    "VoyageEmbeddings",
    "validar_modelos",
]
