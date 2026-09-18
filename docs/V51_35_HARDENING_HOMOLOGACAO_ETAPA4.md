# CurVE V51.35 — Hardening e homologação da autenticação (Etapa 4)

## Base e escopo

A V51.35 consolida as Etapas 1–3 do acesso controlado e executa o hardening final da camada de autenticação. A alteração permanece ao redor da aplicação CurVE: não redesenha TCO, FIPE+, Depreciação, PBEV, Seguro, ANP/ANEEL, PDFs ou o conteúdo dos snapshots.

Esta etapa fecha a porta global em produção e reforça autorização, sessão, migração, cache e superfícies administrativas/técnicas.

## Alterações V51.35

- `CURVE_VERSION = "V51.35"`.
- `AUTH_ACCESS_CONTROL_ENABLED` passa a falhar para o lado seguro em produção: se a variável não for explicitada no Render, o padrão de produção é ligado. O `render.yaml` e `.env.example` usam `1`.
- Rotas públicas ficam restritas à landing, health e fluxo de autenticação necessário.
- Rotas técnicas Painel → site continuam fora do login de usuário final e mantêm a autenticação técnica própria.
- APIs funcionais protegidas retornam `401` quando falta autenticação e `403` quando existe conta autenticada sem status ativo.
- O status da conta é consultado no backend em cada requisição protegida; suspensão/rejeição/desativação têm efeito na requisição seguinte.
- `next` aceita somente caminho interno e rejeita formas codificadas de `//`, barra invertida e CR/LF.
- Login e recuperação de senha têm limite tanto por cliente quanto por cliente+e-mail.
- A tela `aguardando aprovação` reconcilia status real da conta antes de renderizar.
- Respostas dinâmicas autenticadas usam `Cache-Control: private, no-store`, `Pragma: no-cache` e `Vary: Cookie`.
- Cabeçalhos adicionais: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`; HSTS em HTTPS.
- Chamadas técnicas administrativas não recebem cookie/visitor de telemetria por efeito do `before_request`.
- Migrações de `site_usage.sqlite3` e `result_snapshots.sqlite3` criam backup SQLite consistente antes do primeiro `ALTER TABLE`, quando necessário, e executam `PRAGMA quick_check`.
- Backups de migração são idempotentes em `migration_backups/` e não se multiplicam a cada restart/deploy.
- Eventos e snapshots legados mantêm `user_id`/`owner_user_id = NULL`; nenhuma identidade antiga é inferida.

## Backups automáticos de migração

Quando um banco legado efetivamente precisar das colunas das Etapas 3/4, a aplicação cria uma cópia consistente antes de migrar:

- `migration_backups/site_usage_pre_v51_35_usage_schema.sqlite3`
- `migration_backups/result_snapshots_pre_v51_35_snapshot_owner.sqlite3`

Bancos já migrados não geram cópias novas desnecessárias.

## Autorização final

### Público

- `/`
- `/health`
- login
- solicitar acesso
- confirmar/reenviar código
- aguardando aprovação
- recuperação/redefinição de senha
- privacidade e termos
- arquivos estáticos necessários

A rota `/` apresenta landing mínima a visitante quando o acesso controlado está ligado; usuário ativo recebe a Home completa.

### Usuário ativo

As funções CurVE (Simular, FIPE+, Depreciação, resultados, PDFs e demais recursos funcionais) exigem conta autenticada e `active` no backend.

### Integrações técnicas

As rotas administrativas/sincronização utilizadas pelo Painel Local continuam usando os mecanismos técnicos já existentes. A camada de login do usuário final não é colocada sobre essas rotas.

## Sessão e suspensão

A sessão do navegador guarda identificador opaco da sessão autenticada. O usuário e o `access_status` atuais são recuperados do banco no backend. Assim, uma conta suspensa enquanto está logada perde acesso na próxima requisição protegida.

Logout revoga a sessão no banco. Redefinição de senha revoga as sessões existentes.

## S/D/F

- snapshot novo com `owner_user_id`: somente o proprietário ativo pode reabrir pela interface comum;
- outro usuário comum recebe acesso negado;
- snapshot legado permanece com proprietário nulo e seu payload histórico não é alterado;
- a recuperação continua sendo leitura do snapshot, sem recálculo.

## Validações executadas

- compilação Python completa: OK;
- templates Jinja: 28/28 analisados sem erro sintático;
- hardening V51.35: 12/12 testes específicos passaram;
- testes direcionados Etapas 2–4: 20/20 passaram;
- migração real simulada a partir de bancos V51.33: backups criados, `quick_check = ok`, identidade legada mantida nula;
- reaplicação da inicialização: nenhum novo backup duplicado;
- suíte total: 410 passaram, 35 falharam, 12 ignorados, 63 subtestes passaram;
- o conjunto nominal das falhas é idêntico ao baseline V51.34 (falhas históricas PBEV/V50.27 já existentes antes da Etapa 4);
- `data/`: 109 arquivos, 0 alterações durante a Etapa 4;
- compatibilidade do Painel V19.47: 6/6 testes direcionados das Etapas 2–3 passaram e compilação OK.

## Painel Local

Nenhuma alteração de código adicional foi necessária no Painel para a Etapa 4. A V19.47 já usa as APIs administrativas técnicas e permanece compatível com a porta global do site. Portanto não é criada uma V19.48 sem necessidade técnica.

## Publicação / smoke test em produção

1. Publicar o ZIP completo V51.35 preservando o Persistent Disk existente.
2. Confirmar que o ambiente de produção possui `SECRET_KEY` e as configurações já utilizadas pela CurVE.
3. Manter `AUTH_ACCESS_CONTROL_ENABLED=1`.
4. Conferir `/health`.
5. Em navegador anônimo: abrir `/simular` e confirmar redirecionamento para login.
6. Confirmar que `/` mostra a landing pública mínima.
7. Testar conta `email_pending`, `pending_approval`, `active`, `rejected` e `suspended`.
8. Com usuário ativo e logado, suspender pelo Painel e confirmar bloqueio na próxima requisição.
9. Testar logout e login posterior.
10. Testar redefinição de senha e confirmar que sessão anterior não permanece válida.
11. Criar um resultado S/D/F com usuário A e confirmar que usuário B não consegue abri-lo pelo código.
12. Confirmar que um snapshot legado ainda abre dentro do ambiente autenticado sem modificação do payload.
13. Confirmar no Painel que aprovação/telemetria continuam acessíveis pelas APIs administrativas.
14. Confirmar sincronização técnica Painel → site.
15. Fazer smoke de Simular, FIPE+, Depreciação e exportação PDF em desktop e viewport mobile.

## Limitação de homologação local

O ambiente de validação utilizado para a V51.35 não possui a stack Flask/Werkzeug completa para executar um navegador real contra o servidor. A lógica, schemas, templates e regressões foram testados estaticamente e por testes independentes. O smoke de navegador/Render descrito acima permanece como etapa operacional de publicação antes de considerar a versão homologada em produção.
