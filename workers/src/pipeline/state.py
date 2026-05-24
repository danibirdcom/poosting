"""Estado canónico del pipeline. Se persiste en ``run_steps`` entre nodos.

Cada nodo lee las claves que necesita y escribe las suyas. ``total=False``
permite que el TypedDict tenga claves opcionales — un nodo no asume que
todas estén presentes, solo las del flujo anterior.
"""

from __future__ import annotations

from typing import Literal, TypedDict
from uuid import UUID


class Fuente(TypedDict, total=False):
    url: str
    titulo: str | None
    publicado_at: str | None
    autoridad_score: float | None
    contenido_md: str | None
    dominio: str | None
    paywall: bool


class Hecho(TypedDict):
    afirmacion: str
    fuentes: list[str]  # urls de las fuentes que respaldan este hecho


class Entidad(TypedDict, total=False):
    tipo: Literal["persona", "organizacion", "lugar", "evento"]
    nombre: str
    wikidata_id: str | None
    catalogo_id: str | None
    contexto_md: str | None


class EnlaceInterno(TypedDict):
    anchor: str
    draft_id: str
    score: float


class PipelineState(TypedDict, total=False):
    # ---- Entrada ----
    medio_id: UUID
    run_id: UUID
    redactor_id: UUID | None
    estilo_id: UUID | None
    trigger_tipo: Literal["manual", "automatizacion", "evergreen"]
    senal_id: UUID | None
    tema_input: str | None
    categoria: str | None

    # ---- detect ----
    tema_final: str
    angulo: str
    urgencia: Literal["breaking", "normal", "evergreen"]
    tipo_run: Literal["nuevo", "actualizacion"]
    draft_actualizar_id: UUID | None
    detect_motivo_aborto: str | None    # 'fuentes_insuficientes', 'senal_ya_cubierta'…

    # ---- research ----
    fuentes: list[Fuente]
    hechos_verificados: list[Hecho]
    entidades: list[Entidad]
    research_motivo_aborto: str | None

    # ---- write ----
    titulo: str
    meta_title: str
    meta_descr: str
    slug: str
    cuerpo_md: str
    write_intentos: int                  # se incrementa si review pide retry

    # ---- review ----
    review_aprobado: bool
    review_errores: list[str]
    review_sugerencias: list[str]
    requiere_revision_humana: bool

    # ---- enrich ----
    enlaces_internos: list[EnlaceInterno]
    schema_jsonld: dict[str, object]
    imagen_destacada_id: UUID | None
    imagen_destacada_url: str | None
    tags_cms: list[str]

    # ---- publish ----
    draft_id: UUID | None
    modo_publish: Literal["bandeja", "borrador_cms", "auto"]
    editor_url: str | None
    cms_url: str | None
    cms_id_externo: str | None
