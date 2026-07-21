from collections import defaultdict
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.usuario import Usuario
from models.venda_historico import VendaHistorico
from services.margem import CustoAplicador, custo_medio_por_produto_mes

router = APIRouter()

MES_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


def _f(v) -> float:
    return round(float(v or 0), 2)


class ResumoMargem(BaseModel):
    receita_total: float
    cmv_total: float
    margem_total: float
    margem_pct: float


class MesMargem(BaseModel):
    mes: str
    mes_label: str
    receita: float
    cmv: float
    margem: float
    margem_pct: float


class ItemMargem(BaseModel):
    nome: str
    receita: float
    cmv: float
    margem: float
    margem_pct: float
    caixas: int
    sem_custo: bool
    margem_negativa: bool


class OpcoesFiltroMargem(BaseModel):
    produtos: list[str]
    categorias: list[str]
    data_inicio: Optional[str] = None
    data_fim: Optional[str] = None


@router.get("/opcoes-filtro", response_model=OpcoesFiltroMargem)
def get_opcoes_filtro(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    produtos = [
        r[0] for r in
        db.query(distinct(VendaHistorico.produto)).order_by(VendaHistorico.produto).all()
        if r[0]
    ]
    categorias = [
        r[0] for r in
        db.query(distinct(VendaHistorico.categoria)).order_by(VendaHistorico.categoria).all()
        if r[0]
    ]
    inicio = db.query(func.min(VendaHistorico.data)).scalar()
    fim = db.query(func.max(VendaHistorico.data)).scalar()
    return OpcoesFiltroMargem(
        produtos=produtos,
        categorias=categorias,
        data_inicio=inicio.isoformat() if inicio else None,
        data_fim=fim.isoformat() if fim else None,
    )


def _linhas_margem(
    db: Session,
    data_inicio: Optional[date],
    data_fim: Optional[date],
    produto: Optional[str],
    categoria: Optional[str],
) -> list[dict]:
    """Uma linha por (produto, mes) dentro do filtro pedido, com CMV
    aplicado via custo medio ponderado (services/margem.py). E o bloco
    comum que todos os endpoints agregam de formas diferentes.
    """
    custos = custo_medio_por_produto_mes(db)
    aplicador = CustoAplicador(custos)

    mes_trunc = func.date_trunc("month", VendaHistorico.data)
    q = db.query(
        VendaHistorico.produto,
        VendaHistorico.categoria,
        mes_trunc.label("mes"),
        func.sum(VendaHistorico.qtde).label("qtde"),
        func.sum(VendaHistorico.total_item).label("receita"),
    ).group_by(VendaHistorico.produto, VendaHistorico.categoria, mes_trunc)

    if data_inicio:
        q = q.filter(VendaHistorico.data >= data_inicio)
    if data_fim:
        q = q.filter(VendaHistorico.data <= data_fim)
    if produto:
        q = q.filter(VendaHistorico.produto == produto)
    if categoria:
        q = q.filter(VendaHistorico.categoria == categoria)

    linhas = []
    for r in q.all():
        mes = r.mes.date() if hasattr(r.mes, "date") else r.mes
        qtde = float(r.qtde or 0)
        receita = _f(r.receita)
        custo_unit = aplicador.custo(r.produto, mes)
        sem_custo = custo_unit is None
        cmv = _f((custo_unit or 0) * qtde)
        linhas.append({
            "produto": r.produto,
            "categoria": r.categoria or "Outros",
            "mes": mes,
            "qtde": qtde,
            "receita": receita,
            "cmv": cmv,
            "margem": round(receita - cmv, 2),
            "sem_custo": sem_custo,
        })
    return linhas


@router.get("/resumo", response_model=ResumoMargem)
def get_resumo(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    categoria: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    linhas = _linhas_margem(db, data_inicio, data_fim, produto, categoria)
    receita_total = round(sum(l["receita"] for l in linhas), 2)
    cmv_total = round(sum(l["cmv"] for l in linhas), 2)
    margem_total = round(receita_total - cmv_total, 2)
    margem_pct = round((margem_total / receita_total * 100) if receita_total else 0, 1)
    return ResumoMargem(
        receita_total=receita_total,
        cmv_total=cmv_total,
        margem_total=margem_total,
        margem_pct=margem_pct,
    )


@router.get("/mensal", response_model=list[MesMargem])
def get_mensal(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    categoria: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    linhas = _linhas_margem(db, data_inicio, data_fim, produto, categoria)
    por_mes: dict[date, dict] = defaultdict(lambda: {"receita": 0.0, "cmv": 0.0})
    for l in linhas:
        por_mes[l["mes"]]["receita"] += l["receita"]
        por_mes[l["mes"]]["cmv"] += l["cmv"]

    result = []
    for mes in sorted(por_mes.keys()):
        d = por_mes[mes]
        receita = round(d["receita"], 2)
        cmv = round(d["cmv"], 2)
        margem = round(receita - cmv, 2)
        result.append(MesMargem(
            mes=mes.strftime("%Y-%m"),
            mes_label=f"{MES_PT[mes.month]}/{str(mes.year)[2:]}",
            receita=receita,
            cmv=cmv,
            margem=margem,
            margem_pct=round((margem / receita * 100) if receita else 0, 1),
        ))
    return result


def _agrega_por(linhas: list[dict], chave: str) -> list[ItemMargem]:
    grupos: dict[str, dict] = defaultdict(lambda: {"receita": 0.0, "cmv": 0.0, "qtde": 0.0, "sem_custo": False})
    for l in linhas:
        g = grupos[l[chave]]
        g["receita"] += l["receita"]
        g["cmv"] += l["cmv"]
        g["qtde"] += l["qtde"]
        if l["sem_custo"]:
            g["sem_custo"] = True

    itens = []
    for nome, g in grupos.items():
        receita = round(g["receita"], 2)
        cmv = round(g["cmv"], 2)
        margem = round(receita - cmv, 2)
        itens.append(ItemMargem(
            nome=nome,
            receita=receita,
            cmv=cmv,
            margem=margem,
            margem_pct=round((margem / receita * 100) if receita else 0, 1),
            caixas=int(g["qtde"]),
            sem_custo=g["sem_custo"],
            margem_negativa=margem < 0,
        ))
    # pior margem primeiro — e o que interessa achar rapido
    itens.sort(key=lambda i: i.margem)
    return itens


@router.get("/por-produto", response_model=list[ItemMargem])
def get_por_produto(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    categoria: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    linhas = _linhas_margem(db, data_inicio, data_fim, produto, categoria)
    return _agrega_por(linhas, "produto")


@router.get("/por-categoria", response_model=list[ItemMargem])
def get_por_categoria(
    data_inicio: Optional[date] = Query(default=None),
    data_fim: Optional[date] = Query(default=None),
    produto: Optional[str] = Query(default=None),
    categoria: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    linhas = _linhas_margem(db, data_inicio, data_fim, produto, categoria)
    return _agrega_por(linhas, "categoria")
