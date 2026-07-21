from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint

from database import Base


class DespesaHistorico(Base):
    __tablename__ = "despesas_historico"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_despesa = Column(Date, nullable=False, index=True)
    descricao = Column(String(200), nullable=False, index=True)
    loja = Column(String(100), nullable=False)
    credor = Column(String(200), nullable=False)
    data_vencimento = Column(Date, nullable=True)
    valor = Column(Numeric(12, 2), nullable=False, default=0)
    valor_aberto = Column(Numeric(12, 2), nullable=False, default=0)
    data_pagamento = Column(Date, nullable=True)
    ocorrencia = Column(Integer, nullable=False, default=0)
    importado_em = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "data_despesa", "descricao", "loja", "credor", "data_vencimento",
            "valor", "ocorrencia",
            name="uq_despesa_historico",
        ),
    )
