# CurVE V50.15 — Atividades / Pesquisas no painel administrativo

## Escopo

A V50.15 reorganiza a telemetria já existente em uma lista operacional cronológica dentro de `/admin/uso` e adiciona um modal de detalhes por atividade. Não altera cálculos de TCO, FIPE, depreciação, seguro ou snapshots.

## Lista de atividades

A seção **Atividades / Pesquisas** apresenta:

- data/hora;
- visitante pseudônimo;
- ambiente (dispositivo/navegador/SO);
- localização aproximada do acesso, quando fornecida pela infraestrutura;
- hash de rede abreviado;
- módulo/ação;
- código S/D/F quando houver;
- veículo/pesquisa principal.

## Modal de detalhes

Ao clicar em uma linha, o painel consulta o endpoint administrativo protegido:

`GET /api/site-usage/admin/telemetry/events/<event_id>`

O modal mostra contexto do evento, sessão, ambiente, local de acesso, local usado na simulação, horizonte, km/ano, veículos/códigos FIPE e metadados relevantes. Quando existe código S/D/F, o backend lê o snapshot imutável com verificação de integridade e devolve apenas um resumo compacto, além do link **Abrir resultado histórico**.

## Privacidade

A V50.15 não passa a armazenar IP bruto. O painel continua trabalhando com identificador pseudônimo, sessão, hash de rede, navegador, sistema operacional, tipo de dispositivo e geolocalização aproximada somente quando fornecida pela infraestrutura.

## Evento de recuperação histórica

A abertura bem-sucedida de `/resultado/<codigo>` passa a registrar o evento significativo `resultado / historical_result_opened`, permitindo acompanhar no admin quando um resultado histórico foi reconsultado.
