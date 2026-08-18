# CurVE V50.24 — Consistência monetária do TCO

## Convenção

A partir da V50.24, novas simulações usam **TCO acumulado em reais constantes da data-base da simulação**.
A inflação é utilizada exclusivamente para uniformizar a unidade monetária dos componentes. Não há TMA, custo de oportunidade ou VPL.

## Reconstrução das premissas históricas

Fonte: IPCA/SIDRA/IBGE, Tabela 7060, recorte Brasil. Período operacional reconstruído: **jan/2020 a dez/2025**, correspondente a seis variações anuais completas.

| Ano | IPCA geral (%) | Energia elétrica residencial (%) | Combustíveis (veículos) (%) |
|---|---:|---:|---:|
| 2020 | 4,52 | 9,14 | -0,06 |
| 2021 | 10,06 | 21,21 | 49,02 |
| 2022 | 5,79 | -19,01 | -23,87 |
| 2023 | 4,62 | 9,52 | 8,37 |
| 2024 | 4,83 | -0,37 | 10,09 |
| 2025 | 4,26 | 12,31 | 2,30 |

Identificadores estruturais usados na memória metodológica:

- energia: `2202003 — Energia elétrica residencial`;
- combustíveis: `5104 — Combustíveis (veículos)`.

Para cada série, as variações anuais foram encadeadas e convertidas em taxa anual equivalente de seis anos:

`g = [prod(1 + v_a)]^(1/6) - 1`

Resultados:

- energia nominal equivalente: **4,642787% a.a.**, reproduzindo o antigo default de **4,6%** quando arredondado a uma casa;
- combustíveis nominal equivalente: **5,563080% a.a.**, reproduzindo o antigo default de **5,6%** quando arredondado a uma casa;
- IPCA geral equivalente: **5,661132% a.a.**.

A memória textual anterior que utilizava expoente `1/5` não reproduzia os dois defaults. A reconstrução comprovou que a calibração operacional corresponde a **seis anos completos**, portanto a V50.24 registra explicitamente o expoente `1/6`.

## Conversão nominal para real

`g_real = (1 + g_nominal) / (1 + pi) - 1`

Usando as taxas equivalentes reconstruídas:

- energia: **-0,963783% a.a.**; default operacional exibido: **-0,96% a.a.**;
- combustíveis: **-0,092799% a.a.**; default operacional exibido: **-0,09% a.a.**.

Valores negativos são preservados. Eles indicam queda do preço relativo frente à inflação geral no período de calibração.

## Componentes do TCO

- **Depreciação/valor residual:** motor inalterado; trajetória relativa aplicada à FIPE da data-base, sem inflação futura adicional.
- **Energia:** preço da data-base no Ano 1 e variação real anual a partir do Ano 2.
- **Gasolina/etanol/diesel:** mesma variação real agregada de combustíveis, preservando a regra existente.
- **PHEV:** parcela elétrica usa a variação real da energia; parcela térmica usa a variação real dos combustíveis.
- **Flex:** gasolina e etanol mantêm o perfil configurado e usam a mesma variação real de combustíveis.
- **Manutenção:** valor anual constante em reais da data-base.
- **IPVA:** percentual sobre a trajetória projetada do valor do veículo, sem inflação geral adicional.
- **Seguro V2:** metodologia preservada; reestimativa anual sobre a trajetória do valor do veículo. Seguro manual preserva a regra existente de taxa relativa à FIPE, coerente com a trajetória em reais constantes.
- **Financiamento:** o contrato Price continua nominal. Principal, parcela, saldo, amortização e juros contratuais não são modificados. Somente os juros incorporados ao TCO são deflacionados mês a mês para reais da data-base.

## Financiamento em reais da data-base

A inflação geral anual equivalente é convertida para equivalente mensal:

`pi_m = (1 + pi)^(1/12) - 1`

Para a parcela que ocorre no mês `m`:

`J_real,m = J_nominal,m / (1 + pi_m)^m`

A primeira parcela é tratada como mês 1. O TCO soma os juros reais apenas até o limite do horizonte escolhido, preservando a regra anterior.

## Snapshots S

Novas simulações congelam a convenção monetária, data-base, inflação de referência, período de calibração, taxas nominais de origem, taxas reais utilizadas e memória anual corrigida. Snapshots históricos anteriores à V50.24 permanecem imutáveis, não são recalculados e continuam sendo apresentados com os rótulos monetários da metodologia registrada naquele resultado, sem atribuição retroativa da convenção em reais constantes. O estado temporário do formulário também recebeu nova chave de versão para não reinterpretar como reais taxas nominais remanescentes de uma sessão anterior ao deploy.

## Backlog não alterado

A reavaliação anual de regras de isenção de IPVA por envelhecimento do veículo permanece pendência separada. A V50.24 não modifica regras tributárias estaduais.
