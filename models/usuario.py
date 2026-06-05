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
    nome_planilha = Column(String(100), nullable=True)
    cpf = Column(String(14), nullable=True)
    ativo = Column(Boolean, default=True)
    deve_trocar_senha = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
