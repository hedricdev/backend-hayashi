from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Numeric, String

from database import Base


class MetaMensal(Base):
    __tablename__ = "metas_mensais"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mes = Column(String(7), nullable=False, unique=True, index=True)  # YYYY-MM
    meta = Column(Numeric(12, 2), nullable=False)
    supermeta = Column(Numeric(12, 2), nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow)
    atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
