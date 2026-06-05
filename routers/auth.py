from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from database import get_db
from models.usuario import Role, Usuario

router = APIRouter()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    nome: str
    deve_trocar_senha: bool


class MeResponse(BaseModel):
    id: int
    nome: str
    email: str
    role: Role
    nome_planilha: str | None
    deve_trocar_senha: bool

    model_config = {"from_attributes": True}


class TrocarSenhaRequest(BaseModel):
    nova_senha: str


@router.post("/login", response_model=TokenResponse)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
):
    user = db.query(Usuario).filter(
        Usuario.email == form.username.lower(),
        Usuario.ativo == True,
    ).first()
    if not user or not verify_password(form.password, user.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha inválidos",
        )
    return TokenResponse(
        access_token=create_access_token(user),
        role=user.role,
        nome=user.nome,
        deve_trocar_senha=bool(user.deve_trocar_senha),
    )


@router.get("/me", response_model=MeResponse)
def me(current_user: Annotated[Usuario, Depends(get_current_user)]):
    return current_user


@router.post("/trocar-senha", response_model=TokenResponse)
def trocar_senha(
    body: TrocarSenhaRequest,
    current_user: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    if len(body.nova_senha) < 6:
        raise HTTPException(status_code=400, detail="A senha deve ter ao menos 6 caracteres")
    current_user.senha_hash = hash_password(body.nova_senha)
    current_user.deve_trocar_senha = False
    db.commit()
    db.refresh(current_user)
    return TokenResponse(
        access_token=create_access_token(current_user),
        role=current_user.role,
        nome=current_user.nome,
        deve_trocar_senha=False,
    )
