from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint

from database import Base


class VendaHistorico(Base):
    __tablename__ = "vendas_historico"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data = Column(Date, nullable=False, index=True)
    cliente = Column(String(200), nullable=False, index=True)
    produto = Column(String(200), nullable=False)
    qtde = Column(Integer, nullable=False, default=0)
    dvl = Column(Integer, nullable=False, default=0)
    preco_item = Column(Numeric(10, 2), nullable=True)
    total_item = Column(Numeric(10, 2), nullable=True)
    valor_aberto = Column(Numeric(10, 2), nullable=False, default=0)
    data_recebimento = Column(Date, nullable=True)
    categoria = Column(String(100), nullable=True)
    fornecedor = Column(String(100), nullable=True)
    importado_em = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "data", "cliente", "produto", "qtde", "preco_item",
            name="uq_venda_historico",
        ),
    )
