from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint

from database import Base


class VendaSemana(Base):
    __tablename__ = "vendas_semana"

    id = Column(Integer, primary_key=True, autoincrement=True)
    semana_ref = Column(Date, nullable=False, index=True)   # segunda-feira da semana
    data = Column(Date, nullable=False, index=True)         # data real do dia
    dia_semana = Column(String(10), nullable=False)         # SEGUNDA, TERÇA, etc.
    vendedor = Column(String(100), nullable=False, index=True)
    cliente = Column(String(200), nullable=False, index=True)
    produto = Column(String(200), nullable=False)
    quantidade = Column(Integer, nullable=False, default=0)
    pagamento = Column(String(50), nullable=True)
    faturamento_estimado = Column(Numeric(10, 2), nullable=True)
    importado_em = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "semana_ref", "dia_semana", "vendedor", "cliente", "produto", "quantidade",
            name="uq_venda_semana",
        ),
    )
