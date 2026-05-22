"""CRUD básico de redactores. Todo limitado al medio activo por RLS."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from src.db.pool import tenant_connection
from src.schemas.redactores import RedactorIn, RedactorOut
from src.tenancy import Ctx, RequestContext

router = APIRouter(prefix="/redactores", tags=["redactores"])


def _require_role(ctx: RequestContext, roles: set[str]) -> None:
    if ctx.es_superadmin:
        return
    if ctx.rol not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "rol insuficiente")


@router.get("", response_model=list[RedactorOut])
async def listar(ctx: RequestContext = Ctx) -> list[RedactorOut]:
    async with tenant_connection(ctx.medio_id) as conn:
        rows = await conn.fetch(
            "SELECT id, nombre_publico, usuario_id, activo FROM redactores ORDER BY nombre_publico"
        )
    return [RedactorOut(**dict(r)) for r in rows]


@router.post("", response_model=RedactorOut, status_code=status.HTTP_201_CREATED)
async def crear(body: RedactorIn, ctx: RequestContext = Ctx) -> RedactorOut:
    _require_role(ctx, {"editor_jefe"})
    async with tenant_connection(ctx.medio_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO redactores (medio_id, usuario_id, nombre_publico)
            VALUES ($1, $2, $3)
            RETURNING id, nombre_publico, usuario_id, activo
            """,
            ctx.medio_id,
            body.usuario_id,
            body.nombre_publico,
        )
    assert row is not None
    return RedactorOut(**dict(row))


@router.delete("/{redactor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def desactivar(redactor_id: UUID, ctx: RequestContext = Ctx) -> None:
    _require_role(ctx, {"editor_jefe"})
    async with tenant_connection(ctx.medio_id) as conn:
        result = await conn.execute(
            "UPDATE redactores SET activo = FALSE WHERE id = $1", redactor_id
        )
    if result.endswith(" 0"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "redactor no encontrado")
