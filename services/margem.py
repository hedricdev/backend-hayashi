from collections import defaultdict
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.compra_historico import CompraHistorico


def custo_medio_por_produto_mes(db: Session) -> dict[str, dict[date, float]]:
    """{produto: {primeiro_dia_do_mes: custo_medio_unitario}}, a partir de
    CompraHistorico agrupado por (produto, mes). Custo medio ponderado
    (soma valor_total / soma qtde) — nao ha rastreio de lote/FIFO no
    sistema, essa e a melhor aproximacao disponivel.
    """
    mes_trunc = func.date_trunc("month", CompraHistorico.data_compra)
    rows = (
        db.query(
            CompraHistorico.produto,
            mes_trunc.label("mes"),
            func.sum(CompraHistorico.valor_total).label("valor_total"),
            func.sum(CompraHistorico.qtde).label("qtde"),
        )
        .group_by(CompraHistorico.produto, mes_trunc)
        .all()
    )

    out: dict[str, dict[date, float]] = defaultdict(dict)
    for r in rows:
        mes = r.mes.date() if hasattr(r.mes, "date") else r.mes
        qtde = float(r.qtde or 0)
        if qtde <= 0:
            continue
        out[r.produto][mes] = float(r.valor_total or 0) / qtde
    return out


class CustoAplicador:
    """Resolve o custo medio unitario de um produto num mes, caindo pro mes
    anterior mais proximo com compra registrada quando o mes exato nao tem
    (~0,3% dos casos, verificado contra o historico real). Retorna None so
    quando o produto nunca teve nenhuma compra no historico inteiro.
    """

    def __init__(self, custos: dict[str, dict[date, float]]):
        self._custos = custos
        self._meses_ordenados: dict[str, list[date]] = {
            produto: sorted(meses.keys()) for produto, meses in custos.items()
        }

    def custo(self, produto: str, mes: date) -> float | None:
        por_mes = self._custos.get(produto)
        if not por_mes:
            return None
        if mes in por_mes:
            return por_mes[mes]
        # fallback: mes anterior mais proximo com compra registrada
        anteriores = [m for m in self._meses_ordenados[produto] if m < mes]
        if anteriores:
            return por_mes[anteriores[-1]]
        # sem mes anterior — usa o primeiro mes disponivel (posterior) como
        # ultimo recurso, melhor que nenhum custo
        posteriores = self._meses_ordenados[produto]
        return por_mes[posteriores[0]] if posteriores else None
