from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint

from database import Base


class CompraHistorico(Base):
    __tablename__ = "compras_historico"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_compra = Column(Date, nullable=False, index=True)
    produto = Column(String(200), nullable=False, index=True)
    fornecedor = Column(String(200), nullable=False, index=True)
    qtde = Column(Integer, nullable=False, default=0)
    valor_unitario = Column(Numeric(12, 4), nullable=True)
    valor_total = Column(Numeric(12, 2), nullable=False, default=0)
    valor_aberto = Column(Numeric(12, 2), nullable=False, default=0)
    data_pagamento = Column(Date, nullable=True)
    devolucao = Column(Integer, nullable=False, default=0)
    ocorrencia = Column(Integer, nullable=False, default=0)
    importado_em = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "data_compra", "produto", "fornecedor", "qtde", "valor_unitario",
            "valor_total", "ocorrencia",
            name="uq_compra_historico",
        ),
    )
