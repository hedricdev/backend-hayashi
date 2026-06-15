"""Script de diagnóstico do lançamento de vendas na Distribuidora.

Roda o navegador VISÍVEL e despeja tudo que precisamos para entender por que
o save não persiste: estrutura do modal, estado dos campos e resposta de rede.

Uso (a partir de backend-hayashi/):
    python debug_venda.py
"""
import asyncio
import json
import os

from services.scraping import IFrutiScraper
from services.sheets import get_aba_venda_atual, get_vendas_nao_importadas


SEP = "=" * 70
# HEADED=1 abre janela visível e espera ENTER no fim (uso manual).
# Sem HEADED roda headless e termina sozinho (uso automático/diagnóstico).
HEADED = os.environ.get("HEADED") == "1"


async def main():
    aba = get_aba_venda_atual()
    print(f"\n{SEP}\nABA DO DIA: {aba}\n{SEP}")

    vendas = get_vendas_nao_importadas(aba)
    print(f"Vendas pendentes encontradas: {len(vendas)}")
    if not vendas:
        print("Nada pendente — limpe a coluna IFRUTI_ID de uma linha para testar.")
        return

    venda = vendas[0]
    item = venda["itens"][0]
    print(f"Vai testar: cliente={venda['cliente']!r}  "
          f"produto={item['produto']!r}  qtd={item['quantidade']}")

    async with IFrutiScraper(
        headless=not HEADED, slow_mo=300 if HEADED else 0, debug=True
    ) as scraper:
        page = scraper._page
        print(f"\n{SEP}\nLOGIN OK — navegando para Distribuidora\n{SEP}")
        await scraper._navegar_distribuidora()
        print("Distribuidora aberta. #btnNovaCompra presente.")

        # ── 1. Estado ANTES de clicar em + Vender ──────────────────────────
        antes = await page.evaluate("""() => ({
            modais_no_dom: document.querySelectorAll('.modal').length,
            modais_abertos: document.querySelectorAll('.modal.in, .modal.show').length,
        })""")
        print(f"\nAntes do clique: {antes}")

        # ── 2. Clica em + Vender ───────────────────────────────────────────
        await scraper._limpar_modais()
        scraper.page_logs.clear()
        await page.click("#btnNovaCompra")
        try:
            await page.wait_for_selector(".modal.in", state="visible", timeout=8000)
            print("\n>>> Modal .modal.in APARECEU após clicar em + Vender")
        except Exception as e:
            print(f"\n>>> Modal .modal.in NÃO apareceu: {e}")

        await page.wait_for_timeout(600)

        # ── 3. Despeja estrutura do modal ──────────────────────────────────
        estrutura = await page.evaluate("""() => {
            const modal = document.querySelector('.modal.in') || document.querySelector('.modal.show');
            if (!modal) return { erro: 'nenhum modal aberto' };
            const sels = Array.from(modal.querySelectorAll('select')).map(s => ({
                id: s.id, name: s.name, nOpts: s.options.length,
                visivel: !!(s.offsetParent),
                primeiras: Array.from(s.options).slice(0, 3).map(o => o.text.trim()),
            }));
            const inputs = Array.from(modal.querySelectorAll('input')).map(i => ({
                id: i.id, name: i.name, type: i.type, visivel: !!(i.offsetParent),
            }));
            const botoes = Array.from(modal.querySelectorAll('button, a.btn, input[type=button], input[type=submit]')).map(b => ({
                id: b.id, classe: b.className, texto: (b.innerText || b.value || '').trim().slice(0, 30),
            }));
            return {
                modal_id: modal.id,
                modal_classe: modal.className,
                tem_form: !!modal.querySelector('form'),
                form_action: modal.querySelector('form') ? modal.querySelector('form').action : null,
                selects: sels,
                inputs: inputs,
                botoes: botoes,
            };
        }""")
        print(f"\n{SEP}\nESTRUTURA DO MODAL:\n{SEP}")
        print(json.dumps(estrutura, indent=2, ensure_ascii=False))

        # ── 3b. Dump de TODOS os clientes do iFruti vs pendentes ───────────
        ifruti_clientes = await page.evaluate("""() => {
            const modal = document.querySelector('.modal.in');
            const sel = modal.querySelector('select[name=idEmpresa]');
            return Array.from(sel.options).filter(o => o.value && o.value !== '0')
                .map(o => o.text.trim());
        }""")
        print(f"\n{SEP}\nCLIENTES NO IFRUTI ({len(ifruti_clientes)}):\n{SEP}")
        for c in sorted(ifruti_clientes):
            print(f"  {c}")

        def _n(s):
            import unicodedata as u
            s = u.normalize("NFD", s or "")
            s = "".join(c for c in s if u.category(c) != "Mn")
            return " ".join(s.split()).upper()

        ifruti_norm = {_n(c): c for c in ifruti_clientes}
        print(f"\n{SEP}\nMATCH DOS CLIENTES PENDENTES:\n{SEP}")
        for v in vendas:
            cli = v["cliente"]
            n = _n(cli)
            exato = ifruti_norm.get(n)
            parcial = next((orig for k, orig in ifruti_norm.items()
                            if k and (k in n or n in k)), None)
            status = "EXATO" if exato else ("PARCIAL→" + parcial if parcial else "*** SEM MATCH ***")
            print(f"  {cli!r}  ->  {status}")

        # ── 4. DRY-RUN com o método REAL corrigido + cliente que existe ────
        from services.scraping import _MAPA_NORM, _normaliza
        nome_ifruti = _MAPA_NORM.get(_normaliza(item["produto"])) or item["produto"]

        cliente_teste = os.environ.get("CLIENTE_TESTE", "Alexandre")
        print(f"\n{SEP}\nDRY-RUN com método real: cliente={cliente_teste!r} "
              f"produto={nome_ifruti!r}\n{SEP}")
        try:
            res = await scraper._preencher_form_venda(
                cliente_teste, nome_ifruti, item["quantidade"], "1.00", salvar=False
            )
            print(f"RESULTADO: {res}")
        except Exception as e:
            print(f"FALHOU: {e}")

        # Dump do payload que SERIA enviado (sem clicar salvar)
        payload = await page.evaluate("""() => {
            const modal = document.querySelector('.modal.in');
            const g = sel => { const e = modal.querySelector(sel); return e ? e.value : null; };
            return {
                idEmpresa: g('select[name=idEmpresa]'),
                idProduto: g('select[name=idProduto]'),
                idProdVar: g('select[name=idProdVar]'),
                qtdeAtendido: g('#qtdeAtendido'),
                valorVenda: g('#valorVenda'),
            };
        }""")
        print(f"\nValores nos campos após dry-run (idEmpresa NÃO pode ser vazio):")
        print(json.dumps(payload, indent=2, ensure_ascii=False))

        # ── 5. SAVE REAL (apenas com SALVAR_REAL=1) ────────────────────────
        if os.environ.get("SALVAR_REAL") == "1":
            print(f"\n{SEP}\nSAVE REAL — criando venda de teste R$1,00\n{SEP}")
            await scraper._limpar_modais()
            await page.click("#btnNovaCompra")
            await page.wait_for_selector(".modal.in", state="visible", timeout=8000)
            await page.wait_for_timeout(600)

            def on_request(req):
                if req.method == "POST" and "AdminDstr" in req.url:
                    scraper.page_logs.append(f"[POST] {req.post_data}")
            page.on("request", on_request)
            scraper.page_logs.clear()

            res = await scraper._preencher_form_venda(
                cliente_teste, nome_ifruti, item["quantidade"], "1.00", salvar=True
            )
            print(f"RESULTADO _preencher: {res}")

            # Valida o helper de verificação usado na produção
            feedback = await scraper._aguardar_resultado_save()
            from services.scraping import _normaliza
            classificacao = "SUCESSO" if "SUCESSO" in _normaliza(feedback) else "ERRO/REJEITADO"
            print(f"_aguardar_resultado_save() => {feedback!r}")
            print(f">>> Classificação que a produção usaria: {classificacao}")

            for l in scraper.page_logs:
                print(l)

            estado = await page.evaluate("""() => ({
                modal_aberto: !!document.querySelector('.modal.in'),
                linhas: document.querySelectorAll('table tbody tr').length,
                alertas: Array.from(document.querySelectorAll('.alert, .swal2-popup, .toast'))
                    .map(a => a.innerText.trim()).filter(Boolean).slice(0, 5),
            })""")
            print(f"\nPÓS-SAVE: {json.dumps(estado, ensure_ascii=False)}")
            if not estado["alertas"] and not estado["modal_aberto"]:
                print(">>> SUCESSO: modal fechou sem alertas — venda registrada!")
            else:
                print(">>> Verifique os alertas acima.")

        print(f"\n{SEP}\nLOGS DE CONSOLE / REDE DURANTE O SAVE:\n{SEP}")
        for l in scraper.page_logs:
            print(l)

        # ── 5. Estado pós-save ─────────────────────────────────────────────
        pos = await page.evaluate("""() => {
            const modal = document.querySelector('.modal.in') || document.querySelector('.modal.show');
            return {
                modal_ainda_aberto: !!modal,
                linhas_tabela: document.querySelectorAll('table tbody tr').length,
                alertas: Array.from(document.querySelectorAll('.alert, .swal2-popup, .toast, .help-block'))
                    .map(a => a.innerText.trim()).filter(Boolean).slice(0, 5),
            };
        }""")
        print(f"\n{SEP}\nESTADO PÓS-SAVE:\n{SEP}")
        print(json.dumps(pos, indent=2, ensure_ascii=False))

        if HEADED:
            print(f"\n{SEP}\nInspecione a janela. Pressione ENTER aqui para fechar...\n{SEP}")
            await asyncio.get_event_loop().run_in_executor(None, input)


if __name__ == "__main__":
    asyncio.run(main())
