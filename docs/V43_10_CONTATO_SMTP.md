# V43.10 — envio direto da página Contato

A página `/contato` envia mensagens pelo backend Flask para `sv.alisson@gmail.com`.
As credenciais não ficam no código nem no ZIP.

## Variáveis no Render

Para uma conta Gmail, configure:

- `CONTACT_TO_EMAIL=sv.alisson@gmail.com`
- `CONTACT_FROM_EMAIL=sv.alisson@gmail.com`
- `CONTACT_SMTP_USERNAME=sv.alisson@gmail.com`
- `CONTACT_SMTP_PASSWORD=<senha de aplicativo do Google>`

Os valores abaixo já possuem padrão no código, mas podem ser informados no Render:

- `CONTACT_SMTP_HOST=smtp.gmail.com`
- `CONTACT_SMTP_PORT=587`
- `CONTACT_SMTP_USE_TLS=1`
- `CONTACT_SMTP_USE_SSL=0`
- `CONTACT_SMTP_TIMEOUT=20`
- `CONTACT_RATE_LIMIT_SECONDS=60`

A senha deve ser uma senha de aplicativo da conta Google, criada após ativar a verificação em duas etapas. Não use a senha normal da conta e não coloque credenciais no GitHub.
