# V50.19 — Limpeza da visualização de resultado histórico

Escopo exclusivamente de apresentação da página pública de resultados S/D/F.

- remove o aviso visual “Snapshot preservado”;
- mantém apenas a data/hora na frase de geração original;
- remove da interface pública schema, SHA-256, tamanho e payload JSON;
- mantém integridade e imutabilidade do snapshot no backend/banco;
- troca nomes internos de parâmetros por rótulos legíveis;
- oculta chaves puramente técnicas do formulário na visualização pública;
- valores numéricos zero sem significado operacional passam a “—”; flags booleanas relevantes usam Sim/Não.

Nenhum snapshot existente é alterado e nenhum cálculo é refeito.
