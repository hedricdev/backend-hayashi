import calendar as _cal
from collections import defaultdict
from datetime import date, datetime
from typing import Annotated

import pytz
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy import func

from auth import get_current_user
from database import get_db
from models.usuario import Role, Usuario
from models.venda_historico import VendaHistorico
from models.venda_semana import VendaSemana
from services.categoria_map import classificar
from services.sheets import get_vendas_semana, get_aba_atual

router = APIRouter()

DIAS_ORDEM = ["SEGUNDA", "TERÇA", "QUARTA", "QUINTA", "SEXTA", "SABADO", "DOMINGO"]


class Produto(BaseModel):
    nome: str
    quantidade: int


class Venda(BaseModel):
    cliente: str
    vendedor: str
    pagamento: str
    preco: str
    produtos: list[Produto]
    dia: str
    data: str | None = None  # ISO (YYYY-MM-DD) — só presente quando vem de vendas_historico (mês)


class RankingVendedor(BaseModel):
    nome: str
    total_caixas: int
    total_vendas: int
    faturamento_estimado: float


class RankingCliente(BaseModel):
    nome: str
    total_caixas: int
    total_vendas: int
    frequencia_dias: int
    ticket_medio: float


class ProdutoVendido(BaseModel):
    nome: str
    total_caixas: int


class CaixasDia(BaseModel):
    dia: str
    total_caixas: int
    faturamento_estimado: float


class TicketGrupo(BaseModel):
    nome: str
    total_caixas: int
    faturamento: float
    ticket_medio: float  # faturamento / caixas — preço médio por caixa


class MixPagamentoItem(BaseModel):
    count: int
    percentual: float


class Resumo(BaseModel):
    total_caixas: int
    total_vendas: int
    faturamento_estimado: float


class PontoComparativoDia(BaseModel):
    dia: int                    # dia do mês (1-31)
    atual: float | None         # faturamento do mês atual nesse dia (None = ainda não chegou lá)
    anterior: float | None      # faturamento do mês anterior nesse dia (None = mês anterior não tem esse dia)


class ComparativoMensal(BaseModel):
    mes_atual_label: str        # ex: "Jul/26"
    mes_anterior_label: str     # ex: "Jun/26"
    faturamento_atual_total: float
    faturamento_anterior_total: float
    serie: list[PontoComparativoDia]


class VendasResponse(BaseModel):
    vendas: list[Venda]
    resumo: Resumo
    ranking_vendedores: list[RankingVendedor]
    ranking_clientes: list[RankingCliente]
    produtos_mais_vendidos: list[ProdutoVendido]
    caixas_por_dia: list[CaixasDia]
    mix_pagamento: dict[str, MixPagamentoItem]
    vendas_em_aberto: list[Venda]
    ticket_por_categoria: list[TicketGrupo]
    ticket_por_fornecedor: list[TicketGrupo]
    dia_atual: str
    comparativo_mensal: ComparativoMensal | None = None


def _precos_list(preco: str) -> list[float]:
    out: list[float] = []
    for parte in preco.replace(",", ".").split("/"):
        try:
            out.append(float(parte.strip()))
        except ValueError:
            pass
    return out


@router.get("", response_model=VendasResponse)
def get_vendas(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    bust: bool = Query(default=False, description="Ignora o cache e busca dados frescos"),
    escopo: str = Query(
        default="meu",
        description="'meu' = apenas as vendas do vendedor logado (usado no dashboard); "
        "'todos' = vendas de todos os vendedores (usado na aba Vendas). "
        "Admin sempre vê todos, independente do parâmetro.",
    ),
):
    # Vendedor enxerga apenas as próprias vendas no dashboard (escopo padrão),
    # mas pode ver as de todos na aba Vendas (escopo=todos). Admin sempre vê tudo.
    incluir_todos = current_user.role == Role.admin or escopo == "todos"
    nome_vendedor = None if incluir_todos else current_user.nome_planilha

    raw = get_vendas_semana(nome_vendedor=nome_vendedor, bust=bust)
    dia_atual = get_aba_atual()

    total_caixas = 0
    faturamento_total = 0.0
    ranking_v: dict[str, dict] = {}
    ranking_c: dict[str, dict] = {}
    produtos_agg: dict[str, int] = {}
    caixas_dia: dict[str, dict] = {}
    mix: dict[str, int] = {}
    ticket_cat: dict[str, dict] = {}
    ticket_forn: dict[str, dict] = {}
    vendas_out: list[Venda] = []
    vendas_em_aberto: list[Venda] = []

    for v in raw:
        caixas = sum(p["quantidade"] for p in v["produtos"])
        precos = _precos_list(v["preco"])
        fat = sum(precos)
        total_caixas += caixas
        faturamento_total += fat

        # Atribui o faturamento da venda a cada produto: quando há um preço por
        # produto (mesmo tamanho), usa-o direto; senão rateia o total pelas caixas.
        for idx, p in enumerate(v["produtos"]):
            if len(precos) == len(v["produtos"]):
                receita = precos[idx]
            elif caixas > 0:
                receita = fat * (p["quantidade"] / caixas)
            else:
                receita = 0.0

            cat, forn = classificar(p["nome"])
            for agg, chave in ((ticket_cat, cat), (ticket_forn, forn)):
                if chave not in agg:
                    agg[chave] = {"nome": chave, "total_caixas": 0, "faturamento": 0.0}
                agg[chave]["total_caixas"] += p["quantidade"]
                agg[chave]["faturamento"] += receita

        # Ranking vendedores
        nv = v["vendedor"]
        if nv not in ranking_v:
            ranking_v[nv] = {"nome": nv, "total_caixas": 0, "total_vendas": 0, "faturamento_estimado": 0.0}
        ranking_v[nv]["total_caixas"] += caixas
        ranking_v[nv]["total_vendas"] += 1
        ranking_v[nv]["faturamento_estimado"] += fat

        # Ranking clientes
        nc = v["cliente"]
        if nc not in ranking_c:
            ranking_c[nc] = {"nome": nc, "total_caixas": 0, "total_vendas": 0, "dias": set(), "faturamento": 0.0}
        ranking_c[nc]["total_caixas"] += caixas
        ranking_c[nc]["total_vendas"] += 1
        ranking_c[nc]["dias"].add(v["dia"])
        ranking_c[nc]["faturamento"] += fat

        # Produtos mais vendidos
        for p in v["produtos"]:
            produtos_agg[p["nome"]] = produtos_agg.get(p["nome"], 0) + p["quantidade"]

        # Caixas por dia
        dia = v["dia"]
        if dia not in caixas_dia:
            caixas_dia[dia] = {"dia": dia, "total_caixas": 0, "faturamento_estimado": 0.0}
        caixas_dia[dia]["total_caixas"] += caixas
        caixas_dia[dia]["faturamento_estimado"] = round(caixas_dia[dia]["faturamento_estimado"] + fat, 2)

        # Mix de pagamento
        pag = v["pagamento"].strip().upper() or "EM ABERTO"
        mix[pag] = mix.get(pag, 0) + 1

        venda_obj = Venda(
            cliente=v["cliente"],
            vendedor=nv,
            pagamento=v["pagamento"],
            preco=v["preco"],
            produtos=[Produto(nome=p["nome"], quantidade=p["quantidade"]) for p in v["produtos"]],
            dia=v["dia"],
        )
        vendas_out.append(venda_obj)

        if not v["pagamento"].strip():
            vendas_em_aberto.append(venda_obj)

    ranking_v_list = [
        RankingVendedor(**{**r, "faturamento_estimado": round(r["faturamento_estimado"], 2)})
        for r in sorted(ranking_v.values(), key=lambda x: x["total_caixas"], reverse=True)
    ]

    ranking_c_list = [
        RankingCliente(
            nome=c["nome"],
            total_caixas=c["total_caixas"],
            total_vendas=c["total_vendas"],
            frequencia_dias=len(c["dias"]),
            ticket_medio=round(c["faturamento"] / c["total_vendas"], 2) if c["total_vendas"] else 0.0,
        )
        for c in sorted(ranking_c.values(), key=lambda x: x["total_caixas"], reverse=True)
    ]

    produtos_list = [
        ProdutoVendido(nome=k, total_caixas=v)
        for k, v in sorted(produtos_agg.items(), key=lambda x: x[1], reverse=True)
    ]

    caixas_dia_list = [
        CaixasDia(**caixas_dia[d])
        if d in caixas_dia
        else CaixasDia(dia=d, total_caixas=0, faturamento_estimado=0.0)
        for d in DIAS_ORDEM
    ]

    total_mix = sum(mix.values()) or 1
    mix_out = {
        k: MixPagamentoItem(count=cnt, percentual=round(cnt / total_mix * 100, 1))
        for k, cnt in sorted(mix.items(), key=lambda x: x[1], reverse=True)
    }

    def _ticket_list(agg: dict[str, dict]) -> list[TicketGrupo]:
        return [
            TicketGrupo(
                nome=g["nome"],
                total_caixas=g["total_caixas"],
                faturamento=round(g["faturamento"], 2),
                ticket_medio=round(g["faturamento"] / g["total_caixas"], 2)
                if g["total_caixas"]
                else 0.0,
            )
            for g in sorted(agg.values(), key=lambda x: x["faturamento"], reverse=True)
        ]

    ticket_categoria_list = _ticket_list(ticket_cat)
    ticket_fornecedor_list = _ticket_list(ticket_forn)

    return VendasResponse(
        vendas=vendas_out,
        resumo=Resumo(
            total_caixas=total_caixas,
            total_vendas=len(vendas_out),
            faturamento_estimado=round(faturamento_total, 2),
        ),
        ranking_vendedores=ranking_v_list,
        ranking_clientes=ranking_c_list,
        produtos_mais_vendidos=produtos_list,
        caixas_por_dia=caixas_dia_list,
        mix_pagamento=mix_out,
        vendas_em_aberto=vendas_em_aberto,
        ticket_por_categoria=ticket_categoria_list,
        ticket_por_fornecedor=ticket_fornecedor_list,
        dia_atual=dia_atual,
    )


_DIAS_SEMANA = ["SEGUNDA", "TERÇA", "QUARTA", "QUINTA", "SEXTA", "SABADO", "DOMINGO"]
_MES_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


@router.get("/mensal", response_model=VendasResponse)
def get_vendas_mensal(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """
    Dados do mês atual.
    Fonte principal: vendas_historico (iFruti) — completo e confiável.
    Ranking de vendedores: vendas_semana (planilha) — única fonte com info de vendedor.
    """
    brasilia = pytz.timezone("America/Sao_Paulo")
    hoje = datetime.now(brasilia)
    ano, mes = hoje.year, hoje.month
    primeiro_dia = date(ano, mes, 1)
    ultimo_dia = date(ano, mes, _cal.monthrange(ano, mes)[1])
    dia_atual_str = _DIAS_SEMANA[hoje.weekday()]

    # ── Dados principais: iFruti ──────────────────────────────────────────────
    hist_rows = (
        db.query(VendaHistorico)
        .filter(VendaHistorico.data >= primeiro_dia, VendaHistorico.data <= ultimo_dia)
        .order_by(VendaHistorico.data, VendaHistorico.cliente, VendaHistorico.produto)
        .all()
    )

    groups: dict = defaultdict(list)
    for r in hist_rows:
        dia_semana = _DIAS_SEMANA[r.data.weekday()]
        groups[(r.data, dia_semana, r.cliente)].append(r)

    total_caixas = 0
    faturamento_total = 0.0
    ranking_c: dict[str, dict] = {}
    produtos_agg: dict[str, int] = {}
    caixas_dia: dict[str, dict] = {}
    mix: dict[str, int] = {}
    ticket_cat: dict[str, dict] = {}
    ticket_forn: dict[str, dict] = {}
    vendas_out: list[Venda] = []
    vendas_em_aberto: list[Venda] = []

    for (data_venda, dia_semana, cliente), g_rows in groups.items():
        caixas = sum(r.qtde for r in g_rows)
        fat = sum(float(r.total_item or 0) for r in g_rows)
        aberto = sum(float(r.valor_aberto or 0) for r in g_rows)
        total_caixas += caixas
        faturamento_total += fat

        for r in g_rows:
            cat = r.categoria or "Outros"
            forn = r.fornecedor or "Outros"
            fat_row = float(r.total_item or 0)
            for agg, chave in ((ticket_cat, cat), (ticket_forn, forn)):
                if chave not in agg:
                    agg[chave] = {"nome": chave, "total_caixas": 0, "faturamento": 0.0}
                agg[chave]["total_caixas"] += r.qtde
                agg[chave]["faturamento"] += fat_row

        if cliente not in ranking_c:
            ranking_c[cliente] = {"nome": cliente, "total_caixas": 0, "total_vendas": 0, "dias": set(), "faturamento": 0.0}
        ranking_c[cliente]["total_caixas"] += caixas
        ranking_c[cliente]["total_vendas"] += 1
        ranking_c[cliente]["dias"].add(str(data_venda))
        ranking_c[cliente]["faturamento"] += fat

        for r in g_rows:
            produtos_agg[r.produto] = produtos_agg.get(r.produto, 0) + r.qtde

        if dia_semana not in caixas_dia:
            caixas_dia[dia_semana] = {"dia": dia_semana, "total_caixas": 0, "faturamento_estimado": 0.0}
        caixas_dia[dia_semana]["total_caixas"] += caixas
        caixas_dia[dia_semana]["faturamento_estimado"] = round(
            caixas_dia[dia_semana]["faturamento_estimado"] + fat, 2
        )

        # iFruti não tem tipo de pagamento — classifica por status de recebimento
        pag_key = "EM ABERTO" if aberto > 0 else "RECEBIDO"
        mix[pag_key] = mix.get(pag_key, 0) + 1

        preco_str = "/".join(
            f"{float(r.total_item or 0):.2f}".replace(".", ",") for r in g_rows
        )
        venda_obj = Venda(
            cliente=cliente,
            vendedor="",
            pagamento="" if aberto > 0 else "RECEBIDO",
            preco=preco_str,
            produtos=[Produto(nome=r.produto, quantidade=r.qtde) for r in g_rows],
            dia=dia_semana,
            data=str(data_venda),
        )
        vendas_out.append(venda_obj)
        if aberto > 0:
            vendas_em_aberto.append(venda_obj)

    # ── Ranking vendedores: planilha (única fonte com info de vendedor) ────────
    semana_rows = (
        db.query(
            VendaSemana.vendedor,
            func.sum(VendaSemana.quantidade).label("caixas"),
            func.sum(VendaSemana.faturamento_estimado).label("fat"),
        )
        .filter(VendaSemana.data >= primeiro_dia, VendaSemana.data <= ultimo_dia)
        .group_by(VendaSemana.vendedor)
        .all()
    )
    txn_subq = (
        db.query(VendaSemana.vendedor, VendaSemana.data, VendaSemana.cliente)
        .filter(VendaSemana.data >= primeiro_dia, VendaSemana.data <= ultimo_dia)
        .distinct()
        .subquery()
    )
    txn_map = {
        r.vendedor: r.vendas
        for r in db.query(txn_subq.c.vendedor, func.count().label("vendas"))
        .group_by(txn_subq.c.vendedor)
        .all()
    }
    ranking_v_list = [
        RankingVendedor(
            nome=r.vendedor,
            total_caixas=int(r.caixas or 0),
            total_vendas=txn_map.get(r.vendedor, 0),
            faturamento_estimado=round(float(r.fat or 0), 2),
        )
        for r in sorted(semana_rows, key=lambda x: x.caixas or 0, reverse=True)
    ]

    # ── Monta resposta ─────────────────────────────────────────────────────────
    ranking_c_list = [
        RankingCliente(
            nome=c["nome"],
            total_caixas=c["total_caixas"],
            total_vendas=c["total_vendas"],
            frequencia_dias=len(c["dias"]),
            ticket_medio=round(c["faturamento"] / c["total_vendas"], 2) if c["total_vendas"] else 0.0,
        )
        for c in sorted(ranking_c.values(), key=lambda x: x["total_caixas"], reverse=True)
    ]
    produtos_list = [
        ProdutoVendido(nome=k, total_caixas=v)
        for k, v in sorted(produtos_agg.items(), key=lambda x: x[1], reverse=True)
    ]
    caixas_dia_list = [
        CaixasDia(**caixas_dia[d]) if d in caixas_dia
        else CaixasDia(dia=d, total_caixas=0, faturamento_estimado=0.0)
        for d in _DIAS_SEMANA
    ]
    total_mix = sum(mix.values()) or 1
    mix_out = {
        k: MixPagamentoItem(count=cnt, percentual=round(cnt / total_mix * 100, 1))
        for k, cnt in sorted(mix.items(), key=lambda x: x[1], reverse=True)
    }

    def _ticket_list(agg: dict[str, dict]) -> list[TicketGrupo]:
        return [
            TicketGrupo(
                nome=g["nome"],
                total_caixas=g["total_caixas"],
                faturamento=round(g["faturamento"], 2),
                ticket_medio=round(g["faturamento"] / g["total_caixas"], 2) if g["total_caixas"] else 0.0,
            )
            for g in sorted(agg.values(), key=lambda x: x["faturamento"], reverse=True)
        ]

    # ── Comparativo dia a dia com o mês anterior ────────────────────────────────
    if mes == 1:
        ano_ant, mes_ant = ano - 1, 12
    else:
        ano_ant, mes_ant = ano, mes - 1
    dias_no_mes_atual = _cal.monthrange(ano, mes)[1]
    dias_no_mes_anterior = _cal.monthrange(ano_ant, mes_ant)[1]
    primeiro_dia_ant = date(ano_ant, mes_ant, 1)
    ultimo_dia_ant = date(ano_ant, mes_ant, dias_no_mes_anterior)

    fat_por_dia_atual: dict[int, float] = defaultdict(float)
    for r in hist_rows:
        fat_por_dia_atual[r.data.day] += float(r.total_item or 0)

    rows_ant = (
        db.query(VendaHistorico.data, VendaHistorico.total_item)
        .filter(VendaHistorico.data >= primeiro_dia_ant, VendaHistorico.data <= ultimo_dia_ant)
        .all()
    )
    fat_por_dia_anterior: dict[int, float] = defaultdict(float)
    for r in rows_ant:
        fat_por_dia_anterior[r.data.day] += float(r.total_item or 0)

    max_dias = max(dias_no_mes_atual, dias_no_mes_anterior)
    serie = [
        PontoComparativoDia(
            dia=d,
            atual=round(fat_por_dia_atual.get(d, 0.0), 2) if d <= hoje.day else None,
            anterior=round(fat_por_dia_anterior.get(d, 0.0), 2) if d <= dias_no_mes_anterior else None,
        )
        for d in range(1, max_dias + 1)
    ]

    comparativo = ComparativoMensal(
        mes_atual_label=f"{_MES_PT[mes]}/{str(ano)[2:]}",
        mes_anterior_label=f"{_MES_PT[mes_ant]}/{str(ano_ant)[2:]}",
        faturamento_atual_total=round(faturamento_total, 2),
        faturamento_anterior_total=round(sum(fat_por_dia_anterior.values()), 2),
        serie=serie,
    )

    return VendasResponse(
        vendas=vendas_out,
        resumo=Resumo(
            total_caixas=total_caixas,
            total_vendas=len(vendas_out),
            faturamento_estimado=round(faturamento_total, 2),
        ),
        ranking_vendedores=ranking_v_list,
        ranking_clientes=ranking_c_list,
        produtos_mais_vendidos=produtos_list,
        caixas_por_dia=caixas_dia_list,
        mix_pagamento=mix_out,
        vendas_em_aberto=vendas_em_aberto,
        ticket_por_categoria=_ticket_list(ticket_cat),
        ticket_por_fornecedor=_ticket_list(ticket_forn),
        dia_atual=dia_atual_str,
        comparativo_mensal=comparativo,
    )
