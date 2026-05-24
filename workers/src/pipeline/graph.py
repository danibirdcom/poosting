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

    # LangGraph espera funciones ``async def`` reales que devuelvan dict —
    # no lambdas síncronos que devuelvan corrutinas (eso da
    # InvalidUpdateError: "Expected dict, got <coroutine object>"). Cada
    # wrapper aquí satisface esa firma y captura ``deps`` por closure.
    async def _detect(state: PipelineState) -> PipelineState:
        return await detect_node(state, deps)

    async def _research(state: PipelineState) -> PipelineState:
        return await research_node(state, deps)

    async def _write(state: PipelineState) -> PipelineState:
        return await write_node(state, deps)

    async def _review(state: PipelineState) -> PipelineState:
        return await review_node(state, deps)

    async def _enrich(state: PipelineState) -> PipelineState:
        return await enrich_node(state, deps)

    async def _publish(state: PipelineState) -> PipelineState:
        return await publish_node(state, deps)

    g.add_node("detect", _detect)
    g.add_node("research", _research)
    g.add_node("write", _write)
    g.add_node("review", _review)
    g.add_node("enrich", _enrich)
    g.add_node("publish", _publish)

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
