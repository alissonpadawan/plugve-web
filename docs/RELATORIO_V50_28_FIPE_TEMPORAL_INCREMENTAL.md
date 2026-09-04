# CurVE V50.28 — catálogo FIPE temporal incremental

Base: V50.27.

## Problema

A V50.27 corrigiu a elegibilidade temporal por modelo FIPE exato, porém passou a comprovar todos os modelos desconhecidos dentro da mesma requisição que carregava o dropdown de modelos. Em marcas com muitos modelos ICEV, isso podia disparar várias consultas `/anos` antes da resposta, aproximando-se do timeout do worker e exibindo `Erro ao carregar modelos`.

## Correção

- `/api/fipe/modelos` responde imediatamente com os modelos já temporalmente comprovados.
- Modelos desconhecidos permanecem ocultos; PBEV não os libera por similaridade.
- A comprovação dos desconhecidos é feita depois, em lotes de no máximo 2 modelos.
- Cada decisão temporal concluída é persistida individualmente assim que retorna.
- Falha/timeout/429 interrompe a atualização incremental sem apagar o progresso já salvo e sem liberar modelo sem prova FIPE.
- Simular e Depreciação atualizam o dropdown progressivamente, sem bloquear a primeira resposta.
- FIPE+ permanece com catálogo integral.
- Curvas salvas, similaridade e marcadores verde/✓ permanecem no fluxo existente.

## Benchmark controlado

Cenário sintético: 40 modelos, 80 ms por consulta de anos, 4 workers.

- comportamento equivalente à V50.27: 0,807 s para a primeira resposta, 40 consultas de anos;
- primeira resposta da V50.28: 0,001 s, 0 consultas de anos.

O benchmark mede apenas a diferença arquitetural e não representa latência real da API FIPE em produção.

## Regressão

- 369 testes aprovados;
- 29 falhas legadas preservadas;
- 10 ignorados;
- 63 subtests aprovados;
- 5 testes novos da V50.28;
- Chromium headless: fluxo incremental da Simular e Depreciação, 0 page errors / 0 console errors;
- arquivos de dados inalterados;
- `depreciacao_service.py`, `curve_marcadores_curvas.js` e `depreciacao.js` inalterados.
