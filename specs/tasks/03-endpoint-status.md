# Task 03 — Endpoint GET /status

## Objetivo
Implementar o endpoint que retorna o status da última importação registrada no banco.

## Arquivos a Editar

- `routers/status.py`

## Implementação

### `routers/status.py`

`GET /status` — busca a última importação da tabela `importacoes` ordenada por `iniciado_em DESC`.

**Response quando existe importação:**
```json
{
  "status": "sucesso",
  "iniciado_em": "2026-05-26T10:00:00",
  "finalizado_em": "2026-05-26T10:02:15",
  "total_importado": 12,
  "total_erro": 0,
  "log": []
}
```

**Response quando não existe nenhuma importação:**
```json
{
  "status": "nenhuma_importacao",
  "iniciado_em": null,
  "finalizado_em": null,
  "total_importado": 0,
  "total_erro": 0,
  "log": []
}
```

### Schema de resposta (Pydantic)
Criar o schema `StatusResponse` no próprio arquivo `routers/status.py`:
- `status: str`
- `iniciado_em: datetime | None`
- `finalizado_em: datetime | None`
- `total_importado: int`
- `total_erro: int`
- `log: list[str]` — desserializar o campo `log` (JSON string) do banco

### Lógica do `log`
O campo `log` no banco é uma string JSON (ex: `'["erro no cliente X", "erro no cliente Y"]'`). Ao retornar, fazer `json.loads(importacao.log or "[]")`.

## Critérios de Aceitação
- Com banco vazio: `GET /status` retorna 200 com `status: "nenhuma_importacao"`
- Após uma importação registrada: retorna os dados corretos da última importação
- Campo `log` sempre retorna lista (nunca null)
