from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.compra_historico import CompraHistorico
from models.despesa_historico import DespesaHistorico
from models.usuario import Role, Usuario
from models.venda_historico import VendaHistorico

router = APIRouter()

MES_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


def _f(v) -> float:
    return round(float(v or 0), 2)


def _exigir_admin(current_user: Usuario):
    if current_user.role != Role.admin:
        raise HTTPException(403, "Acesso restrito a administradores")


# ── Pydantic ─────────────────────────────────────────────────────────────────

class ResumoFluxoCaixa(BaseModel):
    entradas_total: float
    saidas_total: float
    saldo_acumulado: float
    total_a_receber: float
    total_a_pagar: float


class MesFluxoCaixa(BaseModel):
    mes: str
    mes_label: str
    entradas: float
    saidas: float
    saldo_acumulado: float


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/resumo", response_model=ResumoFluxoCaixa)
def get_resumo(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Entradas/saídas/saldo dentro do período pedido (sem filtro, é o
    histórico completo desde 2023). "Saldo" aqui é sempre "entradas menos
    saídas dentro da janela consultada" — só vira de fato um "saldo
    acumulado desde o início" quando não há filtro nenhum. NÃO é o saldo
    real da conta bancária — não há saldo inicial nem movimentações fora de
    vendas/despesas/compras (empréstimos, transferências etc).

    "A receber"/"a pagar" NÃO respeitam o filtro de período — são sempre o
    total em aberto agora (mesmos números de Fiado/Despesas/Compras), já que
    uma dívida em aberto é em aberto agora, independente da janela de datas
    escolhida pra olhar o histórico.

    "Saídas" inclui compras (custo da mercadoria revendida) além das
    despesas operacionais — sem isso, quase toda a entrada parecia lucro,
    já que o maior custo de uma distribuidora é o que ela paga aos
    fornecedores pela mercadoria, não as despesas administrativas.
    """
    _exigir_admin(current_user)

    q_entradas = db.query(func.sum(VendaHistorico.total_item)).filter(
        VendaHistorico.valor_aberto == 0, VendaHistorico.data_recebimento.isnot(None)
    )
    if data_inicio:
        q_entradas = q_entradas.filter(VendaHistorico.data_recebimento >= data_inicio)
    if data_fim:
        q_entradas = q_entradas.filter(VendaHistorico.data_recebimento <= data_fim)
    entradas_total = _f(q_entradas.scalar())

    q_saidas_despesas = db.query(func.sum(DespesaHistorico.valor)).filter(
        DespesaHistorico.valor_aberto == 0, DespesaHistorico.data_pagamento.isnot(None)
    )
    if data_inicio:
        q_saidas_despesas = q_saidas_despesas.filter(DespesaHistorico.data_pagamento >= data_inicio)
    if data_fim:
        q_saidas_despesas = q_saidas_despesas.filter(DespesaHistorico.data_pagamento <= data_fim)
    saidas_despesas = _f(q_saidas_despesas.scalar())

    q_saidas_compras = db.query(func.sum(CompraHistorico.valor_total)).filter(
        CompraHistorico.valor_aberto == 0, CompraHistorico.data_pagamento.isnot(None)
    )
    if data_inicio:
        q_saidas_compras = q_saidas_compras.filter(CompraHistorico.data_pagamento >= data_inicio)
    if data_fim:
        q_saidas_compras = q_saidas_compras.filter(CompraHistorico.data_pagamento <= data_fim)
    saidas_compras = _f(q_saidas_compras.scalar())

    saidas_total = round(saidas_despesas + saidas_compras, 2)
    total_a_receber = _f(
        db.query(func.sum(VendaHistorico.valor_aberto))
        .filter(VendaHistorico.valor_aberto > 0)
        .scalar()
    )
    a_pagar_despesas = _f(
        db.query(func.sum(DespesaHistorico.valor_aberto))
        .filter(DespesaHistorico.valor_aberto > 0)
        .scalar()
    )
    a_pagar_compras = _f(
        db.query(func.sum(CompraHistorico.valor_aberto))
        .filter(CompraHistorico.valor_aberto > 0)
        .scalar()
    )
    total_a_pagar = round(a_pagar_despesas + a_pagar_compras, 2)

    return ResumoFluxoCaixa(
        entradas_total=entradas_total,
        saidas_total=saidas_total,
        saldo_acumulado=round(entradas_total - saidas_total, 2),
        total_a_receber=total_a_receber,
        total_a_pagar=total_a_pagar,
    )


@router.get("/mensal", response_model=list[MesFluxoCaixa])
def get_fluxo_mensal(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Entradas (vendas recebidas) vs saídas (despesas pagas) por mês, com
    saldo acumulado. Sem data_inicio/data_fim, retorna a série completa —
    o saldo acumulado só faz sentido olhando o histórico desde o início.
    """
    _exigir_admin(current_user)

    q_entradas = db.query(
        func.date_trunc("month", VendaHistorico.data_recebimento).label("mes"),
        func.sum(VendaHistorico.total_item).label("total"),
    ).filter(VendaHistorico.valor_aberto == 0, VendaHistorico.data_recebimento.isnot(None))
    if data_inicio:
        q_entradas = q_entradas.filter(VendaHistorico.data_recebimento >= data_inicio)
    if data_fim:
        q_entradas = q_entradas.filter(VendaHistorico.data_recebimento <= data_fim)
    entradas_por_mes = {
        r.mes.date(): _f(r.total) for r in q_entradas.group_by("mes").all()
    }

    q_despesas = db.query(
        func.date_trunc("month", DespesaHistorico.data_pagamento).label("mes"),
        func.sum(DespesaHistorico.valor).label("total"),
    ).filter(DespesaHistorico.valor_aberto == 0, DespesaHistorico.data_pagamento.isnot(None))
    if data_inicio:
        q_despesas = q_despesas.filter(DespesaHistorico.data_pagamento >= data_inicio)
    if data_fim:
        q_despesas = q_despesas.filter(DespesaHistorico.data_pagamento <= data_fim)
    despesas_por_mes = {
        r.mes.date(): _f(r.total) for r in q_despesas.group_by("mes").all()
    }

    q_compras = db.query(
        func.date_trunc("month", CompraHistorico.data_pagamento).label("mes"),
        func.sum(CompraHistorico.valor_total).label("total"),
    ).filter(CompraHistorico.valor_aberto == 0, CompraHistorico.data_pagamento.isnot(None))
    if data_inicio:
        q_compras = q_compras.filter(CompraHistorico.data_pagamento >= data_inicio)
    if data_fim:
        q_compras = q_compras.filter(CompraHistorico.data_pagamento <= data_fim)
    compras_por_mes = {
        r.mes.date(): _f(r.total) for r in q_compras.group_by("mes").all()
    }

    saidas_por_mes = {
        m: round(despesas_por_mes.get(m, 0.0) + compras_por_mes.get(m, 0.0), 2)
        for m in set(despesas_por_mes) | set(compras_por_mes)
    }

    meses = sorted(set(entradas_por_mes) | set(saidas_por_mes))

    resultado = []
    saldo = 0.0
    for m in meses:
        entradas = entradas_por_mes.get(m, 0.0)
        saidas = saidas_por_mes.get(m, 0.0)
        saldo = round(saldo + entradas - saidas, 2)
        resultado.append(
            MesFluxoCaixa(
                mes=m.strftime("%Y-%m"),
                mes_label=f"{MES_PT[m.month]}/{str(m.year)[2:]}",
                entradas=entradas,
                saidas=saidas,
                saldo_acumulado=saldo,
            )
        )
    return resultado
