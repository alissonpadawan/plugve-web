# V46 — Pacote de teste 04

## Base e escopo

Este pacote é cumulativo e parte do **V46 pacote de teste 03**, construído sobre a V44 homologada.

A rodada 04 corrige uma regressão visual introduzida no pacote 02 e carregada pelo pacote 03: os sliders dos perfis **PHEV** e **flex** eram desativados durante a consulta oficial, mas o slider PHEV não era explicitamente reativado quando a consulta terminava. Em determinados fluxos, o controle permanecia travado mesmo depois do Inmetro responder.

## Correções

- slider PHEV acompanha o estado real da consulta: bloqueia enquanto FIPE/Inmetro processam e libera ao concluir;
- slider flex recebe a mesma proteção explícita, preservando apenas o bloqueio intencional do modo “editar somente consumos”;
- liberação ocorre também após erro, timeout, cancelamento e troca de veículo, pois todos esses fluxos encerram o estado oficial de carregamento;
- `aria-busy` e a classe visual de processamento são removidos junto com o bloqueio;
- campos de preço e consumo com participação **0%** continuam editáveis;
- participação 0% continua tornando o lado opcional no cálculo e visualmente suavizado, mas não impede preparar o valor antes de mover o slider;
- botões “Próximo/Salvar” continuam bloqueados somente durante consulta ativa ou quando faltam dados exigidos pela participação selecionada.

## Comportamento esperado

### Durante consulta FIPE/Inmetro

- slider temporariamente bloqueado;
- consumos temporariamente somente leitura;
- botão Próximo/Salvar bloqueado;
- indicação “Consultando…” visível.

### Depois da consulta

- slider volta a responder imediatamente;
- consumo volta a aceitar edição;
- 100% elétrico ainda permite editar o consumo de combustível;
- 100% combustível ainda permite editar o consumo elétrico;
- no flex, 100% etanol ou 100% gasolina não bloqueia a edição do outro consumo.

## Arquivo de produção alterado

- `templates/simular.html`.

Nenhum backend, matching, catálogo FIPE, TCO, depreciação, ANEEL ou ANP foi alterado nesta rodada.

## Testes executados

- `compileall` aprovado;
- 139 testes aprovados;
- 5 testes ignorados por ausência do Flask no ambiente de montagem;
- 54 subtestes aprovados;
- 44 de 44 casos reais do matching aprovados;
- 15 templates aprovados no parser Jinja;
- 3 scripts inline e 7 scripts estáticos aprovados no `node --check`;
- Chromium headless executou a sequência real de bloqueio/liberação dos perfis.

O teste no Chromium confirmou:

- PHEV livre antes da consulta;
- PHEV bloqueado durante a consulta;
- PHEV liberado depois da consulta;
- slider movido de 100% para 75%, atualizando para 75% elétrico / 25% combustível;
- flex livre antes da consulta;
- flex bloqueado durante a consulta;
- flex liberado depois da consulta;
- slider movido para 70% etanol / 30% gasolina;
- campos do lado com participação 0% permanecem editáveis;
- nenhuma exceção JavaScript no teste direcionado.

## Checklist no Render

1. Substituir o pacote 03 por este ZIP.
2. Fazer `Ctrl + F5` ou abrir janela anônima.
3. Selecionar um PHEV e aguardar a consulta ao Inmetro terminar.
4. Arrastar o slider de 100% elétrico para uma posição intermediária.
5. Voltar para 100% elétrico e confirmar que o consumo de combustível ainda aceita clique e edição.
6. Testar um flex, mover o slider e repetir após outra consulta FIPE/Inmetro.
7. Confirmar localização, catálogo, matching e TCO.

O pacote 04 substitui o pacote 03 como candidato atual. Ainda não é denominado pacote final.
