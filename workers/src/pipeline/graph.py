"""Definición del grafo LangGraph del pipeline.

Topología:

    detect ──► research ──► write ──► review ──► enrich ──► publish ──► END
                                        │            ▲
                                        └──retry─────┘
                                        │
                                        └──to_bandeja──► publish

- ``detect`` aborta → puente directo a ``publish`` con run rechazado.
- ``research`` aborta → puente directo a ``publish`` con run rechazado.
- ``review`` decide siguiente nodo vía ``route_after_review``.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.pipeline.nodes import (
    PipelineDeps,
    detect_node,
    enrich_node,
    publish_node,
    research_node,
    review_node,
    write_node,
)
from src.pipeline.nodes.review import route_after_review
from src.pipeline.state import PipelineState


def _route_after_detect(state: PipelineState) -> str:
    if state.get("detect_motivo_aborto"):
        return "publish"
    return "research"


def _route_after_research(state: PipelineState) -> str:
    if state.get("research_motivo_aborto"):
        return "publish"
    return "write"


def build_graph(deps: PipelineDeps):
    """Construye el grafo del pipeline con dependencias inyectadas.

    Devuelve un graph compilado de LangGraph listo para invocar con
    ``await graph.ainvoke(state)``.
    """
    g: StateGraph = StateGraph(PipelineState)

    # Cada nodo se envuelve para inyectar deps. LangGraph llama con
    # ``await node(state)``; las deps van por closure.
    g.add_node("detect", lambda s: detect_node(s, deps))
    g.add_node("research", lambda s: research_node(s, deps))
    g.add_node("write", lambda s: write_node(s, deps))
    g.add_node("review", lambda s: review_node(s, deps))
    g.add_node("enrich", lambda s: enrich_node(s, deps))
    g.add_node("publish", lambda s: publish_node(s, deps))

    g.set_entry_point("detect")
    g.add_conditional_edges(
        "detect",
        _route_after_detect,
        {"research": "research", "publish": "publish"},
    )
    g.add_conditional_edges(
        "research",
        _route_after_research,
        {"write": "write", "publish": "publish"},
    )
    g.add_edge("write", "review")
    g.add_conditional_edges(
        "review",
        route_after_review,
        {"write": "write", "enrich": "enrich", "publish": "publish"},
    )
    g.add_edge("enrich", "publish")
    g.add_edge("publish", END)

    return g.compile()
