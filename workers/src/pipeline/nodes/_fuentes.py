"""Helpers compartidos entre nodos para preparar fuentes (write + review).

Vive en un módulo separado para evitar import circular write ↔ review.
"""

from __future__ import annotations

from urllib.parse import urlparse

from src.pipeline.state import PipelineState

# ~10k chars ≈ ~2.5k tokens. Suficiente para que el LLM revisor compruebe
# afirmaciones del cuerpo sin saturar la ventana junto con el resto del
# prompt. Aplica también al nodo write como material de trabajo.
MAX_CHARS_FUENTES_CONTENIDO = 10_000


def preparar_fuentes_contenido(state: PipelineState) -> list[dict[str, str]]:
    """Lista de fuentes con `contenido_md` truncado y listo para prompt.

    Solo incluye fuentes con texto sustantivo (≥ 50 chars). Reparte el
    cupo total ``MAX_CHARS_FUENTES_CONTENIDO`` equitativamente entre las
    fuentes candidatas (greedy), truncando en un espacio para no cortar
    palabras. El orden se preserva.
    """
    fuentes = state.get("fuentes") or []
    candidatas: list[dict[str, str]] = []
    for f in fuentes:
        contenido = (f.get("contenido_md") or "").strip()
        if len(contenido) < 50:
            continue
        dominio = f.get("dominio") or _dominio_de_url(f.get("url") or "")
        candidatas.append({"dominio": dominio or "(fuente)", "contenido_md": contenido})

    if not candidatas:
        return []

    cupo_por_fuente = max(500, MAX_CHARS_FUENTES_CONTENIDO // len(candidatas))
    salida: list[dict[str, str]] = []
    total = 0
    for cand in candidatas:
        if total >= MAX_CHARS_FUENTES_CONTENIDO:
            break
        max_chars = min(cupo_por_fuente, MAX_CHARS_FUENTES_CONTENIDO - total)
        contenido = cand["contenido_md"]
        if len(contenido) > max_chars:
            contenido = contenido[:max_chars].rsplit(" ", 1)[0] + " […]"
        salida.append({"dominio": cand["dominio"], "contenido_md": contenido})
        total += len(contenido)
    return salida


def _dominio_de_url(url: str) -> str:
    if not url:
        return ""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host
