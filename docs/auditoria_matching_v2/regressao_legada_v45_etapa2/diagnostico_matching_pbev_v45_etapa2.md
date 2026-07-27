# Matching FIPE × PBEV/Inmetro — V45 Etapa 2

## Resultado executivo

- Casos executados: **31**.
- Casos aprovados: **31**.
- Positivos localizados: **29**.
- Positivos autopreenchidos: **28**.
- Negativos preservados: **2**.
- Lacunas corrigidas nesta etapa: **4**.

## Núcleo implementado

- aliases automotivos gerais versionados em JSON;
- separação entre tokens comerciais e componentes técnicos;
- extração estruturada de cilindrada, válvulas, turbo, transmissão, marchas, tração, carroceria e MY;
- busca principal seguida de busca de resgate quando não há candidato defensável;
- nenhum candidato da marca é descartado silenciosamente pelo antigo pré-filtro;
- bloqueios duros para incompatibilidades explícitas, mantendo ausência como ausência;
- auditoria com identidade FIPE/PBEV e faixa de busca.

## Casos corrigidos

- `hyundai_creta_comfort_tb12v_zero_km`
- `toyota_hilux_srv_tdi16v`
- `ferrari_12cilindri_spider`
- `volvo_xc60_t8_ultimate_dark_my24`

## Matriz

| Caso | Estado | Nível | Autofill | Candidato |
|---|---|---|---:|---|
| `corolla_cross_xre_zero_km` | APROVADO | alto | sim | COROLLA CROSS XRE 20 |
| `song_plus_phev` | APROVADO | alto | sim | SONG PLUS GS DM |
| `hb20_hatch` | APROVADO | alto | sim | HB20 LIMITED |
| `hb20s_sedan` | APROVADO | alto | sim | HB20S LIMITED |
| `duster_intense_plus` | APROVADO | alto | sim | DUSTER DUSTER INTP MT |
| `jetour_t1` | APROVADO | alto | sim | T1 I-DM ADVANCE |
| `jetour_s06` | APROVADO | alto | sim | S06 DM ADVANCE |
| `defender_d300` | APROVADO | alto | sim | DEFENDER 110 HSE XD |
| `discovery_sport_p250` | APROVADO | alto | sim | DISCOVERY SPORT P250FF S |
| `towner_pickup` | APROVADO | alto | sim | START PICKUP L |
| `huracan_sterrato` | APROVADO | alto | sim | HURACAN TECNICA |
| `aventador_ano_distante` | APROVADO | medio | não | AVENTADOR S SV SVR |
| `durango_fallback_familia` | APROVADO | alto | sim | DURANGO LIMITED |
| `ram_2500_sem_cobertura` | APROVADO | sem_match | não | — |
| `sf90_sem_cobertura` | APROVADO | sem_match | não | — |
| `f8_spider_potencia_secundaria` | APROVADO | alto | sim | F8 SPIDER |
| `ferrari_roma_potencia_secundaria` | APROVADO | alto | sim | ROMA -- |
| `wey_07_versoes_equivalentes` | APROVADO | alto | sim | WEY 07 DARK ED. |
| `volvo_xc40_composto` | APROVADO | alto | sim | XC40 T5 INSCRIPT T5 MOMENTUM T5 R-DESIGN |
| `volvo_xc60_composto` | APROVADO | alto | sim | XC60 2.0 T5 INSCRIPTION / 2.0 T5 R-DESIGN |
| `hyundai_creta_comfort_tb12v_zero_km` | APROVADO | alto | sim | CRETA COMFORT |
| `toyota_yaris_xls_zero_km` | APROVADO | alto | sim | YARIS SEDÃ XLS (MY 2024) |
| `toyota_corolla_cross_hybrid` | APROVADO | alto | sim | COROLLA CROSS XRX HYBRID |
| `byd_dolphin_mini` | APROVADO | alto | sim | DOLPHIN MINI GS EV |
| `byd_tan_ev_4x4` | APROVADO | alto | sim | TAN AWD GS 700EV |
| `toyota_hilux_srv_tdi16v` | APROVADO | alto | sim | HILUX DIESEL 4X4 AT SRV AT |
| `peugeot_e2008_gt` | APROVADO | alto | sim | E2008 GT |
| `ferrari_12cilindri_spider` | APROVADO | alto | sim | 12CILINDRI SPI |
| `volvo_xc90_t8_ultra_dark` | APROVADO | alto | sim | XC90 T8 AWD ULTD |
| `volvo_xc60_t8_ultimate_dark_my24` | APROVADO | alto | sim | XC60 T8 ULT DARK |
| `jaecoo_7_prestige` | APROVADO | alto | sim | 7 PRESTIGE |

## Preservação

Nenhum template, JavaScript, rota de TCO, depreciação, ANP, ANEEL ou Painel Local foi alterado.
A etapa modifica apenas o núcleo PBEV, seus aliases, testes e documentação.
