import asyncio
import re
import unicodedata
from datetime import datetime

import pytz
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from config import settings
from services.produto_map import PRODUTO_MAP

LOGIN_URL = f"{settings.IFRUTI_URL}/admin-login.jsp"
MAX_LOGIN_TENTATIVAS = 3
FUSO = pytz.timezone("America/Sao_Paulo")


def _normaliza(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split()).upper()


# Mapa pré-normalizado para lookup O(1)
_MAPA_NORM: dict[str, str] = {_normaliza(k): v for k, v in PRODUTO_MAP.items()}


def _buscar_produto(nome_planilha: str, produtos_ifruti: list[dict]) -> dict | None:
    """Resolve o produto da planilha para a linha correspondente no iFruti.

    Prioridade:
    1. Mapper explícito (abreviação → nome completo)
    2. Match exato normalizado
    3. Match parcial (fallback)
    """
    chave = _normaliza(nome_planilha)

    nome_ifruti = _MAPA_NORM.get(chave)
    if nome_ifruti:
        match = next((p for p in produtos_ifruti if _normaliza(p["nome"]) == _normaliza(nome_ifruti)), None)
        if match:
            return match

    match = next((p for p in produtos_ifruti if _normaliza(p["nome"]) == chave), None)
    if match:
        return match

    return next(
        (p for p in produtos_ifruti if chave in _normaliza(p["nome"]) or _normaliza(p["nome"]) in chave),
        None,
    )


class IFrutiScraper:
    def __init__(self, headless: bool = True, slow_mo: int = 0, debug: bool = False):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._headless = headless
        self._slow_mo = slow_mo
        self._debug = debug
        # Buffer de logs de console/rede capturados da página (debug)
        self.page_logs: list[str] = []

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless, slow_mo=self._slow_mo
        )
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        if self._debug:
            self._attach_debug_listeners()
        await self._autenticar()
        return self

    def _attach_debug_listeners(self, page: Page | None = None):
        """Captura console e respostas de rede da página para diagnóstico."""
        page = page or self._page

        def on_console(msg):
            self.page_logs.append(f"[console.{msg.type}] {msg.text}")

        def on_pageerror(err):
            self.page_logs.append(f"[pageerror] {err}")

        def on_response(resp):
            try:
                url = resp.url
                # Só nos interessam chamadas dinâmicas (não estáticos)
                if any(x in url for x in (".js", ".css", ".png", ".jpg", ".woff", ".ico", ".gif")):
                    return
                self.page_logs.append(f"[net {resp.status}] {resp.request.method} {url}")
            except Exception:
                pass

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_response)

    async def __aexit__(self, *args):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # -------------------------------------------------------------------------
    # Autenticação
    # -------------------------------------------------------------------------

    async def _autenticar(self):
        page = self._page
        ultimo_erro = None

        for tentativa in range(1, MAX_LOGIN_TENTATIVAS + 1):
            try:
                await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

                # CPF — digita caractere a caractere para disparar AJAX que popula a Empresa
                await page.wait_for_selector("#cpf", state="visible", timeout=15000)
                await page.click("#cpf")
                await page.type("#cpf", settings.IFRUTI_CPF, delay=80)
                await page.press("#cpf", "Tab")

                # Aguarda opções reais (ignora placeholder value='0' "Carregando...")
                await page.wait_for_function(
                    "() => { const s = document.querySelector('#cnpj'); return s && s.options.length > 0 && s.options[0].value !== '0'; }",
                    timeout=10000,
                )

                # Seleciona empresa via JS para evitar problemas de encoding
                await page.eval_on_selector(
                    "#cnpj",
                    """(select, empresa) => {
                        const opt = Array.from(select.options).find(o => o.text.trim() === empresa);
                        if (!opt) throw new Error('Empresa não encontrada: ' + empresa);
                        select.value = opt.value;
                        select.dispatchEvent(new Event('change', { bubbles: true }));
                    }""",
                    settings.IFRUTI_EMPRESA,
                )

                await page.fill("#senha", settings.IFRUTI_PASSWORD)

                # Aguarda botão habilitar (Bootstrap remove classe "disabled" após validação)
                await page.wait_for_function(
                    "() => !document.querySelector('#login').classList.contains('disabled')",
                    timeout=10000,
                )
                await page.click("#login")

                await page.wait_for_function(
                    "() => !window.location.href.includes('admin-login')",
                    timeout=15000,
                )

                if "admin-login" in page.url:
                    raise Exception("Ainda na página de login — verifique as credenciais")

                return

            except Exception as e:
                ultimo_erro = e
                if tentativa < MAX_LOGIN_TENTATIVAS:
                    await asyncio.sleep(2)

        raise Exception(
            f"Falha na autenticação após {MAX_LOGIN_TENTATIVAS} tentativas. "
            f"Último erro: {ultimo_erro}"
        )

    # -------------------------------------------------------------------------
    # Navegação — menus
    # -------------------------------------------------------------------------

    async def _navegar_lista_diaria(self):
        """Abre o menu Administrar Loja > Pedidos > Lista Diária."""
        page = self._page
        await page.click("a:has(i.fa-building)")
        await page.wait_for_timeout(800)
        await page.wait_for_selector("a:has-text('Pedidos')", state="visible", timeout=5000)
        await page.click("a:has-text('Pedidos')")
        await page.wait_for_timeout(800)
        await page.wait_for_selector("#menu_grpPedidos", state="visible", timeout=5000)
        await page.click("#menu_grpPedidos")
        await page.wait_for_selector("#btnCriarLista", state="visible", timeout=15000)

    # -------------------------------------------------------------------------
    # Helpers internos
    # -------------------------------------------------------------------------

    async def _preencher_data_remessa(self, data_str: str):
        """Preenche #dataRemessa e aguarda o botão Confirmar habilitar."""
        page = self._page
        # O input é escondido pelo datepicker — usa attached + force para preencher sem checar visibilidade
        await page.wait_for_selector("#dataRemessa", state="attached", timeout=30000)
        await page.fill("#dataRemessa", data_str, force=True)
        await page.dispatch_event("#dataRemessa", "change")
        await page.dispatch_event("#dataRemessa", "input")
        await page.wait_for_function(
            "() => { const b = document.querySelector('#btn-criar-grp-pedido'); return b && !b.classList.contains('disabled'); }",
            timeout=30000,
        )

    async def _limpar_modais(self):
        """Força o fechamento de todos os modais Bootstrap e remove backdrops."""
        await self._page.evaluate("""
            () => {
                const jq = window.jQuery || window.$ || null;
                if (jq) {
                    try { jq('.modal.in, .modal.show, .modal[style*="display: block"]').modal('hide'); } catch(e) {}
                    jq('.modal').each(function() {
                        jq(this).hide().removeClass('in show').attr('aria-hidden', 'true');
                    });
                    jq('.modal-backdrop').remove();
                    jq('body').removeClass('modal-open').css({'padding-right': '', 'overflow': ''});
                } else {
                    document.querySelectorAll('.modal.in, .modal.show, .modal[style*="display: block"]')
                        .forEach(m => { m.style.display = 'none'; m.classList.remove('in', 'show'); m.setAttribute('aria-hidden', 'true'); });
                    document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());
                    document.body.classList.remove('modal-open');
                    document.body.style.paddingRight = '';
                    document.body.style.overflow = '';
                }
            }
        """)
        await self._page.wait_for_timeout(400)

    async def _selecionar_fornecedor(self, pid: str, fornecedor: str):
        page = self._page

        await page.evaluate(f"() => document.querySelector('#btnBuscaFornecedor_{pid}').click()")
        await page.wait_for_selector("#idFornecedorSel", state="attached", timeout=10000)
        await page.wait_for_timeout(500)

        selecionado = await page.evaluate(
            """([fornecedor]) => {
                const sel = document.querySelector('#idFornecedorSel');
                if (!sel) return 'SELECT_NAO_ENCONTRADO';
                const opt = Array.from(sel.options).find(
                    o => o.text.trim().toUpperCase() === fornecedor.toUpperCase()
                );
                if (!opt) return 'OPCAO_NAO_ENCONTRADA: ' + fornecedor;
                sel.value = opt.value;
                $(sel).trigger('change').trigger('chosen:updated');
                return 'OK:' + opt.text.trim();
            }""",
            [fornecedor],
        )

        if not selecionado.startswith("OK"):
            raise Exception(f"Fornecedor não selecionado: {selecionado}")

        await page.wait_for_timeout(400)
        await page.evaluate("() => document.querySelector('#btnSelecionarFornecedor').click()")
        await page.wait_for_timeout(500)
        await self._limpar_modais()

    async def _salvar_linha(self, pid: str):
        page = self._page
        await page.wait_for_function(
            f"() => {{ const b = document.querySelector('#idItemCompra_{pid}'); return b && !b.disabled; }}",
            timeout=10000,
        )
        await page.click(f"#idItemCompra_{pid}", force=True)
        await page.wait_for_timeout(1000)
        await self._limpar_modais()

    async def _incluir_via_modal(
        self,
        primeiro_pid: str,
        nome_busca: str,
        quantidade: int,
        valor: str,
        fornecedor: str,
    ) -> bool:
        """Fallback: clica em btnNovoItem_ e insere via modal 'Incluir novo item'.
        Retorna True se o produto foi encontrado no catálogo e inserido."""
        page = self._page
        await page.evaluate(
            f"() => document.querySelector('#btnNovoItem_{primeiro_pid}').click()"
        )
        await page.wait_for_selector("#idProduto", state="attached", timeout=10000)
        await page.wait_for_timeout(500)

        resultado = await page.evaluate(
            """([nome, forn]) => {
                const norm = s => s.toUpperCase().trim()
                    .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
                const normNome = norm(nome);

                const sel = document.querySelector('#idProduto');
                if (!sel) return 'PROD_SELECT_NAO_ENCONTRADO';

                // match exato primeiro, depois parcial
                const opt =
                    Array.from(sel.options).find(o => norm(o.text) === normNome) ||
                    Array.from(sel.options).find(
                        o => norm(o.text).includes(normNome) || normNome.includes(norm(o.text))
                    );
                if (!opt) return 'NAO_NO_CATALOGO:' + nome;
                sel.value = opt.value;
                $(sel).trigger('change').trigger('chosen:updated');

                const selForn = document.querySelector('select#idFornecedor');
                if (selForn && selForn.options) {
                    const optForn = Array.from(selForn.options).find(
                        o => norm(o.text) === norm(forn)
                    );
                    if (optForn) {
                        selForn.value = optForn.value;
                        $(selForn).trigger('change').trigger('chosen:updated');
                    }
                }
                return 'OK:' + opt.text.trim();
            }""",
            [nome_busca, fornecedor],
        )

        if not resultado.startswith("OK"):
            await self._limpar_modais()
            return False

        await page.wait_for_timeout(300)
        modal = page.locator(".modal.in").last
        await modal.locator("#qtdeCompra").fill(str(quantidade))
        await modal.locator("#valorCompra").fill(valor)
        await page.wait_for_timeout(200)
        await modal.locator("#btn-novo-item").click()
        await page.wait_for_timeout(1500)
        await self._limpar_modais()
        return True

    # -------------------------------------------------------------------------
    # Fluxo 1 — Lista Diária (registro de compras/estoque)
    # -------------------------------------------------------------------------

    async def criar_lista_diaria(self, itens: list[dict], progress=None):
        async def emit(msg: str):
            if progress:
                await progress(msg)

        page = self._page
        await emit("Navegando para Lista Diária...")
        await self._navegar_lista_diaria()

        await emit("Criando nova lista...")
        await page.click("#btnCriarLista")
        await page.wait_for_timeout(1000)
        hoje = datetime.now(FUSO).strftime("%d/%m/%Y")
        await self._preencher_data_remessa(hoje)
        await page.click("#btn-criar-grp-pedido")
        await page.wait_for_load_state("networkidle", timeout=30000)
        await self._limpar_modais()

        await page.click("#btnPedidos", force=True)
        await page.wait_for_load_state("networkidle", timeout=30000)
        await self._limpar_modais()

        await page.wait_for_selector("table tbody tr", state="visible", timeout=30000)
        await page.click("table tbody tr .btn-primary.btn-xs", force=True)
        await page.wait_for_timeout(3000)
        await self._limpar_modais()

        produtos_ifruti = await page.evaluate("""
            () => Array.from(document.querySelectorAll('[id^="nomeProduto_"]'))
                .map(el => ({
                    pid: el.id.replace('nomeProduto_', ''),
                    nome: el.innerText.trim()
                }))
        """)
        await emit(f"{len(itens)} produto(s) para importar")

        erros = []
        primeiro_pid = produtos_ifruti[0]["pid"] if produtos_ifruti else None

        for item in itens:
            fornecedor = item.get("fornecedor") or getattr(settings, "IFRUTI_FORNECEDOR", "JOAOZINHO")
            valor_limpo = re.sub(r"[^\d.,]", "", str(item["valor"])).replace(".", ",")
            quantidade = int(item["quantidade"])

            match = _buscar_produto(item["produto"], produtos_ifruti)

            if not match:
                # Fallback: tenta inserir via modal "Incluir novo item"
                nome_busca = _MAPA_NORM.get(_normaliza(item["produto"])) or item["produto"]
                if not primeiro_pid:
                    msg = f"Sem linhas na tabela para abrir modal: {item['produto']!r}"
                    erros.append(msg)
                    await emit(f"✗ {msg}")
                    continue
                try:
                    ok = await self._incluir_via_modal(
                        primeiro_pid, nome_busca, quantidade, valor_limpo, fornecedor
                    )
                    if ok:
                        await emit(f"✓ {item['produto']} (via modal)")
                    else:
                        msg = f"Não cadastrado no iFruti: {item['produto']!r}"
                        erros.append(msg)
                        await emit(f"✗ {msg}")
                except Exception as e:
                    msg = f"Erro ao inserir via modal {item['produto']!r}: {e}"
                    erros.append(msg)
                    await emit(f"✗ {msg}")
                continue

            pid = match["pid"]
            try:
                qtde_locator = page.locator(f"#qtdeCompra_{pid}")
                await qtde_locator.scroll_into_view_if_needed(timeout=5000)
                await qtde_locator.fill(str(quantidade))
                await qtde_locator.press("Tab")
                await page.wait_for_timeout(400)

                valor_locator = page.locator(f"#valorCompra_{pid}")
                await valor_locator.fill(valor_limpo)
                await valor_locator.press("Tab")
                await page.wait_for_timeout(400)
                await self._selecionar_fornecedor(pid, fornecedor)
                await self._salvar_linha(pid)
                await emit(f"✓ {item['produto']}")
            except Exception as e:
                msg = f"Erro em {item['produto']!r}: {e}"
                erros.append(msg)
                await emit(f"✗ {msg}")

        ok = len(itens) - len(erros)
        await emit(f"CONCLUIDO:{ok} ok, {len(erros)} erro(s)")
        return {"ok": True, "erros": erros}

    # -------------------------------------------------------------------------
    # Fluxo 2 — Entrada de Pedido / Distribuidora (registro de vendas)
    # -------------------------------------------------------------------------

    async def _navegar_distribuidora(self):
        """Abre o menu Administrar Loja > Mercadorias > Distribuidora."""
        page = self._page
        await page.click("a:has(i.fa-building)")
        await page.wait_for_timeout(800)
        await page.wait_for_selector("a:has-text('Mercadorias')", state="visible", timeout=5000)
        await page.click("a:has-text('Mercadorias')")
        await page.wait_for_timeout(800)
        await page.wait_for_selector("a:has-text('Distribuidora')", state="visible", timeout=5000)
        await page.click("a:has-text('Distribuidora')")
        await page.wait_for_selector("#btnNovaCompra", state="visible", timeout=15000)

    # -------------------------------------------------------------------------
    # Fluxo 3 — Exportação de vendas por período (Distribuidora > Exportar Excel)
    # -------------------------------------------------------------------------

    async def exportar_vendas_periodo(self, data_inicio: str, data_fim: str) -> bytes:
        """Exporta o relatório de vendas da Distribuidora num período.

        data_inicio/data_fim no formato dd/mm/aaaa. Usado para sincronizar
        vendas_historico sob demanda.

        O filtro de data é aplicado do lado da sessão pelo botão "Consultar"
        (#btnDstr, submit real de formulário) — sem isso, a exportação ignora
        as datas e devolve uma tabela vazia. Depois de consultar, o botão
        "Exportar Excel" abre uma aba nova que baixa o arquivo e fecha quase
        instantaneamente — rápido demais pra capturar via evento de
        download/popup do Playwright de forma confiável. Em vez de depender
        desse clique, batemos direto no endpoint que ele chama (confirmado
        pelo usuário: AdminDstr?opcao=exportarExcel), reaproveitando os
        cookies de sessão já autenticados no contexto do browser — a essa
        altura já com o filtro de data aplicado.

        Retorna os bytes do .xls (na prática HTML — mesmo formato que
        parse_ifruti_xls já sabe ler).
        """
        page = self._page
        await self._navegar_distribuidora()

        await page.wait_for_selector("#dataInicial", state="attached", timeout=15000)
        await page.fill("#dataInicial", data_inicio, force=True)
        await page.dispatch_event("#dataInicial", "change")
        await page.dispatch_event("#dataInicial", "input")

        await page.wait_for_selector("#dataFinal", state="attached", timeout=15000)
        await page.fill("#dataFinal", data_fim, force=True)
        await page.dispatch_event("#dataFinal", "change")
        await page.dispatch_event("#dataFinal", "input")

        await page.wait_for_selector("#btnDstr", state="visible", timeout=15000)
        await page.click("#btnDstr")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        resp = await self._context.request.get(
            f"{settings.IFRUTI_URL}/AdminDstr",
            params={
                "opcao": "exportarExcel",
                "dataInicial": data_inicio,
                "dataFinal": data_fim,
            },
        )
        if not resp.ok:
            raise Exception(f"Requisição de exportação falhou: HTTP {resp.status}")
        return await resp.body()

    async def exportar_vendas_em_aberto(self) -> bytes:
        """Exporta TODAS as vendas atualmente em aberto no iFruti, sem filtro de data.

        A tela Distribuidora tem um select "situacao" (#situacao, plugin
        Chosen) com as opções: 0=Vendas (todas), 1=Em Aberto, 2=Em Atraso,
        3=Recebido. Ao selecionar "Em Aberto", o campo de datas trava em
        hoje e o filtro de data é ignorado pelo servidor — a exportação
        devolve tudo que está em aberto até agora, independente de quando a
        venda foi feita.

        Isso permite reconciliar fiado antigo sem depender de uma janela de
        datas (diferente de exportar_vendas_periodo): quem estava em aberto
        no nosso banco e sumiu dessa lista foi pago.

        Mesmo padrão de exportar_vendas_periodo: aplica o filtro via
        "Consultar" (#btnDstr) e bate direto na URL de exportação
        reaproveitando os cookies de sessão do contexto do browser.
        """
        page = self._page
        await self._navegar_distribuidora()

        await page.wait_for_selector("#situacao", state="attached", timeout=15000)
        resultado = await page.evaluate(
            """() => {
                const sel = document.querySelector('#situacao');
                if (!sel) return 'ERR:select situacao não encontrado';
                const opt = Array.from(sel.options).find(o => o.value === '1');
                if (!opt) return 'ERR:opção Em Aberto (value=1) não encontrada';
                sel.value = opt.value;
                const jq = window.jQuery || window.$ || null;
                if (jq) jq(sel).trigger('change').trigger('chosen:updated');
                else sel.dispatchEvent(new Event('change', { bubbles: true }));
                return 'OK';
            }"""
        )
        if resultado != "OK":
            raise Exception(resultado.replace("ERR:", "", 1))

        await page.wait_for_selector("#btnDstr", state="visible", timeout=15000)
        await page.click("#btnDstr")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        resp = await self._context.request.get(
            f"{settings.IFRUTI_URL}/AdminDstr",
            params={"opcao": "exportarExcel"},
        )
        if not resp.ok:
            raise Exception(f"Requisição de exportação falhou: HTTP {resp.status}")
        return await resp.body()

    # -------------------------------------------------------------------------
    # Fluxo 4 — Lucro do período (Administrar Loja > Resultado > DRE)
    # -------------------------------------------------------------------------

    _RE_LUCRO_PERIODO = re.compile(
        r"(?:Lucro|Preju[íi]zo) do per[íi]odo:\s*(-)?R\$\s*([\d.,]+)\s*\(([\-\d,]+|\?)%\)"
    )

    async def buscar_lucro_periodo(self, data_inicio: str, data_fim: str) -> dict:
        """Lê o "Lucro do período" (ou "Prejuízo do período", quando negativo)
        na tela Administrar Loja > Resultado > DRE. data_inicio/data_fim no
        formato dd/mm/aaaa.

        Essa tela não tem exportação — o valor só existe como texto renderizado
        no resultado da consulta, por isso extraímos via regex do texto da
        página em vez de bater num endpoint de exportação (diferente dos
        outros fluxos de Distribuidora).

        Preencher os inputs de data exige disparar os eventos que o datepicker
        da tela escuta (change/changeDate/dp.change/blur via jQuery) — um
        simples fill()+dispatch_event("change") não é suficiente aqui: o valor
        aparece preenchido na tela mas é descartado pelo servidor ao consultar,
        que devolve o período default (hoje-hoje) em vez do período pedido.

        Quando o período não tem faturamento, o iFruti mostra a porcentagem
        como "?" (evita divisão por zero) — nesse caso margem_pct volta None.
        """
        page = self._page

        # Logo após o login, a página do painel pode ainda não ter terminado
        # de carregar seus scripts (jQuery incluso) — aguarda antes de mexer
        # nos menus pra evitar corrida.
        await page.wait_for_function("() => !!(window.jQuery || window.$)", timeout=15000)

        await page.click("a:has(i.fa-building)")
        await page.wait_for_timeout(800)
        await page.wait_for_selector("a:has-text('Resultado')", state="visible", timeout=5000)
        await page.click("a:has-text('Resultado')")
        await page.wait_for_timeout(800)
        await page.wait_for_selector("#menu_grpDre", state="visible", timeout=5000)
        await page.click("#menu_grpDre")
        await page.wait_for_selector("#dtPeriodoIni", state="visible", timeout=15000)
        # #menu_grpDre navega pra uma URL nova (recarrega a página) — o HTML
        # estático chega antes do script do jQuery terminar de carregar.
        await page.wait_for_function("() => !!(window.jQuery || window.$)", timeout=15000)

        resultado = await page.evaluate(
            """([ini, fim]) => {
                const jq = window.jQuery || window.$;
                if (!jq) return 'ERR:jQuery não encontrado';
                jq('#dtPeriodoIni').val(ini).trigger('change').trigger('changeDate').trigger('dp.change').trigger('blur');
                jq('#dtPeriodoFim').val(fim).trigger('change').trigger('changeDate').trigger('dp.change').trigger('blur');
                return 'OK';
            }""",
            [data_inicio, data_fim],
        )
        if resultado != "OK":
            raise Exception(resultado.replace("ERR:", "", 1))

        await page.wait_for_selector("#btnPeriodo", state="visible", timeout=15000)
        await page.click("#btnPeriodo")
        await page.wait_for_function(
            "() => document.body.innerText.includes('do período:')",
            timeout=20000,
        )

        texto = await page.evaluate("() => document.body.innerText")
        match = self._RE_LUCRO_PERIODO.search(texto)
        if not match:
            raise Exception("Não foi possível encontrar 'Lucro do período' no resultado do DRE")

        sinal_str, valor_str, pct_str = match.groups()
        sinal = -1 if sinal_str == "-" else 1
        lucro = sinal * float(valor_str.replace(".", "").replace(",", "."))
        margem_pct = None if pct_str == "?" else float(pct_str.replace(",", "."))

        return {"lucro": round(lucro, 2), "margem_pct": margem_pct}

    # -------------------------------------------------------------------------
    # Fluxo 5 — Exportação de despesas por período (Financeiro > Despesas)
    # -------------------------------------------------------------------------

    async def _navegar_despesas(self):
        """Abre Administrar Loja > Financeiro > Despesas e aguarda o form carregar.

        Depois de consultar uma vez, a própria tela de resultado troca o menu
        de topo por um link "Voltar" (some o "Administrar Loja") — então, se
        o form de Despesas já estiver na página (ex: uma segunda consulta na
        mesma sessão, pra combinar período + em aberto), não precisa navegar
        de novo pelos menus, só reaproveita a tela atual.
        """
        page = self._page
        if await page.query_selector("#dataInicial"):
            return

        await page.wait_for_function("() => !!(window.jQuery || window.$)", timeout=15000)

        await page.click("a:has(i.fa-building)")
        await page.wait_for_timeout(800)
        await page.wait_for_selector("a:has-text('Financeiro')", state="visible", timeout=5000)
        await page.click("a:has-text('Financeiro')")
        await page.wait_for_timeout(800)
        await page.wait_for_selector("#menu_grpDespesas", state="visible", timeout=5000)
        await page.click("#menu_grpDespesas")
        await page.wait_for_selector("#dataInicial", state="attached", timeout=15000)
        await page.wait_for_function("() => !!(window.jQuery || window.$)", timeout=15000)

    async def _consultar_despesas_exportar(self) -> bytes:
        """Clica #btnDespesas (já com os filtros preenchidos) e baixa o Excel.

        O botão "Exportar para Excel" (#btnDespesasXls) dispara um download
        direto (não uma aba que renderiza HTML) para
        AdminGrupo?opcao=getDespesasXls — batemos direto nesse endpoint
        reaproveitando os cookies de sessão do contexto, mesmo padrão de
        exportar_vendas_periodo.
        """
        page = self._page
        await page.wait_for_selector("#btnDespesas", state="visible", timeout=15000)
        await page.click("#btnDespesas")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        resp = await self._context.request.get(
            f"{settings.IFRUTI_URL}/AdminGrupo",
            params={"opcao": "getDespesasXls"},
        )
        if not resp.ok:
            raise Exception(f"Requisição de exportação falhou: HTTP {resp.status}")
        return await resp.body()

    async def exportar_despesas_periodo(self, data_inicio: str, data_fim: str) -> bytes:
        """Exporta a tela Financeiro > Despesas num período. data_inicio/
        data_fim no formato dd/mm/aaaa.

        Preencher #dataInicial/#dataFinal exige a mesma cadeia de eventos
        jQuery da tela do DRE (change/changeDate/dp.change/blur) — mesmo
        motivo documentado em buscar_lucro_periodo.

        Retorna os bytes do .xls (HTML, mesmo formato que parse_despesas_xls
        já sabe ler).
        """
        page = self._page
        await self._navegar_despesas()

        resultado = await page.evaluate(
            """([ini, fim]) => {
                const jq = window.jQuery || window.$;
                if (!jq) return 'ERR:jQuery não encontrado';
                jq('#dataInicial').val(ini).trigger('change').trigger('changeDate').trigger('dp.change').trigger('blur');
                jq('#dataFinal').val(fim).trigger('change').trigger('changeDate').trigger('dp.change').trigger('blur');
                return 'OK';
            }""",
            [data_inicio, data_fim],
        )
        if resultado != "OK":
            raise Exception(resultado.replace("ERR:", "", 1))

        return await self._consultar_despesas_exportar()

    async def exportar_despesas_em_aberto(self) -> bytes:
        """Exporta TODAS as despesas atualmente em aberto, sem depender de
        uma janela de datas.

        Diferente da tela de Distribuidora (onde selecionar "Em Aberto"
        trava/ignora o filtro de data), a tela de Despesas combina os dois
        filtros: selecionar #situacao=1 sozinho só devolve os itens em
        aberto DENTRO do período de datas já preenchido (por padrão,
        hoje-hoje). Por isso aqui preenchemos também uma data inicial bem
        antiga (01/01/2000) até hoje, além de #situacao=1 — confirmado ao
        vivo que a combinação dos dois devolve o total real em aberto da
        conta (bate com o rodapé "Vlr. Aberto" da tela).

        Permite reconciliar despesas antigas que só foram pagas bem depois
        da janela de sincronização por período (mesmo problema que
        reconciliar_fiado resolve pra vendas).
        """
        page = self._page
        await self._navegar_despesas()

        hoje = datetime.now(FUSO).strftime("%d/%m/%Y")
        resultado = await page.evaluate(
            """([fim]) => {
                const jq = window.jQuery || window.$;
                if (!jq) return 'ERR:jQuery não encontrado';
                const sel = document.querySelector('#situacao');
                if (!sel) return 'ERR:select situacao não encontrado';
                sel.value = '1';
                jq(sel).trigger('change');
                jq('#dataInicial').val('01/01/2000').trigger('change').trigger('changeDate').trigger('dp.change').trigger('blur');
                jq('#dataFinal').val(fim).trigger('change').trigger('changeDate').trigger('dp.change').trigger('blur');
                return 'OK';
            }""",
            [hoje],
        )
        if resultado != "OK":
            raise Exception(resultado.replace("ERR:", "", 1))

        return await self._consultar_despesas_exportar()

    # -------------------------------------------------------------------------
    # Fluxo 6 — Exportação de compras (Mercadorias > Compras)
    # -------------------------------------------------------------------------

    async def _navegar_compras(self):
        """Abre Administrar Loja > Mercadorias > Compras e aguarda o form
        carregar. Mesma proteção de _navegar_despesas: se o form já estiver
        na página (2ª consulta na mesma sessão), pula a navegação por menu.
        """
        page = self._page
        if await page.query_selector("#dataInicial"):
            return

        await page.wait_for_function("() => !!(window.jQuery || window.$)", timeout=15000)

        await page.click("a:has(i.fa-building)")
        await page.wait_for_timeout(800)
        await page.wait_for_selector("a:has-text('Mercadorias')", state="visible", timeout=5000)
        await page.click("a:has-text('Mercadorias')")
        await page.wait_for_timeout(800)
        await page.wait_for_selector("#menu_grpCompras", state="visible", timeout=5000)
        await page.click("#menu_grpCompras")
        await page.wait_for_selector("#dataInicial", state="attached", timeout=15000)
        await page.wait_for_function("() => !!(window.jQuery || window.$)", timeout=15000)

    async def _consultar_compras_exportar(self) -> bytes:
        """Clica #btnCompras (já com os filtros preenchidos) e baixa o Excel.

        A URL certa é AdminGrupo?opcao=getComprasXls (com "s" em Compras —
        confirmado capturando o evento de download real do botão; um
        primeiro palpite sem o "s" retorna a página de login).
        """
        page = self._page
        await page.wait_for_selector("#btnCompras", state="visible", timeout=15000)
        await page.click("#btnCompras")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        resp = await self._context.request.get(
            f"{settings.IFRUTI_URL}/AdminGrupo",
            params={"opcao": "getComprasXls"},
        )
        if not resp.ok:
            raise Exception(f"Requisição de exportação falhou: HTTP {resp.status}")
        return await resp.body()

    async def exportar_compras_periodo(self, data_inicio: str, data_fim: str) -> bytes:
        """Exporta a tela Mercadorias > Compras num período. data_inicio/
        data_fim no formato dd/mm/aaaa.

        Retorna os bytes do .xls (HTML, mesmo formato que
        parse_compras_xls já sabe ler).
        """
        page = self._page
        await self._navegar_compras()

        resultado = await page.evaluate(
            """([ini, fim]) => {
                const jq = window.jQuery || window.$;
                if (!jq) return 'ERR:jQuery não encontrado';
                jq('#dataInicial').val(ini).trigger('change').trigger('changeDate').trigger('dp.change').trigger('blur');
                jq('#dataFinal').val(fim).trigger('change').trigger('changeDate').trigger('dp.change').trigger('blur');
                return 'OK';
            }""",
            [data_inicio, data_fim],
        )
        if resultado != "OK":
            raise Exception(resultado.replace("ERR:", "", 1))

        return await self._consultar_compras_exportar()

    async def exportar_compras_em_aberto(self) -> bytes:
        """Exporta TODAS as compras atualmente em aberto, sem depender de
        uma janela de datas — mesmo raciocínio de exportar_despesas_em_aberto:
        selecionar #situacao=1 sozinho só devolve os itens em aberto DENTRO
        do período já preenchido, por isso combina com uma data inicial
        bem antiga (01/01/2000) até hoje. Confirmado ao vivo.
        """
        page = self._page
        await self._navegar_compras()

        hoje = datetime.now(FUSO).strftime("%d/%m/%Y")
        resultado = await page.evaluate(
            """([fim]) => {
                const jq = window.jQuery || window.$;
                if (!jq) return 'ERR:jQuery não encontrado';
                const sel = document.querySelector('#situacao');
                if (!sel) return 'ERR:select situacao não encontrado';
                sel.value = '1';
                jq(sel).trigger('change');
                jq('#dataInicial').val('01/01/2000').trigger('change').trigger('changeDate').trigger('dp.change').trigger('blur');
                jq('#dataFinal').val(fim).trigger('change').trigger('changeDate').trigger('dp.change').trigger('blur');
                return 'OK';
            }""",
            [hoje],
        )
        if resultado != "OK":
            raise Exception(resultado.replace("ERR:", "", 1))

        return await self._consultar_compras_exportar()

    async def _preencher_form_venda(
        self, cliente: str, produto: str, quantidade: int, valor: str,
        salvar: bool = True,
    ) -> str:
        """Preenche e salva um item no modal de venda da Distribuidora.

        O formulário "+ Vender" abre como Bootstrap modal (.modal.in).
        Todo o escopo é feito dentro do modal aberto, evitando confundir
        com os filtros da página ou forms de edição de registros existentes.

        Com salvar=False não clica em Salvar (dry-run para diagnóstico):
        apenas resolve/preenche os campos e retorna o estado.

        Retorna 'OK:<produto>' ou lança Exception.
        """
        resultado = await self._page.evaluate(
            """([empresa, produto, qtd, valor, salvar]) => {
                const norm = s => s.toUpperCase().trim()
                    .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
                // jQuery pode estar em noConflict ($ indefinido, jQuery disponível)
                const jq = window.jQuery || window.$ || null;
                const triggerJQ = (el, ...events) => {
                    if (jq) events.forEach(ev => jq(el).trigger(ev));
                    else events.forEach(ev => el.dispatchEvent(new Event(ev, { bubbles: true })));
                };
                // Casa um termo contra as options de um select.
                // IGNORA options sem value ou com texto vazio (a 1ª option costuma
                // ser um placeholder em branco). Sem isso, includes('') casaria
                // com a option vazia e o campo seria enviado em branco.
                const matchOption = (sel, termo) => {
                    const t = norm(termo);
                    if (!t) return null;
                    const opts = Array.from(sel.options).filter(
                        o => o.value && o.value !== '0' && norm(o.text).length > 0
                    );
                    // 1. exato
                    let m = opts.find(o => norm(o.text) === t);
                    if (m) return m;
                    // 2. parcial — exige sobreposição real (nada de includes('') )
                    return opts.find(o => {
                        const ot = norm(o.text);
                        return ot.includes(t) || t.includes(ot);
                    }) || null;
                };

                // Âncora: o modal Bootstrap aberto (.modal.in ou .modal.show)
                const modal = document.querySelector('.modal.in')
                           || document.querySelector('.modal.show');
                if (!modal) return 'ERR:Modal não encontrado (.modal.in / .modal.show)';

                // ── Cliente ────────────────────────────────────────────────
                const empSel = modal.querySelector('select#idEmpresa')
                            || modal.querySelector('select[name=idEmpresa]');
                if (!empSel) return 'ERR:select idEmpresa não está no modal';
                const empOpt = matchOption(empSel, empresa);
                if (!empOpt) return 'ERR:Empresa não encontrada: ' + empresa;
                empSel.value = empOpt.value;
                triggerJQ(empSel, 'change', 'chosen:updated');

                // ── Produto ────────────────────────────────────────────────
                const prodSel = modal.querySelector('select[name=idProduto]');
                if (!prodSel) return 'ERR:select idProduto não encontrado no modal';
                const prodOpt = matchOption(prodSel, produto);
                if (!prodOpt) return 'ERR:Produto não encontrado: ' + produto;
                prodSel.value = prodOpt.value;
                triggerJQ(prodSel, 'change', 'chosen:updated');

                // ── Quantidade ─────────────────────────────────────────────
                const qtdEl = modal.querySelector('#qtdeAtendido');
                if (!qtdEl) return 'ERR:qtdeAtendido não encontrado no modal';
                qtdEl.value = qtd;
                triggerJQ(qtdEl, 'input', 'change');

                // ── Valor ──────────────────────────────────────────────────
                const valorEl = modal.querySelector('#valorVenda');
                if (!valorEl) return 'ERR:valorVenda não encontrado no modal';
                valorEl.value = valor;
                triggerJQ(valorEl, 'input', 'change');

                // ── Salvar ─────────────────────────────────────────────────
                const btn = modal.querySelector('#btn-novo-item');
                if (!btn) return 'ERR:btn-novo-item não encontrado no modal';
                if (salvar) btn.click();

                return 'OK:' + empOpt.text.trim() + ' | ' + prodOpt.text.trim()
                     + ' (idEmpresa=' + empSel.value + ')';
            }""",
            [cliente, produto, str(quantidade), valor, salvar],
        )
        if not resultado.startswith("OK"):
            raise Exception(resultado.replace("ERR:", "", 1))
        return resultado

    async def _aguardar_resultado_save(self) -> str:
        """Lê o alerta de feedback do iFruti após clicar em Salvar.

        Sucesso: "Produto incluído com sucesso! ..."
        Erro:    "Selecione um item da lista." / "...informar todos os campos.
                  Inclusão cancelada!"

        O modal permanece aberto em ambos os casos. Retorna o texto do alerta
        (ou string vazia se nada apareceu dentro do timeout).
        """
        page = self._page
        try:
            await page.wait_for_function(
                """() => {
                    const txt = Array.from(document.querySelectorAll(
                        '.alert, .swal2-popup, .toast, .modal.in, .help-block'))
                        .filter(e => e.offsetParent)
                        .map(e => e.innerText || '').join(' ');
                    return /sucesso|cancelad|selecione um item|informar todos|informe/i.test(txt);
                }""",
                timeout=8000,
            )
        except Exception:
            return ""
        return await page.evaluate(
            """() => {
                const els = Array.from(document.querySelectorAll(
                    '.alert, .swal2-popup, .toast, .help-block'))
                    .filter(e => e.offsetParent && (e.innerText || '').trim());
                if (els.length) return els[els.length - 1].innerText.trim();
                return '';
            }"""
        )

    async def criar_entradas_pedido(
        self, vendas: list[dict], aba: str, progress=None
    ):
        """Lança todas as vendas pendentes da aba no iFruti (Distribuidora).

        Para cada venda da planilha:
        - Cria uma entrada por item (produto × quantidade × valor unitário)
        - Marca a linha como importada na planilha após todos os itens OK
        """
        from services.sheets import marcar_como_importado

        async def emit(msg: str):
            if progress:
                await progress(msg)

        page = self._page
        await emit("Navegando para Distribuidora...")
        await self._navegar_distribuidora()
        await emit(f"{len(vendas)} venda(s) pendente(s) para importar")

        erros: list[str] = []

        for venda in vendas:
            cliente = venda["cliente"]
            linha = venda["linha_numero"]
            itens = venda["itens"]

            # Parseia preços: "110/90" → [110.0, 90.0]
            precos: list[float] = []
            for parte in venda.get("preco", "").replace(",", ".").split("/"):
                try:
                    precos.append(float(parte.strip()))
                except ValueError:
                    pass

            def valor_unitario(idx: int) -> str:
                if precos and idx < len(precos):
                    v = precos[idx]
                elif precos:
                    v = sum(precos) / len(precos)
                else:
                    v = 0.0
                # iFruti aceita ponto decimal no campo valorVenda (validado em
                # teste real e consistente com o fluxo de lista diária).
                return f"{v:.2f}"

            itens_ok = 0
            for idx, item in enumerate(itens):
                produto = item["produto"]
                quantidade = int(item["quantidade"])
                valor = valor_unitario(idx)

                # Resolve abreviação da planilha para nome completo do iFruti
                nome_ifruti = _MAPA_NORM.get(_normaliza(produto)) or produto

                try:
                    await self._limpar_modais()
                    await page.click("#btnNovaCompra")
                    # O formulário "+ Vender" é um Bootstrap modal (.modal.in).
                    # Os inputs dentro do modal não são "visible" para o Playwright
                    # enquanto o Bootstrap ainda está animando — por isso esperamos
                    # pelo modal aberto, não pelo input.
                    await page.wait_for_selector(
                        ".modal.in",
                        state="visible",
                        timeout=10000,
                    )
                    await page.wait_for_timeout(300)  # aguarda fim da animação CSS

                    await self._preencher_form_venda(cliente, nome_ifruti, quantidade, valor)

                    # O iFruti NÃO fecha o modal após salvar: ele exibe um alerta
                    # de feedback. Lemos esse alerta para confirmar o resultado real
                    # — sem isso, contaríamos como sucesso mesmo quando o servidor
                    # rejeita ("Selecione um item", "informe todos os campos").
                    resultado = await self._aguardar_resultado_save()
                    if "SUCESSO" not in _normaliza(resultado):
                        raise Exception(f"iFruti rejeitou: {resultado or 'sem feedback'}")

                    await self._limpar_modais()
                    itens_ok += 1
                    await emit(f"✓ {cliente} — {produto} x{quantidade} @ R${valor}")
                except Exception as e:
                    msg = f"Erro em {cliente!r}/{produto!r}: {e}"
                    erros.append(msg)
                    await emit(f"✗ {msg}")
                    await self._limpar_modais()

            # Marca como importado apenas se TODOS os itens tiveram sucesso
            if itens_ok == len(itens):
                ts = datetime.now(FUSO).strftime("%d%m%Y%H%M")
                try:
                    marcar_como_importado(aba, linha, ts)
                except Exception as e:
                    await emit(f"✗ Erro ao marcar planilha ({cliente}): {e}")
            elif itens_ok > 0:
                await emit(
                    f"⚠ {cliente}: {itens_ok}/{len(itens)} itens importados — "
                    "linha não marcada (importar novamente para completar)"
                )

        await emit(f"CONCLUIDO:{len(vendas)} venda(s) processada(s), {len(erros)} erro(s)")
        return {"ok": True, "erros": erros}
