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


def parse_despesas_xls(raw: bytes) -> list[dict]:
    """
    O iFruti exporta a tela Financeiro > Despesas como um .xls que na verdade
    é HTML (mesmo formato de historico_parser.parse_ifruti_xls). Parseia a
    tabela #dataTables-despesas e retorna uma lista de dicts prontos para
    inserção.

    Algumas despesas legítimas se repetem com todos os campos idênticos
    (ex.: dois fretes de mesmo valor no mesmo dia pro mesmo credor) — pra não
    colapsá-las num upsert por chave natural, atribui um índice "ocorrencia"
    (0, 1, 2...) por grupo de chave idêntica, na ordem em que aparecem na
    tabela.
    """
    text = raw.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(text, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError("Nenhuma tabela encontrada no arquivo")

    linhas = []
    contador: dict[tuple, int] = defaultdict(int)
    for row in table.find("tbody").find_all("tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 7:
            continue
        d = _data(cells[0])
        if not d:
            continue

        chave = (d, cells[1].strip(), cells[2].strip(), cells[3].strip(), cells[4].strip(), cells[5].strip())
        ocorrencia = contador[chave]
        contador[chave] += 1

        linhas.append(
            {
                "data_despesa": d,
                "descricao": cells[1].strip(),
                "loja": cells[2].strip(),
                "credor": cells[3].strip(),
                "data_vencimento": _data(cells[4]),
                "valor": _brl(cells[5]),
                "valor_aberto": _brl(cells[6]),
                "data_pagamento": _data(cells[7]) if len(cells) > 7 and cells[7] else None,
                "ocorrencia": ocorrencia,
            }
        )
    return linhas
