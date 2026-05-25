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

from collections.abc import Awaitable, Callable

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
from src.pipeline.persistence import with_step
from src.pipeline.state import PipelineState
from src.pipeline.step_payloads import compactar_input, compactar_output


def _route_after_detect(state: PipelineState) -> str:
    if state.get("detect_motivo_aborto"):
        return "publish"
    return "research"


def _route_after_research(state: PipelineState) -> str:
    if state.get("research_motivo_aborto"):
        return "publish"
    return "write"


_NodeFn = Callable[[PipelineState, PipelineDeps], Awaitable[PipelineState]]


async def _ejecutar_step(
    nombre: str,
    fn: _NodeFn,
    deps: PipelineDeps,
    state: PipelineState,
) -> PipelineState:
    """Persiste input/output del nodo en ``run_steps`` via ``with_step``.

    Idempotente: ON CONFLICT en (run_id, step_nombre) permite reejecutar
    el mismo step (p. ej. retry de write). Si ``run_id`` o ``medio_id``
    faltan en el estado (smoke tests sin DB), hace fallback a llamada
    directa sin persistir.
    """
    run_id = state.get("run_id")
    medio_id = state.get("medio_id")
    if run_id is None or medio_id is None:
        return await fn(state, deps)
    input_payload = compactar_input(nombre, state)
    async with with_step(deps.pool, medio_id, run_id, nombre, input_payload) as step:
        new_state = await fn(state, deps)
        step.output = compactar_output(nombre, new_state)
        return new_state


def build_graph(deps: PipelineDeps):
    """Construye el grafo del pipeline con dependencias inyectadas.

    Devuelve un graph compilado de LangGraph listo para invocar con
    ``await graph.ainvoke(state)``.

    Cada nodo se envuelve en ``_ejecutar_step`` para persistir input/output
    en ``run_steps``: trazabilidad completa, base para Fase 4 (UI dashboard).
    """
    g: StateGraph = StateGraph(PipelineState)

    # LangGraph espera funciones ``async def`` reales que devuelvan dict —
    # no lambdas síncronos que devuelvan corrutinas. Cada wrapper aquí
    # satisface esa firma y captura ``deps`` por closure.
    async def _detect(state: PipelineState) -> PipelineState:
        return await _ejecutar_step("detect", detect_node, deps, state)

    async def _research(state: PipelineState) -> PipelineState:
        return await _ejecutar_step("research", research_node, deps, state)

    async def _write(state: PipelineState) -> PipelineState:
        return await _ejecutar_step("write", write_node, deps, state)

    async def _review(state: PipelineState) -> PipelineState:
        return await _ejecutar_step("review", review_node, deps, state)

    async def _enrich(state: PipelineState) -> PipelineState:
        return await _ejecutar_step("enrich", enrich_node, deps, state)

    async def _publish(state: PipelineState) -> PipelineState:
        return await _ejecutar_step("publish", publish_node, deps, state)

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
