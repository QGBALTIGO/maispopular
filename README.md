# Mais Popular

Loja pública de serviços digitais no Telegram, com catálogo por plataforma, carteira individual,
recarga Pix pela Cakto e acompanhamento automático de pedidos.

## Experiência do cliente

- Entrada livre pelo `/start`; somente funções operacionais são restritas ao administrador.
- Catálogo em duas etapas: rede social primeiro, serviços relacionados depois.
- Busca por nome, descrição, plataforma ou código.
- Serviços internos, separadores e tipos sem formulário compatível não aparecem na vitrine.
- Descrições vêm do próprio serviço e são higienizadas para remover HTML, links e marca externa.
- Preço final em reais calculado com multiplicador obrigatório de 2 sobre o custo da API.
- Carteira por usuário, histórico de movimentações e débito atômico na confirmação.
- Pix com QR Code e copia-e-cola. Recargas de R$ 20, R$ 50, R$ 100 ou R$ 200.
- Crédito automático após confirmação do pagamento e reversão idempotente em estorno/chargeback.
- Histórico, atualização automática, reposição e cancelamento quando disponíveis.

O catálogo principal permanece nativo no Telegram e usa três níveis curtos para celular:
rede → tipo de serviço → opção. Uma WebApp com cálculo instantâneo pode ser adicionada quando
houver um domínio HTTPS próprio; a implantação de produção não depende de túnel temporário.

## Segurança e consistência financeira

- Credenciais somente no `.env`, que é ignorado pelo Git.
- OAuth2 da Cakto com token em memória e renovação automática.
- `X-Idempotency-Key` persistida por intenção de recarga.
- Uma recarga paga credita a carteira uma única vez.
- Um pedido confirmado debita a carteira uma única vez, mesmo com cliques repetidos.
- Rejeição explícita devolve o saldo; resultado externo incerto fica bloqueado para conciliação.
- Pagamentos e pedidos são consultados periodicamente sem reenviar operações de compra.
- SQLite usa WAL, `synchronous=FULL`, transações imediatas e trilha contábil imutável por referência.
- CPF e dados de cobrança são apagados do banco local após a criação ou rejeição definitiva do Pix.

## Configuração

Requer Python 3.11 ou superior. Copie `.env.example` para `.env` e preencha as credenciais.
Cada entrada de `CAKTO_OFFERS_JSON` associa um valor a uma oferta ativa de pagamento único
com o mesmo preço. O bot valida todas elas antes de começar a receber atualizações.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m compileall -q .
python -m unittest discover -s tests -v
python check_api.py
python bot.py
```

## Comandos

| Comando | Função |
|---|---|
| `/start` | Abrir a loja |
| `/catalogo` | Escolher rede social e serviço |
| `/buscar termo` | Buscar no catálogo |
| `/saldo` | Ver carteira e movimentações |
| `/recarga` | Gerar Pix |
| `/pedidos` | Acompanhar compras |
| `/pedido CODIGO` | Abrir um pedido próprio |
| `/ajuda` | Instruções |
| `/admin` | Métricas operacionais do administrador |

## Deploy com systemd

O serviço espera o projeto em `/opt/maispopular` e executa com o usuário restrito `maispopular`.

```bash
sudo useradd --system --home /opt/maispopular --shell /usr/sbin/nologin maispopular
sudo mkdir -p /opt/maispopular/data
sudo chown -R maispopular:maispopular /opt/maispopular
cd /opt/maispopular
sudo -u maispopular python3 -m venv .venv
sudo -u maispopular .venv/bin/pip install -r requirements.txt
sudo chmod 600 .env
sudo cp deploy/maispopular.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now maispopular
sudo systemctl status maispopular
```

Não execute uma segunda cópia com o mesmo token ou banco. Para backup online, copie o banco
usando a API de backup do SQLite ou inclua também os arquivos WAL/SHM.

## Referências técnicas

- [Autenticação OAuth2 da Cakto](https://docs.cakto.com.br/authentication)
- [Cobrança Pix transacional](https://docs.cakto.com.br/api-reference/payments/create-pix)
- [Idempotência da Cakto](https://docs.cakto.com.br/conceitos/idempotencia)
- [Consulta de pedidos Cakto](https://docs.cakto.com.br/api-reference/orders/retrieve)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/)
