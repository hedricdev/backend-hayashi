# Task 05 — Playwright: Autenticação no iFruti

## Objetivo
Implementar a autenticação no sistema iFruti via Playwright, como primeiro passo do fluxo de scraping.

## Arquivos a Editar

- `services/scraping.py`

## Contexto
O iFruti é o sistema ERP da Hayashi. A importação consiste em abrir o navegador (headless), fazer login e depois navegar até a tela de lançamento de pedidos para cada venda.

As credenciais são `IFRUTI_EMAIL` e `IFRUTI_PASSWORD` do `.env`.

## Implementação

### `services/scraping.py`

#### Classe `IFrutiScraper`
Usar context manager para garantir que o browser seja fechado corretamente.

```python
from playwright.async_api import async_playwright, Page, Browser
from config import settings

class IFrutiScraper:
    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._page = await self._browser.new_page()
        await self._autenticar()
        return self

    async def __aexit__(self, *args):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _autenticar(self):
        # 1. Navegar para a página de login do iFruti
        # 2. Preencher email e senha
        # 3. Clicar em entrar
        # 4. Aguardar redirecionamento para o dashboard
        # 5. Verificar se está autenticado (checar elemento do dashboard)
        # Se falhar, lançar Exception("Falha na autenticação do iFruti")
        ...
```

**Atenção**: Os seletores CSS/XPath exatos da tela de login do iFruti precisam ser inspecionados no sistema real. Esta task exige acesso ao iFruti da Hayashi para mapear os seletores corretos. Deixar comentários `# TODO: verificar seletor` onde necessário.

#### Timeouts e Retry
- Usar `page.wait_for_selector()` com timeout de 15 segundos para elementos críticos
- Se o login falhar após 3 tentativas, lançar exceção com mensagem clara

#### Variáveis de Ambiente Necessárias
```
IFRUTI_URL=https://ifruti.com.br  # ou URL do sistema da Hayashi
IFRUTI_EMAIL=usuario@hayashi.com.br
IFRUTI_PASSWORD=senha_do_sistema
```

## Critérios de Aceitação
- `async with IFrutiScraper() as scraper:` abre o browser, faz login e fecha corretamente
- Credenciais erradas lançam `Exception` com mensagem descritiva
- Browser é sempre fechado mesmo em caso de erro (garantido pelo `__aexit__`)
- Funciona em modo headless (necessário para Docker/VPS)

## Notas Importantes
- Os seletores do iFruti precisam ser mapeados com acesso real ao sistema — coordenar com o cliente Hayashi para obter as credenciais e mapear a interface antes de implementar esta task completamente
- Registrar os seletores encontrados nos comentários do código para facilitar manutenção futura
