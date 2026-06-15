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
  let n = index + 1;
  while (n > 0) {
    const rem = (n - 1) % 26;
    letter = String.fromCharCode(65 + rem) + letter;
    n = Math.floor((n - 1) / 26);
  }
  return letter;
}
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
- Linhas a ignorar: `TOTAL`, `COMPRAS`, `DIFERENÇA`, `DIFERENCA`, linhas vazias

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

### Coluna VENDEDOR
- Sempre a última coluna, logo após `SAÍDA`
- Gravada automaticamente pela automação n8n a cada venda

---

## Relatórios e Métricas

### Como calcular faturamento

O campo `PREÇOS` armazena o preço como string, podendo ser múltiplos valores separados por `/` quando o cliente comprou mais de um produto.

**CRÍTICO:** O preço na coluna PREÇOS corresponde ao preço de cada produto na ordem em que foram vendidos. Não é possível associar preço a produto específico com 100% de certeza — use o faturamento estimado como aproximação.

```python
def parse_precos(preco_str: str) -> list[float]:
    """Converte '110/90/50' em [110.0, 90.0, 50.0]"""
    if not preco_str:
        return []
    try:
        return [float(p.strip()) for p in preco_str.split('/') if p.strip()]
    except:
        return []

def calcular_faturamento(venda: dict) -> float:
    """
    Calcula faturamento estimado de uma venda.
    Multiplica cada preço pela quantidade do produto correspondente (por ordem).
    Se número de preços != número de produtos, usa média dos preços × total de caixas.
    """
    precos = parse_precos(venda.get('preco', ''))
    produtos = venda.get('produtos', [])
    
    if not precos or not produtos:
        return 0.0
    
    if len(precos) == len(produtos):
        return sum(p['quantidade'] * precos[i] for i, p in enumerate(produtos))
    else:
        media = sum(precos) / len(precos)
        total_caixas = sum(p['quantidade'] for p in produtos)
        return media * total_caixas
```

### Relatórios disponíveis

#### 1. Ranking de vendedores
```python
def ranking_vendedores(vendas: list[dict]) -> list[dict]:
    from collections import defaultdict
    ranking = defaultdict(lambda: {'caixas': 0, 'faturamento': 0.0, 'vendas': 0})
    
    for venda in vendas:
        v = venda['vendedor']
        ranking[v]['caixas'] += sum(p['quantidade'] for p in venda['produtos'])
        ranking[v]['faturamento'] += calcular_faturamento(venda)
        ranking[v]['vendas'] += 1
    
    return sorted(
        [{'vendedor': k, **v} for k, v in ranking.items()],
        key=lambda x: x['caixas'],
        reverse=True
    )
```

#### 2. Ranking de clientes
```python
def ranking_clientes(vendas: list[dict]) -> list[dict]:
    from collections import defaultdict
    ranking = defaultdict(lambda: {'caixas': 0, 'faturamento': 0.0, 'dias_comprou': set()})
    
    for venda in vendas:
        c = venda['cliente']
        ranking[c]['caixas'] += sum(p['quantidade'] for p in venda['produtos'])
        ranking[c]['faturamento'] += calcular_faturamento(venda)
        ranking[c]['dias_comprou'].add(venda['dia'])
    
    return sorted(
        [{'cliente': k, 'caixas': v['caixas'], 'faturamento': v['faturamento'],
          'frequencia': len(v['dias_comprou'])} for k, v in ranking.items()],
        key=lambda x: x['caixas'],
        reverse=True
    )
```

#### 3. Produtos mais vendidos
```python
def produtos_mais_vendidos(vendas: list[dict]) -> list[dict]:
    from collections import defaultdict
    produtos = defaultdict(int)
    
    for venda in vendas:
        for p in venda['produtos']:
            produtos[p['nome']] += p['quantidade']
    
    return sorted(
        [{'produto': k, 'quantidade': v} for k, v in produtos.items()],
        key=lambda x: x['quantidade'],
        reverse=True
    )
```

#### 4. Caixas por dia da semana
```python
def caixas_por_dia(vendas: list[dict]) -> list[dict]:
    from collections import defaultdict
    por_dia = defaultdict(int)
    
    for venda in vendas:
        por_dia[venda['dia']] += sum(p['quantidade'] for p in venda['produtos'])
    
    ordem = ['SEGUNDA', 'TERÇA', 'QUARTA', 'QUINTA', 'SEXTA', 'SABADO', 'DOMINGO']
    return [{'dia': d, 'caixas': por_dia.get(d, 0)} for d in ordem]
```

#### 5. Vendas em aberto (sem pagamento informado)
```python
def vendas_em_aberto(vendas: list[dict]) -> list[dict]:
    return [
        v for v in vendas
        if not v.get('pagamento') or v['pagamento'].strip() == ''
    ]
```

#### 6. Mix de pagamento
```python
def mix_pagamento(vendas: list[dict]) -> dict:
    from collections import Counter
    pagamentos = [v.get('pagamento', '').upper().strip() or 'EM ABERTO' for v in vendas]
    total = len(pagamentos)
    counter = Counter(pagamentos)
    return {k: {'count': v, 'percentual': round(v/total*100, 1)} for k, v in counter.items()}
```

#### 7. Clientes que não compraram essa semana
```python
def clientes_inativos(vendas_semana: list[dict], todos_clientes: list[str]) -> list[str]:
    """
    todos_clientes: lista de clientes da coluna A da planilha
    vendas_semana: vendas registradas essa semana
    """
    compraram = {v['cliente'] for v in vendas_semana}
    return [c for c in todos_clientes if c not in compraram]
```

### Endpoints sugeridos no FastAPI

```
GET /api/vendas?semana=atual|passada&vendedor=X&dia=SEGUNDA
GET /api/relatorios/ranking-vendedores?semana=atual
GET /api/relatorios/ranking-clientes?semana=atual
GET /api/relatorios/produtos-mais-vendidos?semana=atual
GET /api/relatorios/caixas-por-dia?semana=atual
GET /api/relatorios/vendas-em-aberto?semana=atual
GET /api/relatorios/mix-pagamento?semana=atual
GET /api/relatorios/clientes-inativos?semana=atual
```

### Fonte de dados por período
- **semana=atual** → lê direto da planilha Google Sheets
- **semana=passada** → lê do PostgreSQL (tabela vendas_historico)
- **semana=personalizado&inicio=YYYY-MM-DD&fim=YYYY-MM-DD** → lê do PostgreSQL

---

## Leitura via API

### Endpoints utilizados

```
# Cabeçalho da aba (linha 4)
GET .../values/{aba}!A4:AZ4

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

### CRÍTICO ao ler dados da planilha

- **Nunca assuma índices de coluna fixos** — leia sempre o cabeçalho primeiro
- Use `A4:AZ4` para garantir que captura todas as colunas
- Só considere como venda válida: linhas onde a coluna VENDEDOR está preenchida
- Ignorar sempre: linhas 1-4, linhas com TOTAL, COMPRAS, DIFERENÇA, linhas vazias

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
    if not s:
        return ''
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return ' '.join(s.split()).upper()

def col_to_letter(index: int) -> str:
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
```

### Leitura de todas as linhas da aba
```python
LABELS_IGNORAR = {'TOTAL', 'COMPRAS', 'DIFERENCA', 'DIFERENÇA'}

def is_linha_valida(row: list, col_vendedor: int) -> bool:
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

### Leitura agregada da semana
```python
def get_vendas_semana() -> list[dict]:
    DIAS = ['SEGUNDA', 'TERÇA', 'QUARTA', 'QUINTA', 'SEXTA', 'SABADO', 'DOMINGO']
    vendas = []
    
    for aba in DIAS:
        try:
            cabecalho = get_cabecalho(aba)
            if not cabecalho:
                continue

            col_vendedor = next((i for i, h in enumerate(cabecalho) if normaliza(h) == 'VENDEDOR'), None)
            col_pagamento = next((i for i, h in enumerate(cabecalho) if normaliza(h) in ['DIN/PIX', 'DIN/CHQ']), None)
            col_preco = next((i for i, h in enumerate(cabecalho) if normaliza(h) in ['PRECOS', 'PRECO']), None)

            result = sheet.values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{aba}'!A:AZ"
            ).execute()
            linhas = result.get('values', [])

            for row in linhas[4:]:
                if not is_linha_valida(row, col_vendedor):
                    continue

                produtos = []
                for j in range(1, col_pagamento or len(row)):
                    if j < len(cabecalho) and j < len(row):
                        nome = cabecalho[j].strip()
                        qtd = row[j]
                        if nome and qtd and str(qtd).strip().isdigit():
                            produtos.append({'nome': nome, 'quantidade': int(qtd)})

                if produtos:
                    vendas.append({
                        'cliente': row[0].strip(),
                        'vendedor': row[col_vendedor] if col_vendedor and col_vendedor < len(row) else '',
                        'pagamento': row[col_pagamento] if col_pagamento and col_pagamento < len(row) else '',
                        'preco': row[col_preco] if col_preco and col_preco < len(row) else '',
                        'produtos': produtos,
                        'dia': aba
                    })
        except Exception as e:
            print(f"Erro ao ler aba {aba}: {e}")

    return vendas
```

### Variáveis de ambiente necessárias
```env
SPREADSHEET_ID=1YeSqoZjU4npt8f0-jkzuieHK31J1dD7S4jt4ABD8SFI
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"..."}
```

> **Nota:** Passe o JSON completo como string na variável de ambiente — facilita o deploy no EasyPanel.
