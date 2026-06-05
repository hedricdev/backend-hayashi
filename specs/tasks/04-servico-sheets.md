# Task 04 — Serviço Google Sheets

## Objetivo
Implementar o serviço que lê a planilha Google Sheets e retorna as linhas de venda que ainda não foram importadas no iFruti.

## Arquivos a Editar

- `services/sheets.py`

## Contexto da Planilha

A planilha tem 7 abas: SEGUNDA, TERÇA, QUARTA, QUINTA, SEXTA, SABADO, DOMINGO.

Estrutura de cada aba:
- **Linha 4**: cabeçalho dos produtos (coluna A = "Cliente/Produto", depois nomes de produtos)
- **Linha 5 em diante**: clientes com quantidades por produto
- **Coluna Q**: forma de pagamento (Din/Pix)
- **Coluna R**: PREÇOS — preço de venda
- **Coluna U**: VENDEDOR — preenchido pela automação n8n
- **Coluna V** (controle): ID do iFruti após importação — se preenchida, a linha já foi importada

Linhas a ignorar: SOBRAS, CUSTO, QUANTIDADE, TOTAL, COMPRAS e vazias.

## Implementação

### `services/sheets.py`

#### Autenticação com Service Account
```python
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

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
```

#### Função principal: `get_vendas_nao_importadas(aba: str) -> list[dict]`
Parâmetros: nome da aba (ex: "SEGUNDA")

Lógica:
1. Buscar range `{aba}!A4:V` da planilha (da linha 4 até o fim, colunas A–V)
2. Linha 4 (índice 0) = cabeçalho de produtos
3. Linhas a partir do índice 1 = clientes
4. Filtrar linhas onde:
   - Coluna A (cliente) não está vazia
   - Coluna A não é uma das linhas especiais: `["SOBRAS", "CUSTO", "QUANTIDADE", "TOTAL", "COMPRAS"]`
   - Coluna U (índice 20) está preenchida (vendedor)
   - Coluna V (índice 21) está **vazia** (ainda não importado no iFruti)
5. Para cada linha válida, retornar:
```python
{
    "linha_numero": int,  # número real da linha na planilha (para gravar ID depois)
    "cliente": str,
    "vendedor": str,
    "pagamento": str,  # coluna Q (índice 16)
    "preco": str,      # coluna R (índice 17)
    "itens": [         # lista de produtos com quantidade > 0
        {"produto": str, "quantidade": str}
    ]
}
```

#### Função: `marcar_como_importado(aba: str, linha_numero: int, ifruti_id: str)`
Grava o `ifruti_id` na coluna V da linha informada.

```python
range_ = f"{aba}!V{linha_numero}"
body = {"values": [[ifruti_id]]}
service.spreadsheets().values().update(
    spreadsheetId=settings.SPREADSHEET_ID,
    range=range_,
    valueInputOption="RAW",
    body=body,
).execute()
```

#### Função auxiliar: `get_aba_semana_atual() -> list[str]`
Retorna a lista de abas da semana atual para iterar. Por hora, retornar todas as 7 abas:
```python
return ["SEGUNDA", "TERÇA", "QUARTA", "QUINTA", "SEXTA", "SABADO", "DOMINGO"]
```

## Critérios de Aceitação
- `get_vendas_nao_importadas("SEGUNDA")` retorna lista de dicts com os campos corretos
- Linhas com coluna V preenchida são ignoradas (idempotência)
- Linhas especiais (CUSTO, TOTAL, etc.) são ignoradas
- `marcar_como_importado` grava corretamente na coluna V sem sobrescrever outras colunas
