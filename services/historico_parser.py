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


def parse_ifruti_xls(raw: bytes) -> list[dict]:
    """
    O iFruti exporta um arquivo .xls que na verdade é HTML.
    Parseia a tabela e retorna uma lista de dicts prontos para inserção.
    """
    text = raw.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(text, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError("Nenhuma tabela encontrada no arquivo")

    linhas = []
    for row in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in row.find_all(["th", "td"])]
        if len(cells) < 9:
            continue
        d = _data(cells[0])
        if not d:
            continue
        linhas.append(
            {
                "data": d,
                "cliente": cells[1].strip().upper(),
                "produto": cells[2].strip(),
                "qtde": int(cells[3]) if cells[3].isdigit() else 0,
                "dvl": int(cells[4]) if cells[4].isdigit() else 0,
                "preco_item": _brl(cells[5]),
                "total_item": _brl(cells[6]),
                "valor_aberto": _brl(cells[7]),
                "data_recebimento": _data(cells[8]) if cells[8] else None,
            }
        )
    return linhas
