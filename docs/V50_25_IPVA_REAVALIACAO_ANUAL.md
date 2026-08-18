# CurVE V50.25 — Reavaliação anual do IPVA no TCO

## Escopo

A V50.25 corrige exclusivamente a projeção anual do IPVA no TCO. A base é a V50.24 homologada, que permanece responsável pela convenção monetária em reais constantes da data-base.

O objetivo é reaplicar, em cada ano do horizonte, as regras já cadastradas no `IpvaService` ao estado projetado do veículo, sem copiar regras estaduais para `tco_routes.py` e sem presumir alterações legislativas futuras.

## Problema anterior

Até a V50.24, o TCO obtinha um IPVA inicial e derivava uma taxa efetiva aproximada por `ipva_inicial / valor_fipe_inicial`. Nos anos seguintes, essa taxa era aplicada ao valor projetado do veículo. O valor monetário variava, mas a elegibilidade tributária inicial podia ficar congelada.

Como consequência, um veículo que atingisse durante o horizonte uma condição de isenção por idade cadastrada no motor poderia continuar pagando IPVA no TCO.

## Solução

Para cada ano `t`, o TCO agora:

1. determina o exercício projetado a partir da data-base da simulação;
2. utiliza o valor projetado `V_t` já fornecido pela trajetória de depreciação;
3. mantém os atributos relevantes do veículo (UF, ano-modelo, combustível, tecnologia e demais metadados disponíveis);
4. chama novamente o mesmo `IpvaService` já utilizado pela aplicação;
5. registra alíquota/regra, idade projetada, incidência/isenção e IPVA efetivamente utilizado no ano;
6. soma esse mesmo `IPVA_t` à memória anual e ao TCO.

A regra pode ser representada por:

`IPVA_t = Z_t × taxa_t × V_t`

em que `Z_t` é reavaliado pelo motor tributário cadastrado para o estado projetado do veículo naquele período.

## Convenção temporal

O ano do primeiro período é o ano da data-base da simulação. A idade continua sendo calculada pelo `IpvaService` a partir do ano-modelo e do exercício projetado; não foi criada uma regra paralela `idade_inicial + t` no TCO.

## Regras futuras

A projeção reaplica as regras cadastradas na data-base. A CurVE não presume mudanças legislativas futuras ainda desconhecidas.

## IPVA manual

Quando o usuário informa manualmente um IPVA, a intenção existente é preservada pela taxa efetiva inicial para os períodos tributáveis. A elegibilidade anual ainda é consultada no `IpvaService`, permitindo que uma isenção por idade já cadastrada passe a valer quando o veículo atingir a condição.

Uma exclusão/isenção manual explícita permanece zero conforme a escolha do usuário.

## Integração tecnológica

A auditoria revelou que a consulta inicial da interface à rota `/ipva_estimado` nem sempre enviava `tipo_propulsao`, embora o endpoint e o `IpvaService` já aceitassem esse dado. Isso podia fazer HEV/PHEV serem interpretados apenas pelo combustível textual em UFs com regra tecnológica específica.

A V50.25 passa a enviar o tipo de propulsão já conhecido pela Simular. Não foi criada nem alterada qualquer alíquota estadual; apenas foi entregue ao mesmo motor um atributo que ele já suporta e utiliza.

## Preservações

Não foram alterados:

- `services/ipva_service.py`;
- motor de depreciação e valor residual;
- Seguro V2;
- energia/combustíveis em reais constantes da V50.24;
- Sistema Price e deflação dos juros;
- D/F;
- Painel Local;
- regras estaduais cadastradas.

## Snapshots

Novas simulações S armazenam a memória anual de IPVA e o metadado de metodologia `IPVA_ANUAL_V1` junto ao resultado/auditoria já congelados.

Snapshots antigos continuam sendo reabertos a partir do conteúdo salvo e não são recalculados.

## Casos de referência antes × depois

### Caso 1 — condição tributária não muda

SP, veículo ano-modelo 2020, valor inicial de R$ 100.000, trajetória de -10% a.a., horizonte de 5 anos:

| Ano | IPVA V50.24 | IPVA V50.25 |
|---|---:|---:|
| 1 | R$ 4.000,00 | R$ 4.000,00 |
| 2 | R$ 3.600,00 | R$ 3.600,00 |
| 3 | R$ 3.240,00 | R$ 3.240,00 |
| 4 | R$ 2.916,00 | R$ 2.916,00 |
| 5 | R$ 2.624,40 | R$ 2.624,40 |

TCO de referência: R$ 57.331,40 nas duas versões.

### Caso 2 — isenção por idade surge no horizonte

GO, veículo ano-modelo 2012, valor inicial de R$ 100.000, trajetória de -10% a.a., data-base 2026, horizonte de 5 anos. O limite de 15 anos utilizado abaixo já existe no `IpvaService` do pacote e não foi criado nesta versão.

| Exercício | Idade | IPVA V50.24 | IPVA V50.25 | Motivo |
|---|---:|---:|---:|---|
| 2026 | 14 | R$ 3.750,00 | R$ 3.750,00 | ainda tributado |
| 2027 | 15 | R$ 3.375,00 | R$ 0,00 | condição de isenção cadastrada atingida |
| 2028 | 16 | R$ 3.037,50 | R$ 0,00 | permanece isento |
| 2029 | 17 | R$ 2.733,75 | R$ 0,00 | permanece isento |
| 2030 | 18 | R$ 2.460,38 | R$ 0,00 | permanece isento |

TCO de referência:

- V50.24: R$ 56.307,63
- V50.25: R$ 44.701,00
- diferença: -R$ 11.606,63

A diferença é exatamente a soma do IPVA que deixa de ser cobrado após a entrada na condição de isenção nesse caso controlado.

## Backlog — não alterado

A V50.25 não verifica a atualidade jurídica de cada regra estadual cadastrada. Uma revisão jurídica/tributária integral por UF permanece um trabalho separado. Esta versão apenas reaplica corretamente, ano a ano, as regras que já estão no motor.
