# V46 — Matriz JavaScript do pacote de teste 04

Nenhuma função JavaScript foi removida ou renomeada.

| Função | Arquivo | Papel | Alteração 04 | Chamadas/dependências | Teste |
|---|---|---|---|---|---|
| `definirEstadoConsultaPbevTCO` | `templates/simular.html` | Atualiza o estado oficial de consulta PBEV | sem mudança de assinatura | chama `atualizarBloqueioCampoConsumoTCO` e `atualizarBloqueioPbevPerfisTCO` | pytest + Chromium |
| `reaplicarBloqueioPbevPerfisTCO` | `templates/simular.html` | Aplica bloqueio enquanto FIPE/PBEV estão ativos | slider passa a receber explicitamente `true` ou `false`; adiciona `aria-busy` | chamada ao fim das funções de estado dos perfis | pytest + Chromium |
| `atualizarBloqueioPbevPerfisTCO` | `templates/simular.html` | Libera campos e recalcula validação quando a consulta termina | sem mudança de assinatura | chama os atualizadores PHEV/flex e reaplica o bloqueio vigente | Chromium |
| `atualizarEstadoModalPhevTCO` | `templates/simular.html` | Percentuais, validação e campos PHEV | participação 0% deixa de usar `disabled` | listener do `phev_mix_slider` e inputs PHEV | pytest + Chromium |
| `atualizarEstadoModalCombustivelTCO` | `templates/simular.html` | Percentuais, validação e campos flex | participação 0% deixa de usar `disabled` | listener do `fuel_mix_slider` e inputs flex | pytest + Chromium |
| `inicializarEventosPhevTCO` | `templates/simular.html` | Registra listener do slider PHEV | não alterada | `DOMContentLoaded` | Chromium: 100 → 75 |
| `inicializarEventosCombustivelTCO` | `templates/simular.html` | Registra listener do slider flex | não alterada | `DOMContentLoaded` | Chromium: 100 → 70 |

## Estados confirmados

- consulta ativa: slider bloqueado, consumo somente leitura, botão protegido;
- consulta concluída: slider liberado, consumo editável, `aria-busy=false`;
- 0% de participação: campo opcional, visualmente suavizado e editável;
- modo flex “somente consumo”: slider permanece intencionalmente bloqueado, pois esse modo não edita a proporção.
