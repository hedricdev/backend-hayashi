from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from database import Base


class Importacao(Base):
    __tablename__ = "importacoes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    iniciado_em = Column(DateTime, default=datetime.utcnow)
    finalizado_em = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False)
    total_importado = Column(Integer, default=0)
    total_erro = Column(Integer, default=0)
    log = Column(Text, nullable=True)
    tipo = Column(String(20), nullable=True, default="lista_diaria")


class ClienteVendedor(Base):
    __tablename__ = "clientes_vendedor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cliente_nome = Column(String(200), nullable=False)
    vendedor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    ativo = Column(Boolean, default=True)
