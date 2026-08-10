# V50.08 — Correções pós-auditoria da V50.07

Base: V50.07 — Painel administrativo de uso e tendências.

## Correções

1. **Credenciais separadas e sem segredo versionado**
   - `PLUGVE_SYNC_TOKEN`: somente rotas de sincronização Painel -> site.
   - `PLUGVE_ADMIN_TOKEN`: somente recursos administrativos humanos.
   - `SECRET_KEY`: obrigatória em produção; sem fallback conhecido em ambiente Render.
   - `render.yaml` não contém tokens literais.

2. **PDF de Depreciação**
   - `pdf_exported` só é registrado depois de existir resultado válido e imediatamente antes da impressão.

3. **Filtros temporais do `/admin/uso`**
   - datas escolhidas no navegador são convertidas para fronteiras UTC a partir do fuso local;
   - o backend recebe `tz_offset_minutes` e agrega os dias do gráfico no mesmo fuso usado pelo administrador.

4. **Curva própria x similaridade**
   - consultas de Depreciação registram `tipo_curva`;
   - dashboard exibe própria, herdada por similaridade e não informado/legado.

## Pré-deploy obrigatório

Antes de publicar:

- gere um novo `PLUGVE_SYNC_TOKEN`;
- gere um `PLUGVE_ADMIN_TOKEN` diferente;
- configure ambos como segredos no serviço Render;
- configure o mesmo Sync token no Painel Local;
- configure o mesmo Admin token no Painel Local somente se utilizar as telas locais de administração;
- não reutilize o token antigo que aparecia nos pacotes anteriores.

## Validação local

- `compileall`: aprovado.
- `node --check`: `admin_usage.js` e `depreciacao.js` aprovados.
- testes V50 afetados: 52 aprovados, 5 ignorados porque Flask não está instalado no sandbox.
- regressão ampla excluindo somente quatro arquivos de dívida previamente identificada: 233 aprovados, 10 ignorados, 58 subtests aprovados.
- quatro arquivos de dívida conhecidos, executados separadamente: 29 falhas, 7 aprovados, 5 subtests aprovados.
- total lógico da suíte atual: 240 aprovados, 29 falhas conhecidas, 10 ignorados e 63 subtests aprovados.

As 29 falhas permanecem concentradas nos testes PBEV V45/V2 e no teste legado de seguro V47; não pertencem às correções V50.08.
