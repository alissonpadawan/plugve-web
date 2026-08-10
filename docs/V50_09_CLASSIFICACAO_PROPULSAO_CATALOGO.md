# V50.09 — Classificação de propulsão no catálogo Simular

Correção restrita à separação VE × ICEV. Nenhuma curva, histórico FIPE, vínculo de similaridade, família ou regra de depreciação foi alterada.

## Problema

Algumas descrições FIPE usam apenas `(Híbrido)`, enquanto a base PBEV distingue versões HEV e PHEV da mesma família. Isso fazia famílias mistas, especialmente GWM Haval H6, cair conservadoramente em ICEV. Além disso, o padrão textual `PHEV` não reconhecia designações coladas a números, como `PHEV19`, `PHEV35` ou `PHEV404`.

## Correção

- `PHEV` seguido de número passa a ser reconhecido como plug-in.
- `HEV` seguido de número passa a ser reconhecido como híbrido não plug-in.
- Em texto híbrido genérico, evidência PBEV de melhor candidato plug-in pode resolver a classificação quando score >= 0,74 e margem contra a propulsão oposta >= 0,030.
- O frontend deixa de inferir PHEV apenas porque o veículo está no bloco VE. O `tipo_plugve` devolvido pelo backend no ano selecionado passa a ser a fonte prioritária.
- Regra de segurança/fallback do Haval H6: GT/PHEVxx = PHEV; HEV/HEV2/ONE/híbrido sem evidência plug-in = HEV.

## Resultado esperado — Haval H6

- H6 HEV / HEV2 / ONE → ICEV.
- H6 PHEV19 → VE.
- H6 PHEV34 / PHEV35 → VE.
- H6 GT → VE.

