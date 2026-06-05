# Task 09 — Testes e Validação

## Objetivo
Validar o funcionamento completo da API em ambiente de produção (EasyPanel) após todas as tasks anteriores estarem concluídas.

## Dependências
Todas as tasks anteriores (00–08) concluídas e deploy realizado.

## Checklist de Validação

### 1. Health Check
```bash
curl https://api.hayashi.asynnc.cloud/health
# Esperado: {"status": "ok"}
```

### 2. Autenticação
```bash
# Sem API key — deve retornar 422 ou 401
curl -X POST https://api.hayashi.asynnc.cloud/importar

# Com API key errada — deve retornar 401
curl -X POST https://api.hayashi.asynnc.cloud/importar \
  -H "X-API-Key: chave_errada"

# Com API key correta — deve iniciar importação
curl -X POST https://api.hayashi.asynnc.cloud/importar \
  -H "X-API-Key: $API_SECRET_KEY"
```

### 3. Status sem importações
```bash
curl https://api.hayashi.asynnc.cloud/status \
  -H "X-API-Key: $API_SECRET_KEY"
# Esperado: {"status": "nenhuma_importacao", ...}
```

### 4. Leitura da Planilha
- Verificar que `get_vendas_nao_importadas` retorna dados corretos para a aba do dia atual
- Confirmar que linhas especiais (CUSTO, TOTAL, etc.) são ignoradas
- Confirmar que linhas sem vendedor (coluna U vazia) são ignoradas

### 5. Importação de Teste
- Ter pelo menos 1 linha na planilha com vendedor preenchido e coluna V vazia
- Chamar `POST /importar`
- Verificar no iFruti que o pedido foi criado corretamente
- Verificar que a coluna V da planilha foi preenchida com o ID do iFruti
- Chamar `POST /importar` novamente — confirmar que a mesma linha não é reimportada

### 6. Status após importação
```bash
curl https://api.hayashi.asynnc.cloud/status \
  -H "X-API-Key: $API_SECRET_KEY"
# Esperado: status "sucesso", total_importado > 0
```

### 7. Logs de erro
- Testar com um cliente que não existe no iFruti
- Verificar que o erro aparece no campo `log` da resposta
- Verificar que as outras vendas foram importadas normalmente (erro não aborta o batch)

## Critérios de Aceitação do MVP
- [ ] Todos os endpoints respondem corretamente
- [ ] Autenticação por API Key funciona
- [ ] Planilha é lida corretamente
- [ ] Pelo menos 1 importação real no iFruti funciona ponta a ponta
- [ ] Idempotência confirmada (sem duplicatas)
- [ ] Erros individuais não abortam o batch
- [ ] Logs registrados no banco de dados
- [ ] Container sobe automaticamente no EasyPanel após push para `main`
