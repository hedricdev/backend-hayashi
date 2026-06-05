from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from auth import get_current_user
from models.usuario import Role, Usuario
from services.sheets import get_vendas_semana

router = APIRouter()


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


class Resumo(BaseModel):
    total_caixas: int
    total_vendas: int
    faturamento_estimado: float


class VendasResponse(BaseModel):
    vendas: list[Venda]
    resumo: Resumo
    ranking_vendedores: list[RankingVendedor]


@router.get("", response_model=VendasResponse)
def get_vendas(
    current_user: Annotated[Usuario, Depends(get_current_user)],
    bust: bool = Query(default=False, description="Ignora o cache e busca dados frescos da planilha"),
):
    nome_vendedor = (
        current_user.nome_planilha
        if current_user.role == Role.vendedor
        else None
    )

    raw = get_vendas_semana(nome_vendedor=nome_vendedor, bust=bust)

    total_caixas = 0
    faturamento_estimado = 0.0
    ranking: dict[str, dict] = {}
    vendas_out: list[Venda] = []

    for v in raw:
        caixas = sum(p["quantidade"] for p in v["produtos"])
        total_caixas += caixas

        for parte in v["preco"].replace(",", ".").split("/"):
            try:
                faturamento_estimado += float(parte.strip())
            except ValueError:
                pass

        nome = v["vendedor"]
        if nome not in ranking:
            ranking[nome] = {"nome": nome, "total_caixas": 0, "total_vendas": 0}
        ranking[nome]["total_caixas"] += caixas
        ranking[nome]["total_vendas"] += 1

        vendas_out.append(
            Venda(
                cliente=v["cliente"],
                vendedor=nome,
                pagamento=v["pagamento"],
                preco=v["preco"],
                produtos=[
                    Produto(nome=p["nome"], quantidade=p["quantidade"])
                    for p in v["produtos"]
                ],
                dia=v["dia"],
            )
        )

    ranking_list = sorted(
        ranking.values(), key=lambda x: x["total_caixas"], reverse=True
    )

    return VendasResponse(
        vendas=vendas_out,
        resumo=Resumo(
            total_caixas=total_caixas,
            total_vendas=len(vendas_out),
            faturamento_estimado=round(faturamento_estimado, 2),
        ),
        ranking_vendedores=[RankingVendedor(**r) for r in ranking_list],
    )
