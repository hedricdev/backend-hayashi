# Task 02 — Autenticação JWT (Admin + Vendedor)

## Objetivo
Substituir a autenticação por API Key por um sistema JWT completo com dois papéis: `admin` e `vendedor`. Admins têm acesso total; vendedores só veem dados relacionados a eles na planilha.

## Contexto de Papéis

- **admin**: acessa todos os endpoints, cria/edita usuários, vê todas as vendas
- **vendedor**: acessa o dashboard e a tabela de vendas filtrada pelo seu `nome_planilha` (valor que aparece na coluna U da planilha Google Sheets, preenchido pelo n8n)

## Arquivos a Criar/Editar

- `models/usuario.py` — modelo SQLAlchemy
- `auth.py` — utilitários JWT + dependencies FastAPI
- `routers/auth.py` — endpoints de login e perfil
- `routers/usuarios.py` — CRUD de usuários (admin only)
- `config.py` — adicionar campos JWT
- `main.py` — incluir novos routers

---

## Implementação

### `models/usuario.py`

```python
import enum
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Enum as SAEnum, Integer, String
from database import Base


class Role(str, enum.Enum):
    admin = "admin"
    vendedor = "vendedor"


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(100), nullable=False)
    email = Column(String(200), unique=True, nullable=False, index=True)
    senha_hash = Column(String(200), nullable=False)
    role = Column(SAEnum(Role), nullable=False, default=Role.vendedor)
    nome_planilha = Column(String(100), nullable=True)  # deve bater com coluna U da planilha
    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
```

> **Nota sobre Task 01**: a tabela `vendedores` do modelo anterior é substituída por esta. Usuários com `role=vendedor` são os vendedores do sistema. A FK `clientes_vendedor.vendedor_id` passa a apontar para `usuarios.id`.

---

### `config.py` — adicionar campos

```python
JWT_SECRET_KEY: str
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = 480  # 8 horas
```

---

### `auth.py`

Utilitários e dependencies do FastAPI:

```python
from datetime import datetime, timedelta
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.usuario import Role, Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user: Usuario) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "nome_planilha": user.nome_planilha,
        "exp": datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
) -> Usuario:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: int = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise credentials_exception

    user = db.query(Usuario).filter(Usuario.id == user_id, Usuario.ativo == True).first()
    if not user:
        raise credentials_exception
    return user


def require_admin(current_user: Annotated[Usuario, Depends(get_current_user)]) -> Usuario:
    if current_user.role != Role.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a administradores")
    return current_user
```

---

### `routers/auth.py`

```python
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import create_access_token, get_current_user, verify_password
from database import get_db
from models.usuario import Role, Usuario

router = APIRouter()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    nome: str


class MeResponse(BaseModel):
    id: int
    nome: str
    email: str
    role: Role
    nome_planilha: str | None

    model_config = {"from_attributes": True}


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
    )


@router.get("/me", response_model=MeResponse)
def me(current_user: Annotated[Usuario, Depends(get_current_user)]):
    return current_user
```

---

### `routers/usuarios.py`

CRUD de usuários — apenas admins:

```python
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from auth import hash_password, require_admin
from database import get_db
from models.usuario import Role, Usuario

router = APIRouter()


class CriarUsuarioRequest(BaseModel):
    nome: str
    email: EmailStr
    senha: str
    role: Role = Role.vendedor
    nome_planilha: str | None = None


class AtualizarUsuarioRequest(BaseModel):
    nome: str | None = None
    email: EmailStr | None = None
    senha: str | None = None
    role: Role | None = None
    nome_planilha: str | None = None
    ativo: bool | None = None


class UsuarioResponse(BaseModel):
    id: int
    nome: str
    email: str
    role: Role
    nome_planilha: str | None
    ativo: bool

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
        email=body.email.lower(),
        senha_hash=hash_password(body.senha),
        role=body.role,
        nome_planilha=body.nome_planilha,
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
    db.commit()
    db.refresh(usuario)
    return usuario
```

---

### `main.py` — incluir novos routers

```python
from routers import auth as auth_router, usuarios as usuarios_router

app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
app.include_router(usuarios_router.router, prefix="/admin/usuarios", tags=["usuarios"])
```

Os routers `importar` e `status` agora dependem de `get_current_user` em vez de API key — a dependency é adicionada nos próprios endpoints (tasks 03 e 07), não globalmente.

---

## Migrações Alembic

Após implementar, adicionar nova migration:
```bash
alembic revision --autogenerate -m "add usuarios table"
alembic upgrade head
```

## Usuário Admin Inicial

Criar um script `scripts/criar_admin.py` para bootstrapar o primeiro admin:

```python
from database import SessionLocal
from auth import hash_password
from models.usuario import Role, Usuario

db = SessionLocal()
admin = Usuario(
    nome="Admin",
    email="admin@hayashi.com.br",
    senha_hash=hash_password("trocar_esta_senha"),
    role=Role.admin,
)
db.add(admin)
db.commit()
print(f"Admin criado: {admin.email}")
db.close()
```

---

## Critérios de Aceitação

- `POST /auth/login` com credenciais válidas retorna JWT + role + nome
- `POST /auth/login` com credenciais inválidas retorna 401
- `GET /auth/me` sem token retorna 401; com token válido retorna dados do usuário
- `POST /admin/usuarios` por um vendedor retorna 403
- `POST /admin/usuarios` por um admin cria o usuário e retorna 201
- Email duplicado ao criar usuário retorna 409
- Token expirado retorna 401
