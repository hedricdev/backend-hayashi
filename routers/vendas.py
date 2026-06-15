from typing import Annotated

import pytz
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from auth import get_current_user
from models.usuario import Role, Usuario
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


class MixPagamentoItem(BaseModel):
    count: int
    percentual: float


class Resumo(BaseModel):
    total_caixas: int
    total_vendas: int
    faturamento_estimado: float


class VendasResponse(BaseModel):
    vendas: list[Venda]
    resumo: Resumo
    ranking_vendedores: list[RankingVendedor]
    ranking_clientes: list[RankingCliente]
    produtos_mais_vendidos: list[ProdutoVendido]
    caixas_por_dia: list[CaixasDia]
    mix_pagamento: dict[str, MixPagamentoItem]
    vendas_em_aberto: list[Venda]
    dia_atual: str


def _parse_faturamento(preco: str) -> float:
    total = 0.0
    for parte in preco.replace(",", ".").split("/"):
        try:
            total += float(parte.strip())
        except ValueError:
            pass
    return total


@router.get("", response_model=VendasResponse)
def get_vendas(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    bust: bool = Query(default=False, description="Ignora o cache e busca dados frescos"),
):
    nome_vendedor = (
        current_user.nome_planilha
        if current_user.role == Role.vendedor
        else None
    )

    raw = get_vendas_semana(nome_vendedor=nome_vendedor, bust=bust)
    dia_atual = get_aba_atual()

    total_caixas = 0
    faturamento_total = 0.0
    ranking_v: dict[str, dict] = {}
    ranking_c: dict[str, dict] = {}
    produtos_agg: dict[str, int] = {}
    caixas_dia: dict[str, dict] = {}
    mix: dict[str, int] = {}
    vendas_out: list[Venda] = []
    vendas_em_aberto: list[Venda] = []

    for v in raw:
        caixas = sum(p["quantidade"] for p in v["produtos"])
        fat = _parse_faturamento(v["preco"])
        total_caixas += caixas
        faturamento_total += fat

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
        dia_atual=dia_atual,
    )
