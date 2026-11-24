# cs-skin-prices

Coleta preços e histórico de skins de CS2 (AK-47, M4A1-S, facas e luvas) e gera uma página com a variação de cada uma.

## Fontes

| Fonte | O que dá | Limite | Quando roda |
|---|---|---|---|
| [Skinport API](https://docs.skinport.com) | Mediana, média e volume de vendas em 24h, 7, 30 e 90 dias de **todos** os itens, numa chamada só | 8 consultas a cada 5 min | Uma vez por dia |
| CSFloat `/api/v1/history/<nome>/graph` | Preço médio e número de vendas de cada dia, desde o lançamento do item | ~200 itens por hora | De hora em hora, 180 itens por vez |
| CSFloat `/api/v1/schema` | Lista de skins, faixas de float e preço de referência | — | Uma vez por dia |

A API de histórico do CSFloat não é documentada oficialmente e pode mudar.

## Como funciona

```
collector/catalog.py   data/catalog.json            quais skins acompanhar
collector/skinport.py  data/skinport/latest.json    estatísticas de venda atuais
                       data/skinport/daily/*.json.gz  um retrato por dia
                       data/skinport/fx.json        câmbio USD→BRL implícito
collector/csfloat.py   data/csfloat/history/*.json  histórico diário, um arquivo por skin
                       data/csfloat/state.json      o que já foi coletado e quando
collector/build.py     site/index.html              página com tudo embutido
```

Os dois workflows em `.github/workflows` rodam sozinhos, reconstroem a página e fazem commit só quando há dado novo. Eles dividem um grupo de concorrência, então nunca fazem push ao mesmo tempo.

O CSFloat devolve `429` com `Retry-After` quando passa do limite. O coletor para na hora, guarda até quando esperar em `state.json` e a próxima execução pula se ainda estiver cedo. Com 180 itens por hora, o catálogo inteiro (~2.700 skins) é coberto em umas 15 horas e depois cada skin é atualizada mais ou menos uma vez por dia.

## Rodar localmente

```bash
pip install -r requirements.txt
python -m collector.catalog
python -m collector.skinport
python -m collector.csfloat --max 20
python -m collector.build      # abre site/index.html no navegador
```

## Configuração

`config.json` define as categorias (por `def_index` do CS2), quantos itens buscar por execução e por quantos dias manter pontos diários na página (antes disso, semanais).

Para acompanhar outras armas, acrescente o `def_index` delas numa categoria. Por exemplo, a AWP é 9 e a M4A4 é 16.
