# Contexto da Planilha — Sistema Hayashi

## Identificação
- **ID da planilha de desenvolvimento:** `1YeSqoZjU4npt8f0-jkzuieHK31J1dD7S4jt4ABD8SFI`
- **Acesso:** Google Sheets API via Service Account

---

## Estrutura Geral

A planilha tem **7 abas**, uma por dia da semana:
`SEGUNDA`, `TERÇA`, `QUARTA`, `QUINTA`, `SEXTA`, `SABADO`, `DOMINGO`

**Cada aba tem a mesma estrutura de linhas:**

| Linha | Conteúdo |
|-------|----------|
| 1 | SOBRAS (quantidade que sobrou do dia anterior por produto) |
| 2 | CUSTO (custo real por caixa = custo pago na roça + R$6,00 de frete) |
| 3 | QUANTIDADE (total de caixas compradas por produto naquele dia) |
| 4 | **Cabeçalho** — `Cliente/Produto` na coluna A, depois os nomes dos produtos nas colunas seguintes |
| 5 em diante | Um cliente por linha |

---

## Estrutura de Colunas

### CRÍTICO: As colunas NÃO são fixas entre abas nem entre semanas

O número de colunas de produto varia a cada dia dependendo do que o Michael comprou na roça. Por isso:

- **Nunca assuma que um produto está numa coluna fixa (ex: B, C, D)**
- **Sempre leia o cabeçalho da linha 4 dinamicamente** para descobrir a coluna de cada produto
- As colunas de controle (Din/Pix, PREÇOS, TOTAL, SAÍDA, VENDEDOR) ficam sempre **depois** das colunas de produto, mas em posições variáveis

### Colunas de controle (sempre após os produtos)

| Nome no cabeçalho | Variações possíveis | Conteúdo |
|---|---|---|
| `Din/Pix` ou `Din/Chq` | Varia por aba | Forma de pagamento (PIX, DIN, CHQ) |
| `PREÇOS` ou `PREÇO` | Varia por aba | Preço de venda negociado pelo vendedor |
| `TOTAL` | — | Calculado |
| `SAÍDA` ou `Saída` | — | Controle operacional |
| `VENDEDOR` | — | Nome do vendedor que realizou a venda (gravado pela automação) |

### Como encontrar a coluna correta no código

```javascript
function normaliza(str) {
  return str.normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toUpperCase();
}

// Busca dinâmica — sempre use assim
const cabecalho = // array com valores da linha 4 (A4:Z4 ou além)

const colProdutoIndex = cabecalho.findIndex(h => normaliza(h) === normaliza('1A COOP'));
const colPagamentoIndex = cabecalho.findIndex(h => 
  normaliza(h) === normaliza('Din/Pix') || normaliza(h) === normaliza('Din/Chq')
);
const colPrecoIndex = cabecalho.findIndex(h => 
  normaliza(h) === normaliza('PREÇOS') || normaliza(h) === normaliza('PREÇO')
);
const colVendedorIndex = cabecalho.findIndex(h => normaliza(h) === normaliza('VENDEDOR'));
```

### Conversão de índice para letra de coluna

```javascript
function colToLetter(index) {
  let letter = '';
  let n = index + 1; // índice 0 = coluna A
  while (n > 0) {
    const rem = (n - 1) % 26;
    letter = String.fromCharCode(65 + rem) + letter;
    n = Math.floor((n - 1) / 26);
  }
  return letter;
}
// Exemplos: índice 0 = A, índice 1 = B, índice 25 = Z, índice 26 = AA
```

---

## Regras de Negócio

### Ciclo semanal
- A semana vai de **Segunda a Domingo**
- No domingo, o Thiago faz backup manual e zera a planilha
- A estrutura base (clientes, cabeçalho de produtos) é mantida entre semanas
- As vendas (quantidades, preços, pagamentos, vendedor) são zeradas

### Cálculo de aba pelo horário
- Mensagens até **11h59** → aba do dia atual
- Mensagens a partir de **12h00** → aba do dia seguinte
- Fuso horário: sempre `America/Sao_Paulo`

```javascript
const dias = ['DOMINGO', 'SEGUNDA', 'TERÇA', 'QUARTA', 'QUINTA', 'SEXTA', 'SABADO'];
const agora = new Date();
const brasilia = new Date(agora.toLocaleString('en-US', { timeZone: 'America/Sao_Paulo' }));
if (brasilia.getHours() >= 12) brasilia.setDate(brasilia.getDate() + 1);
const aba = dias[brasilia.getDay()];
```

### Clientes
- Cada linha a partir da linha 5 é um cliente
- O nome do cliente fica na **coluna A**
- Clientes novos são inseridos dinamicamente antes da primeira linha vazia após os clientes existentes
- Linhas a ignorar ao buscar clientes: `TOTAL`, `COMPRAS`, `DIFERENÇA`, `DIFERENCA`, linhas vazias

### Vendas
- Cada célula no cruzamento de linha (cliente) e coluna (produto) contém a **quantidade vendida**
- Uma venda registra: quantidade, pagamento (Din/Pix), preço de venda e vendedor
- O preço é acumulado com `/` se o mesmo cliente comprou produtos diferentes no mesmo dia
  - Ex: cliente comprou 1A COOP e 2A MINAS → preço fica `110/90`
- O vendedor é identificado pelo número de WhatsApp (mapeamento fixo no n8n)

### Custos
- **Custo na roça** = valor que o Michael paga ao fornecedor
- **Custo real** = custo na roça + R$6,00 (frete fixo por caixa)
- O que entra na linha 2 da planilha é o **custo real**
- Ex: Michael paga R$34,00 → planilha registra R$40,00

### Coluna VENDEDOR
- Sempre a última coluna, logo após `SAÍDA`
- Adicionada manualmente no cabeçalho (linha 4) de cada aba
- Gravada automaticamente pela automação n8n a cada venda

---

## Leitura via API

### Endpoints utilizados

```
# Cabeçalho da aba (linha 4)
GET .../values/{aba}!A4:Z4

# Lista de clientes (coluna A inteira)  
GET .../values/{aba}!A:A

# Metadados das abas (sheetId de cada aba)
GET ...?fields=sheets.properties

# Leitura de célula específica
GET .../values/{aba}!{coluna}{linha}

# Gravação em lote
POST .../values:batchUpdate
Body: { valueInputOption: "RAW", data: [{ range, values }] }

# Inserção de linha
POST .../batchUpdate  
Body: { requests: [{ insertDimension: { range: { sheetId, dimension: "ROWS", startIndex, endIndex } } }] }
```

### SheetIds das abas (planilha de desenvolvimento)

| Aba | sheetId |
|-----|---------|
| SEGUNDA | 1200961913 |
| TERÇA | 31445411 |
| QUARTA | 1177545865 |
| QUINTA | 1222316783 |
| SEXTA | 1785459684 |
| SABADO | 715708557 |
| DOMINGO | 309564564 |

### CRÍTICO ao ler dados da planilha no Next.js

- **Nunca assuma índices de coluna fixos** — leia sempre o cabeçalho primeiro
- A linha 4 pode ter colunas extras dependendo do dia — use `A4:Z4` ou `A4:AZ4` para garantir
- Ao agregar dados da semana, leia aba por aba e some os valores
- Só considere como venda válida: linhas onde a coluna VENDEDOR está preenchida
- Ignorar sempre: linhas 1-4, linhas com TOTAL, COMPRAS, DIFERENÇA, linhas vazias

---

## Exemplo de leitura agregada (para o dashboard)

```javascript
// Para cada aba da semana:
// 1. Busca cabeçalho (linha 4) → descobre índice de cada coluna
// 2. Busca todas as linhas a partir da linha 5
// 3. Filtra linhas onde coluna VENDEDOR está preenchida
// 4. Para cada linha válida, extrai os dados de venda

// Estrutura de uma venda extraída:
{
  cliente: string,        // coluna A
  vendedor: string,       // coluna VENDEDOR
  pagamento: string,      // coluna Din/Pix ou Din/Chq
  precos: string,         // coluna PREÇOS (pode ser "110/90" para múltiplos produtos)
  produtos: [             // para cada coluna de produto com valor > 0
    { nome: string, quantidade: number }
  ],
  dia: string             // nome da aba (SEGUNDA, TERÇA, etc.)
}
```

---

## Leitura via Python (FastAPI / Backend)

### Dependências
```
pip install google-auth google-auth-httplib2 google-api-python-client
```

### Setup do cliente
```python
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = '1YeSqoZjU4npt8f0-jkzuieHK31J1dD7S4jt4ABD8SFI'

credentials = service_account.Credentials.from_service_account_info(
    json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),
    scopes=SCOPES
)
service = build('sheets', 'v4', credentials=credentials)
sheet = service.spreadsheets()
```

### Funções utilitárias

```python
import unicodedata

def normaliza(s: str) -> str:
    """Remove acentos, espaços extras e converte para maiúsculas."""
    if not s:
        return ''
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return ' '.join(s.split()).upper()

def col_to_letter(index: int) -> str:
    """Converte índice 0-based para letra de coluna (0=A, 1=B, 25=Z, 26=AA)."""
    letter = ''
    n = index + 1
    while n > 0:
        rem = (n - 1) % 26
        letter = chr(65 + rem) + letter
        n = (n - 1) // 26
    return letter
```

### Leitura do cabeçalho (linha 4)
```python
def get_cabecalho(aba: str) -> list[str]:
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{aba}'!A4:AZ4"
    ).execute()
    values = result.get('values', [[]])
    return values[0] if values else []

# Uso:
cabecalho = get_cabecalho('TERCA')
col_produto = next((i for i, h in enumerate(cabecalho) if normaliza(h) == normaliza('1A COOP')), None)
col_pagamento = next((i for i, h in enumerate(cabecalho) if normaliza(h) in ['DIN/PIX', 'DIN/CHQ']), None)
col_preco = next((i for i, h in enumerate(cabecalho) if normaliza(h) in ['PRECOS', 'PRECO']), None)
col_vendedor = next((i for i, h in enumerate(cabecalho) if normaliza(h) == 'VENDEDOR'), None)
```

### Leitura de todas as linhas da aba
```python
def get_linhas(aba: str) -> list[list]:
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{aba}'!A:AZ"
    ).execute()
    return result.get('values', [])

# Linhas a ignorar
LABELS_IGNORAR = {'TOTAL', 'COMPRAS', 'DIFERENCA', 'DIFERENÇA'}

def is_linha_valida(row: list, col_vendedor: int) -> bool:
    """Retorna True se a linha é uma venda válida registrada pela automação."""
    if not row or not row[0].strip():
        return False
    if normaliza(row[0]) in LABELS_IGNORAR:
        return False
    if col_vendedor is None or col_vendedor >= len(row):
        return False
    if not row[col_vendedor].strip():
        return False
    return True
```

### Leitura agregada da semana (para o dashboard)
```python
from datetime import datetime
import pytz

DIAS = ['DOMINGO', 'SEGUNDA', 'TERCA', 'QUARTA', 'QUINTA', 'SEXTA', 'SABADO']

def get_aba_atual() -> str:
    brasilia = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(brasilia)
    if agora.hour >= 12:
        agora = agora.replace(day=agora.day + 1)
    return DIAS[agora.weekday() + 1 if agora.weekday() < 6 else 0]

def get_vendas_semana() -> list[dict]:
    vendas = []
    for aba in DIAS[1:]:  # SEGUNDA a SABADO
        try:
            cabecalho = get_cabecalho(aba)
            if not cabecalho:
                continue

            col_vendedor = next((i for i, h in enumerate(cabecalho) if normaliza(h) == 'VENDEDOR'), None)
            col_pagamento = next((i for i, h in enumerate(cabecalho) if normaliza(h) in ['DIN/PIX', 'DIN/CHQ']), None)
            col_preco = next((i for i, h in enumerate(cabecalho) if normaliza(h) in ['PRECOS', 'PRECO']), None)

            linhas = get_linhas(aba)

            for i, row in enumerate(linhas[4:], start=5):  # pula linhas 1-4
                if not is_linha_valida(row, col_vendedor):
                    continue

                cliente = row[0].strip()
                vendedor = row[col_vendedor] if col_vendedor and col_vendedor < len(row) else ''
                pagamento = row[col_pagamento] if col_pagamento and col_pagamento < len(row) else ''
                preco = row[col_preco] if col_preco and col_preco < len(row) else ''

                # Produtos vendidos (colunas 1 até col_pagamento-1)
                produtos = []
                for j in range(1, col_pagamento or len(row)):
                    if j < len(cabecalho) and j < len(row):
                        nome_produto = cabecalho[j].strip()
                        qtd = row[j]
                        if nome_produto and qtd and str(qtd).strip().isdigit():
                            produtos.append({
                                'nome': nome_produto,
                                'quantidade': int(qtd)
                            })

                if produtos:
                    vendas.append({
                        'cliente': cliente,
                        'vendedor': vendedor,
                        'pagamento': pagamento,
                        'preco': preco,
                        'produtos': produtos,
                        'dia': aba
                    })
        except Exception as e:
            print(f"Erro ao ler aba {aba}: {e}")
            continue

    return vendas
```

### Gravação em lote
```python
def gravar_celulas(dados: list[dict]) -> dict:
    """
    dados = [
        {'range': 'TERCA!B5', 'values': [[30]]},
        {'range': 'TERCA!Q5', 'values': [['PIX']]},
    ]
    """
    body = {
        'valueInputOption': 'RAW',
        'data': dados
    }
    return sheet.values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body=body
    ).execute()
```

### Variáveis de ambiente necessárias
```env
SPREADSHEET_ID=1YeSqoZjU4npt8f0-jkzuieHK31J1dD7S4jt4ABD8SFI
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"..."}
```

> **Nota:** Prefira passar o JSON completo como string na variável de ambiente em vez de um arquivo, facilita o deploy no EasyPanel.
