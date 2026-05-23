"""Clientes de modelos: Claude (write/review), Gemini (research),
Voyage (embeddings).
"""

from .embeddings import EmbeddingsClient, VoyageEmbeddings

__all__ = ["EmbeddingsClient", "VoyageEmbeddings"]
