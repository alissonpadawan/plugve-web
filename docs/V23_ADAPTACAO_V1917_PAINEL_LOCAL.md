# V23 - Adaptação V19.17 do painel local

Este pacote corrige o diagnóstico histórico para seguir o fluxo que funcionava no painel local:

1. referência mensal;
2. marca na referência;
3. modelos na referência;
4. anos do modelo;
5. preço;
6. primeira aparição da coorte;
7. zero km 32000 no mês da primeira aparição;
8. reutilização dos códigos encontrados na primeira aparição para montar a série histórica.

O diagnóstico fica limitado para evitar timeout no Render. A coleta definitiva deve ser ligada depois de validar que a estratégia retorna pontos históricos suficientes.
