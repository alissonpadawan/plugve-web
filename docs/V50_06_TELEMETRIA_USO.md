# V50.06 — Telemetria de uso da plataforma CurVE

## Objetivo

Preparar a base persistente para o painel administrativo de tendências sem criar um segundo banco. A telemetria usa `site_usage.sqlite3`, já persistido no diretório institucional da aplicação.

## Identidade pseudonimizada

- `visitor_hash`: derivado de um identificador aleatório persistido na sessão do navegador.
- `session_hash`: sessão operacional renovada após 30 minutos de inatividade.
- `network_hash`: HMAC-SHA256 do endereço de rede usando a chave da aplicação. O IP bruto não é persistido.
- localização de acesso: cidade/região/país somente quando a infraestrutura/proxy já fornece cabeçalhos geográficos; pode ficar vazia.
- cidade/UF da simulação: armazenadas separadamente, pois são parâmetros escolhidos pelo usuário e não localização inferida do acesso.

## Eventos principais

- `page_view`: abertura das páginas principais.
- `tco / simulation_completed`: simulação concluída, com veículos, cenário, horizonte, km/ano e localização da simulação.
- `depreciacao / consultation_completed`: consulta de depreciação concluída, com veículo e metadados de curva.
- `fipe_plus / consultation_completed`: consulta FIPE concluída, com veículo consultado.
- `pdf_exported`: exportação acionada em TCO, Depreciação ou Fipe+.
- `curve_requested`: pedido de curva ausente, preservando o mecanismo já existente.

## Novas tabelas

- `usage_visitors`
- `usage_sessions`
- `usage_events`
- `usage_event_vehicles`

As tabelas antigas `analysis_counts`, `curve_requests` e `curve_request_visitors` são preservadas para compatibilidade.

## Leitura administrativa preparada para a Etapa 4

Rotas autenticadas:

- `GET /api/site-usage/admin/telemetry/summary`
- `GET /api/site-usage/admin/telemetry/events`
- `GET /api/site-usage/admin/telemetry/visitors`

Os filtros `start`, `end`, `module`, `visitor`, `offset` e `limit` já permitem construir o dashboard posterior. O resumo também fornece veículos mais consultados, pares mais comparados e cidades escolhidas nas simulações.

## Migração

A inicialização usa `CREATE TABLE IF NOT EXISTS`, portanto bancos existentes são ampliados sem apagar contagens e solicitações anteriores.
