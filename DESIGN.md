# Mais Popular — Mini App

Interface mobile-first: base clara, azul para ações, tipografia de sistema,
logos de marca locais, duas colunas no celular e navegação inferior fixa.
Categorias e títulos são separados das condições comerciais. Respeita
`prefers-reduced-motion`, foco de teclado e autenticação oficial Telegram.

## Referências

- Wise Design: https://wise.design/components/card — hierarquia e agrupamento.
- Simple Icons: https://github.com/simple-icons/simple-icons — marcas vetoriais.
- Dashboard Icons: https://github.com/homarr-labs/dashboard-icons — Disney+ e Xbox.
- Assets complementares: favicons oficiais e ícones publicados pelos desenvolvedores no Google Play.
- Cada fonte está documentada em `webapp_static/brands/*SOURCES.json`.
- Marcas usadas para identificação, sem alegação de parceria ou endosso.

## Conteúdo

`catalog_content.json` é um snapshot das descrições públicas do catálogo,
importado em 2026-09-12. Não contém credenciais nem dados de clientes.
O casamento exige ID e nome iguais para evitar reaproveitamento indevido.
Preços, limites, disponibilidade e capacidades vêm sempre da API atual.
Para atualizar o snapshot: `python deploy/refresh_catalog_content.py`
(ferramenta de manutenção requer beautifulsoup4 e httpx).

As descrições dos serviços 698, 704 e 906 apresentam divergências detectadas.
O cliente recebe um aviso em vez de uma promessa inventada.
Assinaturas sem descrição detalhada indicam a ausência das condições de entrega.
Os nomes expandidos seguem o item/ID e o contexto da categoria de streaming;
DN plus, HMX e GPLAY foram interpretados como Disney+, HBO Max e Globoplay.
Conferir essas correspondências com o fornecedor ao revisar o catálogo.

## Verificação

- `python -m unittest discover -s tests -q`
- `node tests/test_price.js`
- `node --check webapp_static/app.js`
- `python deploy/preview_ui.py`: servidor somente local, catálogo real, carteira
  isolada, token fictício, envio de pedidos bloqueado. Nunca apontar o túnel a ele.
- O preview não substitui uma compra real: testes de layout e orçamento não
  confirmam a entrega de produtos nem o pagamento Pix.
