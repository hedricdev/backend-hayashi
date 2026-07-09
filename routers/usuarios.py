from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import hash_password, require_admin
from database import get_db
from models.usuario import Role, Usuario

router = APIRouter()


class CriarUsuarioRequest(BaseModel):
    nome: str
    cpf: str | None = None
    email: EmailStr
    senha: str
    role: Role = Role.vendedor
    nome_planilha: str | None = None


class AtualizarUsuarioRequest(BaseModel):
    nome: str | None = None
    cpf: str | None = None
    email: EmailStr | None = None
    senha: str | None = None
    role: Role | None = None
    nome_planilha: str | None = None
    ativo: bool | None = None
    deve_trocar_senha: bool | None = None


class UsuarioResponse(BaseModel):
    id: int
    nome: str
    cpf: str | None
    email: str
    role: Role
    nome_planilha: str | None
    ativo: bool
    deve_trocar_senha: bool

    model_config = {"from_attributes": True}


@router.post("", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def criar_usuario(
    body: CriarUsuarioRequest,
    _: Annotated[Usuario, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    if db.query(Usuario).filter(Usuario.email == body.email.lower()).first():
        raise HTTPException(status_code=409, detail="Email já cadastrado")
    usuario = Usuario(
        nome=body.nome,
        cpf=body.cpf,
        email=body.email.lower(),
        senha_hash=hash_password(body.senha),
        role=body.role,
        nome_planilha=body.nome_planilha,
        deve_trocar_senha=True,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@router.get("", response_model=list[UsuarioResponse])
def listar_usuarios(
    _: Annotated[Usuario, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    return db.query(Usuario).order_by(Usuario.nome).all()


@router.patch("/{usuario_id}", response_model=UsuarioResponse)
def atualizar_usuario(
    usuario_id: int,
    body: AtualizarUsuarioRequest,
    _: Annotated[Usuario, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if body.nome is not None:
        usuario.nome = body.nome
    if body.cpf is not None:
        usuario.cpf = body.cpf
    if body.email is not None:
        usuario.email = body.email.lower()
    if body.senha is not None:
        usuario.senha_hash = hash_password(body.senha)
    if body.role is not None:
        usuario.role = body.role
    if body.nome_planilha is not None:
        usuario.nome_planilha = body.nome_planilha
    if body.ativo is not None:
        usuario.ativo = body.ativo
    if body.deve_trocar_senha is not None:
        usuario.deve_trocar_senha = body.deve_trocar_senha
    db.commit()
    db.refresh(usuario)
    return usuario


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_usuario(
    usuario_id: int,
    current_user: Annotated[Usuario, Depends(require_admin)],
    db: Session = Depends(get_db),
):
    if usuario_id == current_user.id:
        raise HTTPException(status_code=400, detail="Não é possível excluir sua própria conta")
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    try:
        db.delete(usuario)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Não é possível excluir: este usuário tem registros vinculados (ex: clientes atribuídos)",
        )
