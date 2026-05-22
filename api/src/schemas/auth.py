from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    medios: list["MedioMembership"]


class MedioMembership(BaseModel):
    medio_id: str
    medio_slug: str
    medio_nombre: str
    rol: str


LoginResponse.model_rebuild()
