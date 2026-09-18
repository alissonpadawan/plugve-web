# CurVE V51.33 — Etapa 2 — Aprovação pelo Painel Local

A V51.33 amplia a autenticação criada na V51.32 com APIs administrativas para listar e administrar solicitações de acesso sem expor senhas ou códigos de confirmação.

## Site

- `GET /api/access/admin/requests`: solicitações com e-mail confirmado e `pending_approval`.
- `GET /api/access/admin/users`: listagem administrativa filtrável por status.
- `GET /api/access/admin/users/<public_id>`: identidade, estado, auditoria de autenticação e notificações.
- ações `approve`, `reject`, `suspend`, `reactivate` e `resend-notification`.
- aprovação/rejeição é persistida antes do e-mail. Falha SMTP não desfaz a decisão.
- transições de estado usam atualização condicional para evitar inconsistência em ações concorrentes.
- nova tabela `auth_notifications`, criada incrementalmente no mesmo `auth_users.sqlite3`.

## Painel Local

A V19.46 adiciona `Administração do site > Usuários e acessos`, separando solicitações pendentes, usuários ativos e rejeitados/suspensos. O Painel consulta as APIs administrativas já usadas pela arquitetura atual e nunca acessa o banco de produção pelo filesystem.

A etapa não altera telemetria para `user_id`, snapshots S/D/F ou patrimônio de curvas. Esses pontos pertencem à Etapa 3.
