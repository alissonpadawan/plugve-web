# Calculadora de Depreciação V2

## Estado atual

Etapa 4.3 implementada.

A aplicação Flask modular já possui:

- consulta FIPE pública;
- leitura de curvas salvas de combustão e elétrico;
- resumo automático de curva salva;
- botão de cálculo sob demanda;
- download de histórico FIPE mensal para combustão;
- bloqueio de cálculo direto em zero km;
- proxy de combustão para zero km usando ano usado equivalente do mesmo modelo;
- auditoria básica do histórico utilizado.

## Regra técnica importante

O código FIPE 32000 representa veículo zero km. A série histórica desse código mede variação de preço de tabela do veículo novo, não depreciação real. Por isso, o cálculo direto foi bloqueado.

Na Etapa 4.3, quando o veículo é zero km, o sistema procura anos usados do mesmo modelo, prioriza o mesmo combustível, baixa o histórico FIPE desse ano usado e aplica a taxa calculada ao valor atual do zero km.

## Próxima etapa sugerida

Etapa 4.4: validar proxy de combustão com vários modelos e melhorar a auditoria visual.
