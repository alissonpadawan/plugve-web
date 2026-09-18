# CurVE V51.37 — polimento da autenticação

- Login aprovado passa a ser silencioso: a pessoa entra na CurVE sem banner de “acesso realizado”.
- A aplicação autenticada volta a ter a aparência normal da CurVE; a camada de acesso fica fora do fluxo visual após o login.
- Campos lado a lado do cadastro, especialmente Senha e Confirmar senha, passam a alinhar pelo topo independentemente de textos auxiliares.
- Mantida a porta de login/cadastro para usuários não autenticados e toda a proteção de backend da V51.35/V51.36.
- Nenhuma alteração em TCO, FIPE+, Depreciação, telemetria, S/D/F ou dados persistentes.
