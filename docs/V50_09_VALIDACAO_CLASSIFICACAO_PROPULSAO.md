# V50.09 — Validação da classificação VE × ICEV

## Escopo

Correção exclusiva da classificação tecnológica utilizada pelo catálogo/Simular.
Não foram alterados curvas, históricos FIPE, vínculos de similaridade, famílias,
snapshot, TCO, PBEV matching ou bases de depreciação.

## Casos Haval H6 validados

- Haval H6 1.5 AWD (Híbrido), 2024 → ICEV / HEV.
- Haval H6 ONE 1.5 (Híbrido), 2026 → ICEV / HEV.
- Haval H6 2 1.5 (Híbrido), 2026 → ICEV / HEV.
- Haval H6 HEV2 1.5 (Híbrido), 2026 → ICEV / HEV.
- Haval H6 GT 1.5 AWD (Híbrido) → VE / PHEV.
- Haval H6 PHEV19 → VE / PHEV.
- Haval H6 PHEV34 → VE / PHEV.
- Haval H6 PHEV35 → VE / PHEV.

A base PBEV local contém H6 GT em 2023, 2024, 2025 e 2026 exclusivamente
com `tipo_propulsao_normalizado = PLUG_IN`.

## Validação executada

- `compileall` dos módulos Python alterados: aprovado.
- testes V50.09 + catálogo FIPE V46: 12 aprovados.
- regressão direcionada FIPE/PBEV: 36 aprovados e 49 subtests aprovados.
- regressão ampla excluindo os quatro arquivos de dívida conhecida:
  237 aprovados, 10 ignorados e 58 subtests aprovados.
- dívidas conhecidas executadas separadamente: 29 falhas, 7 aprovados e 5 subtests;
  não houve aumento em relação ao baseline anterior.
- funções frontend alteradas extraídas do template e executadas em Node:
  H6 GT/PHEV19/PHEV35 → PHEV; H6 HEV2/ONE → híbrido não plug-in;
  `tipo_plugve` do backend é priorizado na seleção.

