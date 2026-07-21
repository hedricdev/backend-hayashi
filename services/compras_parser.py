from collections import defaultdict
from datetime import date, datetime

from bs4 import BeautifulSoup


def _brl(s: str) -> float:
    try:
        return float(s.replace(".", "").replace(",", ".").strip())
    except Exception:
        return 0.0


def _data(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except Exception:
        return None


def parse_compras_xls(raw: bytes) -> list[dict]:
    """
    O iFruti exporta a tela Mercadorias > Compras como um .xls que na
    verdade é HTML (mesmo formato de despesas_parser.parse_despesas_xls).
    Diferente de Despesas, essa tabela não tem <thead>/<tbody> — é só
    <table><tr>cabeçalho</tr><tr>dados</tr>...</table> — por isso itera
    todas as <tr> da própria <table> e descarta quem não tiver uma data
    válida na primeira célula (inclusive a linha de cabeçalho).

    Mesma lógica de "ocorrencia" de parse_despesas_xls pra não colapsar
    compras legítimas repetidas (mesmo produto/fornecedor/valor no mesmo
    dia) num upsert por chave natural.
    """
    text = raw.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(text, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError("Nenhuma tabela encontrada no arquivo")

    linhas = []
    contador: dict[tuple, int] = defaultdict(int)
    for row in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 8:
            continue
        d = _data(cells[0])
        if not d:
            continue

        produto = cells[1].strip()
        fornecedor = cells[2].strip()
        qtde = int(cells[3]) if cells[3].isdigit() else 0
        valor_unitario = _brl(cells[4])
        valor_total = _brl(cells[5])

        chave = (d, produto, fornecedor, qtde, valor_unitario, valor_total)
        ocorrencia = contador[chave]
        contador[chave] += 1

        linhas.append(
            {
                "data_compra": d,
                "produto": produto,
                "fornecedor": fornecedor,
                "qtde": qtde,
                "valor_unitario": valor_unitario,
                "valor_total": valor_total,
                "valor_aberto": _brl(cells[6]),
                "data_pagamento": _data(cells[7]) if len(cells) > 7 and cells[7] else None,
                "devolucao": int(cells[8]) if len(cells) > 8 and cells[8].isdigit() else 0,
                "ocorrencia": ocorrencia,
            }
        )
    return linhas
