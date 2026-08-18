# V50.20 — Correção da sincronização visual do perfil PHEV

## Diagnóstico
A correção V50.14 atualizava durante o arraste os elementos `energia_bar_eletrico` e
`energia_bar_combustivel`, mas o card compacto visível **Híbrido plug-in** usa
`phev_bar_eletrico` e `phev_bar_combustivel`. O card PHEV só era redesenhado por
`renderizarCardPhevTCO()`, que lia `phev_percent_eletrico`, valor persistido somente
após `Próximo/Salvar`. Por isso o modal mostrava 90/10 enquanto o card superior
permanecia 100/0.

## Correção
`renderizarCardPhevTCO()` aceita agora um percentual temporário (`override`). Durante
o evento `input` do slider, `atualizarEstadoModalPhevTCO()` redesenha o card compacto
PHEV com esse percentual, sem gravar o hidden persistido. Salvar persiste o valor;
cancelar restaura o estado previamente salvo.

Nenhum cálculo TCO, snapshot, dado, matching, curva ou telemetria foi alterado.
