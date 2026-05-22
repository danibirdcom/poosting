"""Login: devuelve JWT + lista de medios a los que pertenece el usuario."""

from fastapi import APIRouter, HTTPException, status

from src.auth.passwords import verify_password
from src.auth.tokens import create_token
from src.db.pool import tenant_connection
from src.schemas.auth import LoginRequest, LoginResponse, MedioMembership

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest) -> LoginResponse:
    async with tenant_connection(None) as conn:
        # usuarios no tiene RLS por medio_id, lectura directa
        user_row = await conn.fetchrow(
            "SELECT id, email, nombre, password_hash, rol_global FROM usuarios WHERE email = $1",
            req.email,
        )
        if user_row is None or not verify_password(req.password, user_row["password_hash"]):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "credenciales inválidas")

        membresias = await conn.fetch(
            """
            SELECT m.id AS medio_id, m.slug, m.nombre, um.rol
              FROM usuarios_medios um
              JOIN medios m ON m.id = um.medio_id
             WHERE um.usuario_id = $1 AND m.activo = TRUE
             ORDER BY m.nombre
            """,
            user_row["id"],
        )

    token = create_token(user_row["id"], user_row["email"], user_row["rol_global"])
    return LoginResponse(
        access_token=token,
        medios=[
            MedioMembership(
                medio_id=str(r["medio_id"]),
                medio_slug=r["slug"],
                medio_nombre=r["nombre"],
                rol=r["rol"],
            )
            for r in membresias
        ],
    )
