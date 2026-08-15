# CurVE V50.12 — recuperação histórica por código

## Objetivo

A V50.12 torna consultáveis os snapshots imutáveis criados na V50.11. O identificador `S`, `D` ou `F` passa a abrir o resultado originalmente armazenado sem chamar FIPE, ANP, ANEEL, AUTOSEG/SUSEP ou qualquer rotina de cálculo.

## Rotas públicas

- `/resultado` — campo **Consultar resultado**.
- `/resultado/<codigo>` — leitura do snapshot histórico.

O menu principal passa a oferecer o acesso **Consultar resultado**.

## Regra de imutabilidade

A recuperação executa exclusivamente `ResultSnapshotService.get_snapshot(..., verify_integrity=True)` e monta a visualização a partir do payload persistido. Não há recalculo e não há enriquecimento com dados atuais.

A página informa explicitamente:

- código do resultado;
- data/hora original;
- versão da CurVE que gerou o registro;
- tipo S/D/F;
- SHA-256 do snapshot;
- parâmetros originais preservados;
- valores/resultados preservados.

O payload integral fica disponível em seção técnica recolhida, permitindo auditoria do conteúdo congelado.

## Tipos

### S — Simulação TCO

Exibe identificação e código FIPE dos veículos, TCO preservado, custo por km, valores inicial/revenda, componentes, indicadores comparativos e memória anual quando existentes no snapshot.

### D — Depreciação

Exibe veículo, código FIPE, valor usado na consulta, valor futuro original, horizonte, depreciação, taxa anual, confiança e origem/tipo de curva que estavam armazenados.

### F — Consulta Fipe+

Exibe marca, modelo, código FIPE, valor FIPE, ano/modelo, combustível e referência exatamente como persistidos no instante da consulta.

## Segurança e privacidade

- Não existe listagem pública de snapshots.
- A página usa `noindex,nofollow`.
- O código aleatório continua sendo a chave de compartilhamento.
- Nenhum IP bruto é incorporado à visualização.
- Falha de integridade bloqueia a exibição.

## Fora do escopo desta etapa

- botão que refaz automaticamente o resultado com dados atuais;
- nomes finais dos PDFs com S/D/F;
- inclusão formal de código/data em todos os PDFs;
- PDF próprio da tela histórica;
- integração visual final dos IDs com `/admin/uso`.

Esses itens permanecem para a etapa seguinte.
