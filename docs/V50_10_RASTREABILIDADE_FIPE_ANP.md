# CurVE V50.10 — Rastreabilidade por Código FIPE + fonte ANP clicável

## Escopo

Evolução construída sobre o Site V50.09, sem alterar regras de cálculo, curvas, histórico FIPE, vínculos, famílias, matching PBEV, TCO, seguro ou dados persistidos.

## Código FIPE visível

A V50.10 reforça a identidade do veículo por meio do código FIPE, de forma discreta:

- **Simular TCO**: código FIPE exibido após a seleção FIPE para carro atual, VE e ICEV; o código é enviado no POST, preservado no resultado, no relatório/PDF e na auditoria TCO.
- **Depreciação**: código FIPE exibido após a seleção, no resumo do resultado, na lista de curvas salvas e no relatório profissional/PDF.
- **Consulta Fipe+**: a tela e a impressão já exibiam o código FIPE; o comportamento foi preservado e incluído na regressão da V50.10.

O código FIPE é exclusivamente informativo/rastreável. Não participa de nenhuma nova regra de cálculo nesta versão.

## ANP clicável

As quatro ocorrências da logo ANP associadas a preços automáticos de combustível na Simular passaram a abrir, em nova guia, a página oficial do Levantamento de Preços de Combustíveis da ANP:

`https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas`

O clique na fonte foi isolado do clique do card de combustível para não abrir simultaneamente o modal de configuração.

## Arquivos alterados

- `routes/tco_routes.py`
- `static/css/app.css`
- `static/js/depreciacao.js`
- `static/js/fipe.js`
- `templates/auditoria_tco.html`
- `templates/base.html`
- `templates/depreciacao.html`
- `templates/simular.html`
- `tests/test_v43_16_aneel_anp_sources.py` (expectativa atualizada para a nova regra)
- `tests/test_v50_10_rastreabilidade_fipe_anp.py` (novo)

## Validação

- testes específicos V50.10: 5 aprovados;
- regressão ampla, excluindo somente os quatro arquivos de dívida conhecida PBEV/seguro: 242 aprovados, 10 ignorados, 58 subtests aprovados;
- quatro arquivos de dívida conhecida executados separadamente: 29 falhas conhecidas, 7 aprovados, 5 subtests aprovados — sem aumento;
- `compileall`: aprovado;
- `node --check` em `static/js/fipe.js` e `static/js/depreciacao.js`: aprovado;
- JavaScript inline da Simular renderizado via Jinja em estado sem resultado e validado por `node --check`: aprovado;
- diretório `data/`: hashes idênticos antes/depois da validação.
