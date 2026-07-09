from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Numeric, String

from database import Base


class MetaMensal(Base):
    __tablename__ = "metas_mensais"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mes = Column(String(7), nullable=False, unique=True, index=True)  # YYYY-MM
    meta = Column(Numeric(12, 2), nullable=False)
    supermeta = Column(Numeric(12, 2), nullable=False)
    lucro = Column(Numeric(12, 2), nullable=True)
    lucro_margem_pct = Column(Numeric(5, 2), nullable=True)
    lucro_atualizado_em = Column(DateTime, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
