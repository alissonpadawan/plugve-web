# Validação da entrega — V45 Etapa 1

## Escopo

Entrega diagnóstica. Não houve alteração em arquivos de produção do matching, endpoint ou interface.

## Resultados

- `python -m pytest -q`: **118 aprovados, 5 pulados, 2 falhas esperadas, 5 subtestes aprovados**.
- Auditoria V42 original: **20/20 casos aprovados**.
- Diagnóstico V45 normal: **20 regressões protegidas aprovadas, 1 falha conhecida, 0 regressões inesperadas**.
- Diagnóstico V45 estrito: saída `2`, conforme esperado enquanto a lacuna do Creta permanecer aberta.
- `python -m compileall -q app.py services routes scripts tests`: aprovado.
- Importação de `PbevService`: aprovada.

## Integridade da V44

Os hashes SHA-256 permaneceram idênticos ao ZIP de entrada para:

- `services/pbev_service.py`;
- `routes/pbev_routes.py`;
- `templates/simular.html`;
- `static/js/fipe.js`;
- `app.py`.

Comparação integral, ignorando `.git`, caches e bytecode:

- arquivos existentes modificados: **0**;
- arquivos existentes removidos: **0**;
- arquivos adicionados: apenas harness, casos e documentação da V45 Etapa 1.

## Validação visual

Não foi executado navegador real nesta etapa. Como nenhum template, CSS ou JavaScript de produção foi alterado, a preservação visual foi verificada por identidade de hashes dos arquivos protegidos.
