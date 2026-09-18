# CurVE V51.34 — Etapa 3: usuário × telemetria

A V51.34 adiciona identidade autenticada à telemetria existente sem remover `visitor_id`/`session_id` e sem atribuir eventos legados retroativamente.

## Migrações incrementais

- `site_usage.sqlite3`: `usage_events.user_id`, `usage_sessions.user_id` e `curve_request_visitors.user_id` (nullable).
- `result_snapshots.sqlite3`: `owner_user_id` (nullable).
- Eventos/snapshots existentes permanecem `NULL`/sem proprietário.

O `user_id` gravado é o `public_id` UUID estável da conta, evitando usar e-mail como chave relacional e evitando expor a chave sequencial interna do banco de autenticação.

## Eventos identificados

Todo novo evento registrado por `record_current_usage_event` recebe automaticamente o usuário autenticado quando existir. Isso cobre page views, TCO, Depreciação, Fipe+, PDF, solicitações de curva e reabertura S/D/F. Login/logout também passam a ser eventos da timeline.

## Snapshots S/D/F

Novos snapshots recebem `owner_user_id`. O proprietário pode reabrir o próprio resultado; uma conta diferente recebe 403. O código S/D/F não funciona como credencial de compartilhamento entre usuários. Snapshots legados não são alterados nem recebem proprietário por inferência.

## Administração

A API administrativa de usuários passa a retornar resumo de atividade nas listas e, no detalhe, métricas, veículos, pares, tecnologias, cidades e timeline. O Painel Local V19.47 exibe essas informações em **Administração do site > Usuários e acessos**.
