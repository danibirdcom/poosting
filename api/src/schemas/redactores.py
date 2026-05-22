from uuid import UUID

from pydantic import BaseModel, Field


class RedactorIn(BaseModel):
    nombre_publico: str = Field(min_length=1, max_length=200)
    usuario_id: UUID | None = None


class RedactorOut(BaseModel):
    id: UUID
    nombre_publico: str
    usuario_id: UUID | None
    activo: bool
