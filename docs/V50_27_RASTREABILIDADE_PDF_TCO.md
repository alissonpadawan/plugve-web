# CurVE V50.27 — rastreabilidade essencial no resultado/PDF TCO

Base: V50.26 homologada.

Escopo: completar, sem alterar cálculos, os parâmetros essenciais exibidos na página de resultado e no PDF TCO.

Incluído quando aplicável:
- preço inicial da energia;
- preços dos combustíveis;
- perfil flex;
- consumo utilizado;
- manutenção (valor anual ou “Não considerada”);
- referência FIPE (mês/ano retornado pela consulta FIPE);
- origem da curva de depreciação efetivamente utilizada;
- Seguro V2 com fonte, referência IPSA atual e nível de agregação em forma curta, sem exibição de 2021/2021A.

A referência FIPE e a origem da curva passam a ser preservadas como campos do formulário/snapshot S. Não há nova consulta nem recálculo na recuperação histórica. Snapshots anteriores continuam sem receber retroativamente os novos campos.

Não foram alterados TCO, depreciação, Seguro V2, IPVA, financiamento, CO2, ANEEL, ANP ou regras de matching.
