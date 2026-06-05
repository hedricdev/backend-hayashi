# Task 07 — Endpoint POST /importar

## Objetivo
Implementar o endpoint principal que orquestra o fluxo completo de importação: lê a planilha, importa cada venda no iFruti via Playwright e registra o resultado no banco.

## Dependências
- Task 01 (modelos do banco)
- Task 04 (serviço Sheets)
- Task 05 e 06 (serviço Playwright)

## Arquivos a Editar

- `routers/importar.py`

## Implementação

### `POST /importar`

O endpoint executa a importação de forma síncrona (aguarda a conclusão para retornar).

#### Fluxo completo:
1. Criar registro na tabela `importacoes` com `status = "em_andamento"` e `iniciado_em = now()`
2. Chamar `get_aba_semana_atual()` para obter a lista de abas
3. Para cada aba, chamar `get_vendas_nao_importadas(aba)` para obter as vendas pendentes
4. Abrir `IFrutiScraper` (autenticar uma vez para todas as vendas)
5. Para cada venda:
   - Chamar `scraper.importar_venda(venda)`
   - Em caso de sucesso: chamar `marcar_como_importado(aba, venda["linha_numero"], ifruti_id)` e incrementar `total_importado`
   - Em caso de erro: adicionar mensagem ao `log` e incrementar `total_erro`
6. Atualizar o registro `importacoes` com `status`, `finalizado_em`, `total_importado`, `total_erro` e `log`
7. Retornar o resumo

#### Response de sucesso:
```json
{
  "importacao_id": 1,
  "status": "sucesso",
  "total_importado": 15,
  "total_erro": 0,
  "log": []
}
```

#### Response com erros parciais:
```json
{
  "importacao_id": 2,
  "status": "sucesso",
  "total_importado": 13,
  "total_erro": 2,
  "log": [
    "Cliente não encontrado: João Silva",
    "Produto não encontrado: Manga Palmer"
  ]
}
```

#### Response quando não há vendas pendentes:
```json
{
  "importacao_id": 3,
  "status": "sucesso",
  "total_importado": 0,
  "total_erro": 0,
  "log": ["Nenhuma venda pendente encontrada"]
}
```

#### Tratamento de erro crítico (ex: falha de autenticação no iFruti):
- Atualizar registro com `status = "erro"` e gravar erro no `log`
- Retornar HTTP 500 com detalhe do erro

### Schema de resposta (Pydantic)
```python
class ImportarResponse(BaseModel):
    importacao_id: int
    status: str
    total_importado: int
    total_erro: int
    log: list[str]
```

### Idempotência
A idempotência é garantida pelo serviço Sheets (task 04): `get_vendas_nao_importadas` só retorna linhas com coluna V vazia. Chamadas repetidas ao endpoint não reimportam vendas já marcadas.

## Critérios de Aceitação
- Endpoint retorna 200 com resumo correto após importação bem-sucedida
- Registro é criado e atualizado no banco em ambos os casos (sucesso e erro)
- Erros individuais por venda não abortam o batch — o processo continua para as demais
- Erros críticos (falha de auth, banco fora) retornam 500 com registro de status "erro" no banco
- Chamadas repetidas não duplicam importações (idempotência via coluna V)
