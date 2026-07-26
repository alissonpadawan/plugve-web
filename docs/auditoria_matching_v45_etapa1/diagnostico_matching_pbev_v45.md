# Diagnóstico do matching FIPE × PBEV/Inmetro — V45 Etapa 1

## Escopo congelado

Esta etapa adiciona somente casos de regressão, ferramenta de diagnóstico e documentação.
Nenhum arquivo de produção do motor, endpoint ou interface foi alterado.

## Resultado executivo

- Site-base: **V44.3**.
- Casos executados: **21**.
- Regressões protegidas aprovadas: **20**.
- Falhas conhecidas reproduzidas: **1**.
- Regressões inesperadas: **0**.
- Contratos de localização/ausência atendidos: **21**.
- Candidatos positivos localizados: **19**.
- Ausências negativas preservadas: **2**.

## Matriz resumida

| Caso | Estado | Contrato localização/ausência | Nível atual | Autofill | Candidato |
|---|---|---:|---|---:|---|
| `corolla_cross_xre_zero_km` | APROVADO | sim | alto | sim | COROLLA CROSS XRE 20 |
| `song_plus_phev` | APROVADO | sim | alto | sim | SONG PLUS PREM DM |
| `hb20_hatch` | APROVADO | sim | alto | sim | HB20 LIMITED |
| `hb20s_sedan` | APROVADO | sim | alto | sim | HB20S LIMITED |
| `duster_intense_plus` | APROVADO | sim | alto | sim | DUSTER DUSTER INTP MT |
| `jetour_t1` | APROVADO | sim | alto | sim | T1 I-DM ADVANCE |
| `jetour_s06` | APROVADO | sim | alto | sim | S06 DM ADVANCE |
| `defender_d300` | APROVADO | sim | alto | sim | DEFENDER 110 HSE |
| `discovery_sport_p250` | APROVADO | sim | alto | sim | DISCOVERY SPORT P250FF SERD7 |
| `towner_pickup` | APROVADO | sim | alto | sim | START PICKUP L |
| `huracan_sterrato` | APROVADO | sim | alto | sim | HURACAN TECNICA |
| `aventador_ano_distante` | APROVADO | sim | medio | não | AVENTADOR |
| `durango_fallback_familia` | APROVADO | sim | alto | sim | DURANGO LIMITED |
| `ram_2500_sem_cobertura` | APROVADO | sim | sem_match | não | — |
| `sf90_sem_cobertura` | APROVADO | sim | sem_match | não | — |
| `f8_spider_potencia_secundaria` | APROVADO | sim | alto | sim | F8 SPIDER |
| `ferrari_roma_potencia_secundaria` | APROVADO | sim | alto | sim | ROMA -- |
| `wey_07_versoes_equivalentes` | APROVADO | sim | alto | sim | WEY 07 |
| `volvo_xc40_composto` | APROVADO | sim | alto | sim | XC40 T5 INSCRIPT T5 MOMENTUM T5 R-DESIGN |
| `volvo_xc60_composto` | APROVADO | sim | alto | sim | XC60 2.0 T5 INSCRIPTION / 2.0 T5 R-DESIGN |
| `hyundai_creta_comfort_tb12v_zero_km` | FALHA_CONHECIDA | sim | medio | não | CRETA COMFORT |

## Lacunas e regressões

### hyundai_creta_comfort_tb12v_zero_km

- Estado: **FALHA_CONHECIDA**.
- Classificação: normalizacao_token_tecnico, classificacao_token_forte, resolucao_equivalencia_consumo, efeito_interface_campo_manual.
- Candidato localizado: **sim**.
- Resultado atual: `medio`, autofill `False`.
- Candidato atual: **CRETA COMFORT**.
- Score bruto: **118.0**.
- Tokens fortes FIPE: `TB12V`.
- Identidade técnica forte: **não**.
- Técnica suficiente para consumo: **não**.
- Erros contra a meta V45: nivel_match: esperado='alto', obtido='medio', autopreencher: esperado=True, obtido=False, criterio_match: esperado='versoes_equivalentes', obtido='exato'.

## Diagnóstico específico — Hyundai Creta Comfort 1.0 TB 12V

O registro correto está presente e foi localizado como `PBEV-2026-0386`.
A entrada FIPE e o candidato PBEV coincidem em marca, família, acabamento, ano,
cilindrada, válvulas, turbo, combustível e transmissão.

A falha reproduzida ocorre porque o extrator atual forma `TB12V` como token forte
de identidade comercial. O PBEV registra o mesmo conjunto técnico como `12V T`,
portanto o token artificial fica ausente no candidato e rebaixa a identidade técnica.

Os dois candidatos líderes possuem a mesma sugestão de consumo, mas a resolução por
consumo não é acionada porque ambos chegam à etapa de ambiguidade com identidade técnica
marcada como insuficiente. O backend retorna `medio` e `autopreencher=false`, embora o
candidato correto esteja localizado.

### Contrato esperado para a próxima etapa

- `TB`, `T` e `TURBO` devem ser comparados como característica técnica contextual.
- `12V` deve continuar sendo assinatura de válvulas, não identificador comercial.
- `TB12V` não pode ser criado como token forte de família/modelo.
- Candidatos tecnicamente equivalentes e com consumo idêntico podem formar grupo equivalente.
- O resultado esperado é match alto, editável e com procedência Inmetro.

## Próxima etapa recomendada

Implementar o núcleo geral em módulos separados: normalização contextual, extração de identidade
técnica, geração ampla de candidatos, restrições duras, score explicável e resolução de equivalentes.
O arquivo `services/pbev_service.py` só deve ser alterado na Etapa 2, mantendo este harness como
critério de aceitação.

## Comandos

```bash
python scripts/diagnosticar_matching_pbev_v45.py
python scripts/diagnosticar_matching_pbev_v45.py --strict-target
python -m pytest -q
```

O modo normal falha apenas diante de regressões inesperadas. O modo `--strict-target` também
retorna erro enquanto qualquer lacuna conhecida da meta V45 continuar aberta.
