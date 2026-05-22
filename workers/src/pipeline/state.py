"""Estado canónico del pipeline. Se persiste en ``run_steps`` entre nodos."""

from __future__ import annotations

from typing import Literal, TypedDict
from uuid import UUID


class Fuente(TypedDict, total=False):
    url: str
    titulo: str | None
    publicado_at: str | None
    autoridad_score: float | None
    contenido_md: str | None


class Hecho(TypedDict):
    afirmacion: str
    fuentes: list[str]  # urls


class Entidad(TypedDict, total=False):
    tipo: Literal["persona", "organizacion", "lugar", "evento"]
    nombre: str
    wikidata_id: str | None
    catalogo_id: str | None


class PipelineState(TypedDict, total=False):
    # Entrada
    medio_id: UUID
    run_id: UUID
    redactor_id: UUID | None
    estilo_id: UUID | None
    trigger_tipo: Literal["manual", "automatizacion", "evergreen"]
    senal_id: UUID | None
    tema_input: str | None
    categoria: str | None

    # detect
    tema_final: str
    angulo: str
    urgencia: Literal["breaking", "normal", "evergreen"]
    tipo_run: Literal["nuevo", "actualizacion"]
    draft_actualizar_id: UUID | None

    # research
    fuentes: list[Fuente]
    hechos_verificados: list[Hecho]
    entidades: list[Entidad]

    # write
    titulo: str
    meta_title: str
    meta_descr: str
    slug: str
    cuerpo_md: str

    # review
    review_aprobado: bool
    review_errores: list[str]
    review_sugerencias: list[str]

    # enrich
    enlaces_internos: list[dict[str, object]]
    schema_jsonld: dict[str, object]
    imagen_destacada_id: UUID | None

    # publish
    cms_url: str | None
    cms_id_externo: str | None
