# PlugVE Web — Deploy no Render

## Configuração do Web Service

Build Command:

```txt
pip install -r requirements.txt
```

Start Command:

```txt
gunicorn app:app
```

## Rotas principais

```txt
/
/simular
/depreciacao
/metodologia
/sobre
/contato
/api/depreciacao/status
/api/depreciacao/painel
```

## Observações

- A pasta `data/` deve ser enviada junto com o projeto.
- O arquivo `data/familias_fipe.xlsx` é necessário para o painel de depreciação reconhecer famílias/modelos FIPE.
- Dados gerados em produção não devem ser considerados persistentes sem Persistent Disk ou banco de dados.
