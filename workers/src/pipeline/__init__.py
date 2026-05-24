"""Pipeline multiagente de Fase 3.

Punto de entrada: ``build_graph(deps).ainvoke(state)``.

Estructura:
- ``state.py``: TypedDict canónico del estado entre nodos.
- ``graph.py``: definición del grafo LangGraph.
- ``nodes/``: implementación de cada nodo.
- ``prompts/``: templates Jinja2 de los prompts (cargados en PR B).
- ``persistence.py``: helpers de runs/run_steps/drafts.
"""

from .graph import build_graph
from .state import PipelineState

__all__ = ["PipelineState", "build_graph"]
