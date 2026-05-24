"""Nodos del pipeline multiagente.

Cada nodo es una corrutina ``async def <nombre>(state, deps) -> state``
que lee las claves que necesita del estado, hace su trabajo (puede llamar
a LLMs, BD, APIs externas) y devuelve un nuevo dict de estado con sus
salidas.

Convención: si un nodo aborta el run (p.ej. fuentes insuficientes), pone
``<nodo>_motivo_aborto`` en el estado y el grafo enruta a ``publish`` con
estado='rechazado'. Los nodos nunca lanzan excepciones para señalar
"no se puede continuar" — usan el estado.

Excepciones SÍ se lanzan para fallos técnicos (LLM caído, BD, etc.) y las
captura el orquestador para marcar el ``run_steps`` como fallido.
"""

from .deps import PipelineDeps
from .detect import detect_node
from .enrich import enrich_node
from .publish import publish_node
from .research import research_node
from .review import review_node
from .write import write_node

__all__ = [
    "PipelineDeps",
    "detect_node",
    "enrich_node",
    "publish_node",
    "research_node",
    "review_node",
    "write_node",
]
