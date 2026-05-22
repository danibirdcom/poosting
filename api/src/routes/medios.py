"""Información del medio activo en el contexto del request."""

from fastapi import APIRouter

from src.db.pool import tenant_connection
from src.tenancy import Ctx, RequestContext

router = APIRouter(prefix="/medios", tags=["medios"])


@router.get("/actual")
async def medio_actual(ctx: RequestContext = Ctx) -> dict[str, object]:
    async with tenant_connection(ctx.medio_id) as conn:
        row = await conn.fetchrow(
            "SELECT id, slug, nombre, cms_tipo, activo FROM medios WHERE id = $1",
            ctx.medio_id,
        )
    if row is None:
        # RLS lo ocultó: no debería pasar si get_request_context validó membresía
        return {"error": "medio no accesible"}
    return dict(row)
