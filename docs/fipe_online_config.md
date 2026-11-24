# Configuração FIPE Online

O catálogo e o preço atual usam a API FIPE v2 da Parallelum sem chave por padrão.

- Para ampliar a cota com uma chave gratuita, configure `FIPE_CURRENT_TOKEN` nas variáveis de ambiente do Render.
- A coleta técnica de histórico usa `FIPE_TOKEN` ou o arquivo persistente `fipe_token.txt`. O histórico estendido está sujeito ao plano do provedor.

Guarde os tokens no ambiente do servidor.

O contador local de requisições é salvo no Persistent Disk em:
/var/data/plugve/fipe_cache/requisicoes_fipe.json

O progresso de varredura é salvo em:
/var/data/plugve/fipe_cache/progresso_varredura.json
