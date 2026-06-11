# V24.5 — Motor V19.17 em modo Pública/Pública

Objetivo: alinhar o diagnóstico V19.17 ao painel local quando o usuário usa:

- API consulta: `1 - Pública`
- API histórico: `1 - Pública`
- token/API paga: ignorados

## O que foi alterado

1. `FipeService` passou a operar por padrão em `FIPE_PUBLIC_ONLY=1`.
2. A consulta básica de marca/modelo/ano/preço passa a usar `https://parallelum.com.br/fipe/api/v1/carros` por padrão.
3. O diagnóstico V19.17 não usa mais fallback para API paga/v2 nem `/history` curto.
4. O histórico usa o fluxo público Web do painel local:
   - `ConsultarTabelaDeReferencia`
   - `ConsultarMarcas`
   - `ConsultarModelos`
   - `ConsultarAnoModelo`
   - `ConsultarValorComTodosParametros`
5. O cliente FIPE Web usa headers e retry alinhados ao programa local, com aquecimento de sessão via página pública.
6. Se `ConsultarTabelaDeReferencia` falhar, as referências mensais são reconstruídas pela numeração FIPE conhecida, mas a coleta de preço continua sendo feita pela FIPE Web pública.
7. O terminal temporário mostra explicitamente:
   - API consulta pública
   - API histórico pública/Web FIPE
   - token ignorado
   - API paga/v2 não usada

## Proteções mantidas

- O botão Calcular definitivo continua protegido.
- Nenhuma curva definitiva é salva.
- A coleta continua em lotes pequenos para evitar timeout no Render.
- O diagnóstico continua paralelo.
