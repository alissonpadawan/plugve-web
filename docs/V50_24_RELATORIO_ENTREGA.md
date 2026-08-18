# CurVE V50.24 — Relatório de entrega
## Base e escopo
- Base homologada: **Site V50.23**.
- Nova versão: **V50.24**.
- Escopo: correção exclusiva da consistência monetária do TCO para **reais constantes da data-base da simulação**, sem TMA/VPL.
- Painel Local, motor de depreciação, Seguro V2, regras estaduais de IPVA e demais pendências não foram alterados.
## Calibração monetária
| Série | Taxa nominal equivalente | IPCA geral equivalente | Taxa real calculada | Default operacional |
|---|---:|---:|---:|---:|
| Energia elétrica residencial | 4,642787% | 5,661132% | -0,963783% | -0,96% |
| Combustíveis (veículos) | 5,563080% | 5,661132% | -0,092799% | -0,09% |

Período: jan/2020 a dez/2025, Brasil, seis variações anuais completas. A memória antiga com expoente `1/5` não reproduzia os defaults de 4,6% e 5,6%; a reconstrução correta usa o produto dos seis fatores anuais e expoente `1/6`.
## Comparação V50.23 × V50.24
| Caso | TCO anterior | TCO corrigido | Diferença | Principal causa |
|---|---:|---:|---:|---|
| BEV × ICEV · 3 anos · sem financiamento — BEV | R$ 59.539,46 | R$ 59.154,55 | R$ -384,92 | energia/combustível em taxa real |
| BEV × ICEV · 3 anos · sem financiamento — ICEV | R$ 83.064,30 | R$ 81.717,08 | R$ -1.347,22 | energia/combustível em taxa real |
| PHEV × HEV · 5 anos · sem financiamento — PHEV | R$ 133.722,51 | R$ 131.289,10 | R$ -2.433,41 | energia/combustível em taxa real |
| PHEV × HEV · 5 anos · sem financiamento — HEV | R$ 137.313,72 | R$ 134.207,32 | R$ -3.106,41 | energia/combustível em taxa real |
| Flex · 5 anos · sem financiamento — Flex | R$ 115.975,29 | R$ 111.364,31 | R$ -4.610,98 | energia/combustível em taxa real |
| Diesel · 7 anos · sem financiamento — Diesel | R$ 307.520,25 | R$ 295.328,05 | R$ -12.192,19 | energia/combustível em taxa real |
| BEV × ICEV · 5 anos · com financiamento — BEV | R$ 134.098,42 | R$ 128.831,10 | R$ -5.267,32 | energia/combustível em taxa real + juros deflacionados |
| BEV × ICEV · 5 anos · com financiamento — ICEV | R$ 172.939,72 | R$ 164.327,75 | R$ -8.611,97 | energia/combustível em taxa real + juros deflacionados |

Nos cenários determinísticos, depreciação, IPVA, seguro e manutenção permaneceram numericamente iguais. As diferenças vieram exclusivamente dos componentes monetariamente corrigidos: energia/combustíveis e, quando presente, juros do financiamento.
## Financiamento
O contrato Price permanece nominal. Em cenário de 60 meses com principal de R$ 80.000 e taxa de 1,5% a.m., os juros contratuais permaneceram em **R$ 41.888,45 nominais**; após a conversão mês a mês para a data-base, o valor incorporado ao TCO foi **R$ 37.936,09**. A primeira parcela é tratada no mês 1.
## Testes finais
- `compileall`: aprovado.
- Testes direcionados TCO/Price/Seguro/IPVA/snapshot/PDF/auditoria: **81/81 aprovados**.
- Regressão geral: **335 aprovados, 29 falhas, 10 ignorados e 63 subtests aprovados**.
- As 29 falhas são as mesmas da V50.23 (matching PBEV legado V45/V2 e seguro externo V47); não houve nova falha.
- Jinja: templates alterados parseados com sucesso.
- JavaScript: 3 blocos inline aprovados em `node --check`.
- Chromium headless sobre o trecho JS alterado: defaults reais, edição manual preservada, **0 page errors / 0 console errors**.
- Aplicação Flask completa: não iniciada neste ambiente por ausência de Flask/gunicorn; isso é limitação do ambiente, não resultado de teste do pacote.
- Dados monitorados: **107 arquivos, 0 alterações** após os testes.
## Snapshots
Novas simulações S congelam a convenção monetária, data-base, inflação geral equivalente, taxas nominais de origem, taxas reais utilizadas, memória anual e juros nominais/reais. A recuperação histórica existente não foi alterada; snapshots anteriores permanecem sem recálculo e são exibidos com os rótulos da metodologia histórica, sem atribuição retroativa de “reais constantes”. A chave do estado temporário do formulário foi versionada para impedir que 4,6%/5,6% nominais de uma sessão antiga sejam interpretados como taxas reais após o deploy.
## Backlog — não alterado
- Reavaliação anual das regras de isenção de IPVA por envelhecimento do veículo. É pendência distinta e ficou fora desta correção.
