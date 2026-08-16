# CurVE V50.17 — Consolidação da telemetria e do painel administrativo

## Objetivo

A V50.17 fecha a rodada V50.14–V50.16 com uma auditoria de consistência da telemetria e do `/admin/uso`, sem alterar os cálculos da CurVE.

## Correções de consistência

### Contexto histórico por evento

Até a V50.16, cidade/UF aproximadas, hash de rede e ambiente técnico eram lidos da sessão ao montar a visualização administrativa. Isso era suficiente na maior parte dos casos, mas permitia que um evento antigo refletisse contexto atualizado posteriormente dentro da mesma sessão.

A V50.17 congela no próprio `usage_events` o contexto coarse existente no instante do evento:

- hash de rede pseudonimizado;
- cidade, UF/região e país aproximados;
- navegador;
- classe do dispositivo;
- sistema operacional.

Bancos existentes são migrados de forma compatível. Eventos legados recebem como ponto de partida o contexto já associado à sessão no momento da migração. IP bruto continua não sendo armazenado.

### Código S/D/F em coluna própria

O `resultado_codigo` passa a ter coluna indexada `result_code` em `usage_events`, mantendo o `metadata_json` por compatibilidade. Isso melhora a filtragem administrativa e permite idempotência dos eventos que representam criação de resultados.

### Proteção contra duplicidade acidental

Para os eventos de conclusão que possuem snapshot único:

- TCO `simulation_completed`;
- Depreciação `consultation_completed`;
- Fipe+ `consultation_completed`;

o mesmo código S/D/F não é contabilizado duas vezes se a mesma chamada for reenviada acidentalmente.

Ações legitimamente repetíveis continuam sendo contadas individualmente, como exportar PDF ou reabrir um resultado histórico.

## Mobile

As tabelas de visitantes e de Atividades/Pesquisas passam a assumir formato de cards em telas estreitas, evitando que a consulta administrativa dependa de rolagem horizontal para leitura básica. O modal de detalhe mantém layout de uma coluna no mobile.

## Índices

Foram adicionados índices para código de resultado, localização de acesso, marca, tecnologia e Código FIPE, reduzindo o custo das consultas do painel conforme a base de telemetria crescer.

## Escopo preservado

A V50.17 não altera:

- TCO;
- FIPE;
- Depreciação;
- seguro;
- matching PBEV;
- snapshots S/D/F;
- PDFs;
- curvas ou vínculos;
- arquivos em `data/`.
