# Auditoria FIPE × PBEV — V42

Validação do motor de matching do pacote 15:

- 20 casos de regressão derivados dos diagnósticos enviados: todos aprovados.
- 500 registros PBEV válidos únicos auditados em lotes: todos aprovados.
- A auditoria verifica também invariantes: cobertura técnica forte sem autofill, autofill com família divergente, ambiguidade aberta e critério conservador sem memória de cálculo.

A amostra de 500 registros usa consultas sintéticas construídas a partir da própria base PBEV. Ela valida ranking, identidade de família e autopreenchimento em registros cobertos. Não substitui uma auditoria integral de todo o catálogo FIPE.

O script `scripts/auditar_matching_pbev.py` aceita casos JSON/CSV, permite `--self-audit`, `--offset` e `--limit`, e gera relatórios JSON/CSV.
