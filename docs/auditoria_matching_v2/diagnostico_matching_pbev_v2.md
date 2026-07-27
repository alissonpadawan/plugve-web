# CurVE V45 — Diagnóstico e arquitetura do Motor PBEV V2

Data da validação: 26/07/2026

## Objetivo

Substituir a dependência excessiva do motor antigo em tokens classificados precocemente como família ou identificador forte. O Motor V2 relaciona a entrada FIPE com a base PBEV/Inmetro por uma combinação determinística de normalização automotiva profunda, identidade técnica, recuperação ampla, similaridade textual e bloqueios por contradição real.

O motor não cria uma tabela manual FIPE → PBEV, não consulta serviços externos e não contém condições por modelo específico.

## Problemas observados no motor anterior

Os relatórios reais mostraram padrões recorrentes:

- tokens técnicos tratados como família: `6V`, `12V`, `TB12V`;
- designações comerciais tratadas como identificadores obrigatórios: `200`, `40I`, `PRO`, `PLUS`;
- tokens colados sem segmentação adequada: `Style1.0`, `xDrive40i`;
- HEV e PHEV concorrendo no mesmo ranking;
- candidatos corretos e dominantes rebaixados por um único token ausente;
- necessidade de confirmação manual em ambiguidades que poderiam ser resolvidas automaticamente.

## Arquitetura implementada

### 1. Normalização automotiva profunda

O normalizador preserva o texto original, cria tokens canônicos e trata padrões colados/separados. Exemplos:

- `TB12V` → turbo + 12 válvulas;
- `Style1.0` → Style + 1.0;
- `xDrive40i` e `XDRIVE 40I` → formas equivalentes;
- `CLA 200` e `CLA200` → âncora alfanumérica comum;
- `SERES 3` e `SERES3` → âncora comum;
- `TIGGO 5X` e `TIGGO5X` → âncora comum.

A composição alfanumérica é controlada para não recriar falsos tokens a partir de cilindrada, válvulas, portas ou outras especificações técnicas.

### 2. Identidade técnica

Cada entrada é convertida em uma identidade estruturada contendo, quando disponíveis:

- marca;
- núcleo e âncoras de modelo;
- acabamento e designações secundárias;
- cilindrada;
- válvulas;
- turbo;
- transmissão, subtipo e número de marchas;
- tração;
- carroceria;
- combustível;
- propulsão;
- ano, MY e contexto zero km.

### 3. Restrição de propulsão antes do ranking

- lado `ve`: somente BEV e PHEV;
- lado `icev`: ICE, HEV e MHEV;
- PHEV não compete no lado ICEV;
- HEV convencional não compete no lado VE/PHEV.

### 4. Recuperação ampla de candidatos

A busca começa pelo índice de marca e usa uma pontuação de recuperação baseada em frequência inversa de tokens, âncoras de modelo, núcleo do modelo e similaridade aproximada. O conjunto final inclui os melhores candidatos e correspondências obrigatórias de modelo, evitando que o correto seja eliminado por um token secundário.

### 5. Ranking híbrido determinístico

O ranking combina:

- similaridade por conjunto de tokens;
- RapidFuzz;
- similaridade compacta;
- cosseno de trigramas de caracteres;
- sobreposição e Jaccard;
- compatibilidade técnica;
- proximidade de ano;
- margem em relação ao segundo candidato;
- qualidade e flags do registro PBEV.

### 6. Contradições técnicas

Candidatos podem ser bloqueados por incompatibilidades explícitas, entre elas:

- lado/propulsão;
- combustível;
- cilindrada;
- transmissão;
- tração;
- carroceria;
- MY;
- âncoras fortes de modelo incompatíveis;
- descritores estruturais exclusivos, como `CROSS`, quando aparecem apenas no candidato e alteram a família.

Ausência de um acabamento ou designação secundária não constitui, isoladamente, bloqueio.

### 7. Decisão automática

A confirmação manual foi removida. A decisão segue esta ordem:

1. candidato dominante e tecnicamente defensável: autofill;
2. candidatos tecnicamente equivalentes com mesmo consumo: autofill;
3. grupo tecnicamente equivalente com consumo diferente: critério conservador autorizado;
4. contradição real ou confiança insuficiente: campo manual.

Critério conservador:

- BEV/PHEV: maior kWh/km;
- ICE/flex/diesel/HEV: menor km/L.

Os campos antigos de confirmação permanecem no JSON somente como compatibilidade de contrato, sempre com `requer_confirmacao=false` e lista vazia.

## Casos reais incorporados

O conjunto novo inclui 13 regressões, entre elas:

- BYD Yuan Pro;
- Hyundai Creta TB12V;
- Hyundai HB20S Style1.0;
- Citroën C3 Live Plus 6V;
- Citroën C3 YOU Turbo 200;
- BMW X7 xDrive40i;
- Ford Fiesta Titanium Plus;
- GWM Haval H6 HEV e H6 ONE HEV;
- GWM Wey 07 PHEV;
- Jaguar XKR e XFR-S como negativos;
- Ferrari SF90 como negativo.

Resultado: 13/13 aprovados, sem confirmação manual.

## Limites honestos

O benchmark sintético e os casos reais demonstram ampla melhoria, mas não constituem prova matemática de 100% para qualquer nomenclatura futura. Entradas com informações contraditórias, ausentes ou tecnicamente indistinguíveis podem continuar manuais. A política permanece conservadora: é melhor não preencher do que aplicar consumo de outro veículo.
