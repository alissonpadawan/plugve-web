# CurVE 51.32 — Etapa 1: autenticação e porta de entrada

## Escopo

Esta versão adiciona a camada de autenticação ao redor da aplicação existente sem alterar o motor TCO, FIPE, depreciação, PBEV, seguro, snapshots ou telemetria existente.

Fluxo implementado:

`cadastro -> confirmação de e-mail -> pending_approval -> login somente quando active`.

A aprovação administrativa **não faz parte da Etapa 1**. Ela será integrada ao Painel Local na Etapa 2.

## Persistência

Novo banco incremental no Persistent Disk:

`/var/data/plugve/institucional/auth_users.sqlite3`

Localmente, segue o mesmo fallback já usado pela CurVE em `data/_runtime/institucional/`.

Tabelas:

- `users`
- `auth_challenges`
- `auth_sessions`
- `auth_audit_log`
- `auth_rate_events`

A criação usa `CREATE TABLE IF NOT EXISTS`; nenhum banco existente é removido ou recriado.

## Segurança

- Senha armazenada somente por `werkzeug.security.generate_password_hash`.
- E-mail normalizado e UNIQUE.
- Código de confirmação/reset de 6 dígitos; banco guarda somente HMAC do código.
- Código com expiração, limite de tentativas, uso único e invalidação no reenvio.
- Sessão autenticada possui token aleatório; banco guarda somente SHA-256 do token.
- Estado do usuário é consultado no backend a cada requisição autenticada (com cache apenas durante a própria requisição).
- Cookies `HttpOnly`, `SameSite=Lax` e `Secure` em produção.
- Login rotaciona o estado de autenticação sem apagar `visitor_id` e `session_id` da telemetria já existente.
- Formulários sensíveis possuem CSRF.
- `next` aceita apenas caminho interno.
- Rate limit local/persistente para cadastro, login, códigos e recuperação.

## Rotas públicas de autenticação

- `/`
- `/login`
- `/solicitar-acesso`
- `/confirmar-email`
- `/reenviar-codigo`
- `/aguardando-aprovacao`
- `/esqueci-minha-senha`
- `/redefinir-senha`
- `/privacidade`
- `/termos`
- `/health`
- `/static/...`

## APIs técnicas

As integrações administrativas/sincronização que já possuem token próprio continuam fora do login de usuário final. A camada V51.32 preserva esses endpoints para que seus validadores `X-PlugVE-Admin-Token` / `X-PlugVE-Sync-Token` continuem sendo a autoridade técnica.

## Ativação da porta global

A camada está implementada, porém `AUTH_ACCESS_CONTROL_ENABLED=0` nesta Etapa 1.

Isso é proposital: ainda não existe, no Painel Local, a ação administrativa para aprovar a primeira conta. Na Etapa 2 será criado o fluxo de aprovação; depois de aprovar a conta inicial e validar o login, a variável poderá ser alterada para `1`.

Não existe bypass por IP ou máquina.

## SMTP

Autenticação reutiliza exatamente `CONTACT_SMTP_*`. Nenhuma segunda credencial SMTP foi criada.

## Versão

Marcador interno atualizado para `V51.32`, alinhando o código ao controle de versão informado pelo mantenedor.
