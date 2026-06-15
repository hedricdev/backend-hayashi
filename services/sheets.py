import time
import unicodedata
from datetime import datetime, timedelta

import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ---------------------------------------------------------------------------
# Cache em memória — evita chamar a Sheets API a cada request do dashboard
# ---------------------------------------------------------------------------
_cache_data: list[dict] | None = None
_cache_ts: float = 0.0
CACHE_TTL = 180  # segundos


def _cache_get() -> list[dict] | None:
    if _cache_data is not None and (time.time() - _cache_ts) < CACHE_TTL:
        return _cache_data
    return None


def _cache_set(data: list[dict]) -> None:
    global _cache_data, _cache_ts
    _cache_data = data
    _cache_ts = time.time()


def invalidate_cache() -> None:
    global _cache_data, _cache_ts
    _cache_data = None
    _cache_ts = 0.0
LABELS_IGNORAR = {"TOTAL", "COMPRAS", "DIFERENCA", "DIFERENÇA"}
DIAS_SEMANA = ["DOMINGO", "SEGUNDA", "TERÇA", "QUARTA", "QUINTA", "SEXTA", "SABADO"]


def normaliza(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split()).upper()


def col_to_letter(index: int) -> str:
    letter = ""
    n = index + 1
    while n > 0:
        rem = (n - 1) % 26
        letter = chr(65 + rem) + letter
        n = (n - 1) // 26
    return letter


def get_sheets_client():
    creds = service_account.Credentials.from_service_account_info(
        {
            "type": "service_account",
            "client_email": settings.GOOGLE_SERVICE_ACCOUNT_EMAIL,
            "private_key": settings.GOOGLE_PRIVATE_KEY.replace("\\n", "\n"),
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=creds)


def _get_cabecalho(service, aba: str) -> list[str]:
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=settings.SPREADSHEET_ID, range=f"'{aba}'!A4:AZ4")
        .execute()
    )
    values = result.get("values", [[]])
    return values[0] if values else []


def get_vendas_nao_importadas(aba: str) -> list[dict]:
    service = get_sheets_client()

    cabecalho = _get_cabecalho(service, aba)
    if not cabecalho:
        return []

    col_vendedor = next(
        (i for i, h in enumerate(cabecalho) if normaliza(h) == "VENDEDOR"), None
    )
    col_pagamento = next(
        (i for i, h in enumerate(cabecalho) if normaliza(h) in {"DIN/PIX", "DIN/CHQ"}),
        None,
    )
    col_preco = next(
        (i for i, h in enumerate(cabecalho) if normaliza(h) in {"PRECOS", "PRECO"}),
        None,
    )

    if col_vendedor is None:
        return []

    # Coluna imediatamente após VENDEDOR = marcador de importação (IFRUTI_ID)
    col_ifruti = col_vendedor + 1

    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=settings.SPREADSHEET_ID, range=f"'{aba}'!A5:AZ")
        .execute()
    )
    rows = result.get("values", [])

    vendas = []
    for i, row in enumerate(rows, start=5):
        if not row or not row[0].strip():
            continue
        cliente = row[0].strip()
        if normaliza(cliente) in LABELS_IGNORAR:
            continue

        vendedor = row[col_vendedor].strip() if col_vendedor < len(row) else ""
        if not vendedor:
            continue

        ifruti_id = row[col_ifruti].strip() if col_ifruti < len(row) else ""
        if ifruti_id:
            continue  # já importado

        pagamento = (
            row[col_pagamento].strip()
            if col_pagamento is not None and col_pagamento < len(row)
            else ""
        )
        preco = (
            row[col_preco].strip()
            if col_preco is not None and col_preco < len(row)
            else ""
        )

        # Produtos: colunas 1 até col_pagamento (exclusive)
        limite_produtos = col_pagamento if col_pagamento is not None else col_vendedor
        itens = []
        for j in range(1, limite_produtos):
            if j >= len(cabecalho):
                break
            nome_produto = cabecalho[j].strip()
            if not nome_produto:
                continue
            qtd_str = row[j].strip() if j < len(row) else ""
            if not qtd_str or qtd_str == "0":
                continue
            try:
                if int(qtd_str) > 0:
                    itens.append({"produto": nome_produto, "quantidade": qtd_str})
            except ValueError:
                pass

        if not itens:
            continue

        vendas.append(
            {
                "linha_numero": i,
                "cliente": cliente,
                "vendedor": vendedor,
                "pagamento": pagamento,
                "preco": preco,
                "itens": itens,
            }
        )

    return vendas


def _fetch_todas_as_vendas() -> list[dict]:
    """Busca todos os dados da semana na API do Sheets (sem filtro, sem cache)."""
    service = get_sheets_client()
    todas: list[dict] = []

    for aba in DIAS_SEMANA[1:]:  # SEGUNDA → SABADO
        try:
            cabecalho = _get_cabecalho(service, aba)
            if not cabecalho:
                continue

            col_vendedor = next(
                (i for i, h in enumerate(cabecalho) if normaliza(h) == "VENDEDOR"), None
            )
            col_pagamento = next(
                (
                    i
                    for i, h in enumerate(cabecalho)
                    if normaliza(h) in {"DIN/PIX", "DIN/CHQ"}
                ),
                None,
            )
            col_preco = next(
                (i for i, h in enumerate(cabecalho) if normaliza(h) in {"PRECOS", "PRECO"}),
                None,
            )

            if col_vendedor is None:
                continue

            result = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=settings.SPREADSHEET_ID, range=f"'{aba}'!A5:AZ")
                .execute()
            )
            rows = result.get("values", [])

            for row in rows:
                if not row or not row[0].strip():
                    continue
                cliente = row[0].strip()
                if normaliza(cliente) in LABELS_IGNORAR:
                    continue

                vendedor = row[col_vendedor].strip() if col_vendedor < len(row) else ""
                if not vendedor:
                    continue

                pagamento = (
                    row[col_pagamento].strip()
                    if col_pagamento is not None and col_pagamento < len(row)
                    else ""
                )
                preco = (
                    row[col_preco].strip()
                    if col_preco is not None and col_preco < len(row)
                    else ""
                )

                limite_produtos = col_pagamento if col_pagamento is not None else col_vendedor
                produtos = []
                for j in range(1, limite_produtos):
                    if j >= len(cabecalho):
                        break
                    nome_produto = cabecalho[j].strip()
                    if not nome_produto:
                        continue
                    qtd_str = row[j].strip() if j < len(row) else ""
                    if not qtd_str or qtd_str == "0":
                        continue
                    try:
                        qtd = int(qtd_str)
                        if qtd > 0:
                            produtos.append({"nome": nome_produto, "quantidade": qtd})
                    except ValueError:
                        pass

                if produtos:
                    todas.append(
                        {
                            "cliente": cliente,
                            "vendedor": vendedor,
                            "pagamento": pagamento,
                            "preco": preco,
                            "produtos": produtos,
                            "dia": aba,
                        }
                    )

        except Exception as e:
            print(f"Erro ao ler aba {aba}: {e}")
            continue

    return todas


def get_vendas_semana(
    nome_vendedor: str | None = None, bust: bool = False
) -> list[dict]:
    """Retorna vendas da semana com cache em memória (TTL=3 min).

    bust=True ignora o cache e força uma nova leitura da planilha.
    """
    if not bust:
        cached = _cache_get()
        if cached is not None:
            if nome_vendedor:
                return [
                    v for v in cached
                    if normaliza(v["vendedor"]) == normaliza(nome_vendedor)
                ]
            return cached

    todas = _fetch_todas_as_vendas()
    _cache_set(todas)

    if nome_vendedor:
        return [
            v for v in todas
            if normaliza(v["vendedor"]) == normaliza(nome_vendedor)
        ]
    return todas


def marcar_como_importado(aba: str, linha_numero: int, ifruti_id: str) -> None:
    service = get_sheets_client()
    cabecalho = _get_cabecalho(service, aba)
    col_vendedor = next(
        (i for i, h in enumerate(cabecalho) if normaliza(h) == "VENDEDOR"), None
    )
    if col_vendedor is None:
        return

    col_letra = col_to_letter(col_vendedor + 1)
    range_ = f"'{aba}'!{col_letra}{linha_numero}"
    body = {"values": [[ifruti_id]]}
    service.spreadsheets().values().update(
        spreadsheetId=settings.SPREADSHEET_ID,
        range=range_,
        valueInputOption="RAW",
        body=body,
    ).execute()


def get_aba_atual() -> str:
    """Retorna a aba do dia corrente. Após 12h aponta para o dia seguinte.
    Usado para a lista diária (compras): após 12h já aponta para o próximo dia.
    """
    brasilia = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(brasilia)
    if agora.hour >= 12:
        agora += timedelta(days=1)
    idx = (agora.weekday() + 1) % 7  # 0=dom, 1=seg, ..., 6=sab
    return DIAS_SEMANA[idx]


def get_aba_venda_atual() -> str:
    """Retorna a aba do dia atual para importação de vendas.
    Sempre retorna o dia corrente, sem adiantar para o próximo.
    As vendas são do dia em que foram feitas, independente do horário.
    """
    brasilia = pytz.timezone("America/Sao_Paulo")
    agora = datetime.now(brasilia)
    idx = (agora.weekday() + 1) % 7
    return DIAS_SEMANA[idx]


def get_aba_semana_atual() -> list[str]:
    return DIAS_SEMANA


def get_lista_diaria(aba: str | None = None) -> list[dict]:
    """Lê as compras do dia a partir das linhas 2 (custo) e 3 (quantidade).

    Retorna lista de {produto, quantidade, valor, fornecedor}.
    Ignora produtos sem quantidade ou sem custo preenchido.
    """
    if aba is None:
        aba = get_aba_atual()

    service = get_sheets_client()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=settings.SPREADSHEET_ID, range=f"'{aba}'!A2:AZ4")
        .execute()
    )
    rows = result.get("values", [])
    if len(rows) < 3:
        return []

    row_custo = rows[0]       # linha 2 — custo real por caixa
    row_qtde = rows[1]        # linha 3 — quantidade comprada
    row_cabecalho = rows[2]   # linha 4 — nomes dos produtos

    col_pagamento = next(
        (i for i, h in enumerate(row_cabecalho) if normaliza(h) in {"DIN/PIX", "DIN/CHQ"}),
        None,
    )
    limite = col_pagamento if col_pagamento is not None else len(row_cabecalho)

    itens: list[dict] = []
    for j in range(1, limite):
        nome = row_cabecalho[j].strip() if j < len(row_cabecalho) else ""
        if not nome:
            continue
        qtd_str = row_qtde[j].strip() if j < len(row_qtde) else ""
        custo_str = row_custo[j].strip() if j < len(row_custo) else ""
        if not qtd_str or not custo_str:
            continue
        try:
            qtd = int(float(qtd_str))
        except ValueError:
            continue
        if qtd <= 0:
            continue
        itens.append({
            "produto": nome,
            "quantidade": qtd,
            "valor": custo_str.replace(",", "."),
            "fornecedor": None,
        })

    return itens
