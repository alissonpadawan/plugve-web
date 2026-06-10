# Configuração FIPE Online

O token da FIPE deve ser configurado no Render em Environment Variables, com o nome:

FIPE_TOKEN

Não salvar token real no GitHub.

O app usa a API v2:
https://fipe.parallelum.com.br/api/v2/cars

O contador local de requisições é salvo no Persistent Disk em:
/var/data/plugve/fipe_cache/requisicoes_fipe.json

O progresso de varredura é salvo em:
/var/data/plugve/fipe_cache/progresso_varredura.json
