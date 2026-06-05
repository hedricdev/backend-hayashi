# Task 06 — Playwright: Importação de Pedidos no iFruti

## Objetivo
Implementar o método que navega até a tela de lançamento de pedido do iFruti e preenche os dados de cada venda, continuando a task anterior de autenticação.

## Dependências
- Task 05 (autenticação) deve estar concluída
- Acesso real ao iFruti da Hayashi para mapear os seletores

## Arquivos a Editar

- `services/scraping.py`

## Implementação

### Método `importar_venda(self, venda: dict) -> str`
Adicionar à classe `IFrutiScraper`.

Recebe um dicionário no formato retornado pelo serviço Sheets (task 04):
```python
{
    "cliente": str,
    "vendedor": str,
    "pagamento": str,
    "preco": str,
    "itens": [{"produto": str, "quantidade": str}]
}
```

Retorna o ID do pedido gerado no iFruti (string).

#### Fluxo esperado no iFruti:
1. Navegar para a tela de novo pedido (ex: `/pedidos/novo` ou equivalente)
2. Preencher campo de cliente (busca por nome)
3. Selecionar o cliente nos resultados
4. Para cada item na lista `venda["itens"]`:
   - Buscar o produto pelo nome
   - Preencher a quantidade
5. Preencher forma de pagamento
6. Preencher o preço/valor total
7. Confirmar/salvar o pedido
8. Capturar o ID gerado (número do pedido exibido na tela de confirmação)
9. Retornar esse ID como string

#### Tratamento de erros por venda:
- Se o cliente não for encontrado no iFruti: lançar `Exception(f"Cliente não encontrado: {venda['cliente']}")`
- Se o produto não for encontrado: lançar `Exception(f"Produto não encontrado: {item['produto']}")`
- Se o pedido não for confirmado: lançar `Exception(f"Falha ao confirmar pedido para {venda['cliente']}")`

**Atenção**: Todos os seletores são placeholders — precisam ser mapeados com acesso real ao iFruti. Marcar com `# TODO: seletor a verificar`.

### Estrutura final da classe `IFrutiScraper`

```python
class IFrutiScraper:
    async def __aenter__(self): ...
    async def __aexit__(self, *args): ...
    async def _autenticar(self): ...
    async def importar_venda(self, venda: dict) -> str: ...
```

## Critérios de Aceitação
- `scraper.importar_venda(venda)` navega, preenche e confirma o pedido no iFruti
- Retorna o ID do pedido como string
- Erros por venda individual são tratados e propagados como `Exception` com mensagem descritiva
- O método não fecha o browser (isso é responsabilidade do `__aexit__`)

## Notas
- Testar com 1 venda real antes de rodar em batch — validar que o pedido aparece corretamente no iFruti
- Verificar se o iFruti tem proteção anti-bot (CAPTCHA, rate limit) que exija delays entre requests
