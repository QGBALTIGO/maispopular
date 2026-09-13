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
- Pix com QR Code e copia-e-cola. Recargas de R$ 20 a R$ 100 em intervalos de R$ 5.
- Crédito automático após confirmação do pagamento e reversão idempotente em estorno/chargeback.
- Programa de afiliados: link individual e bônus de 15% sobre cada recarga aprovada do indicado.
- Histórico, atualização automática, reposição e cancelamento quando disponíveis.

O catálogo permanece disponível nativamente no Telegram e também no Mini App. A interface
visual usa o fluxo rede → tipo → serviço → pedido, busca local, cálculo instantâneo e uma
confirmação final com o preço recalculado pelo servidor. Toda operação autenticada valida o
`Telegram.WebApp.initData`; dados exibidos no navegador nunca autorizam preço ou usuário.

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
- Comissão de afiliado é vinculada uma única vez, impede autoindicação/ciclos e acompanha estornos.
- Broadcast administrativo usa destinatários congelados, confirmação, idempotência, progresso, cancelamento e retomada segura após reinício.
- Banners personalizados são convertidos para WebP e servidos com cache imutável por revisão.

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
| `/afiliados` | Abrir o programa de indicação |
| `/admin` | Abrir painel administrativo no Web App |
| `/darsaldo ID VALOR MOTIVO` | Creditar carteira (somente administradores) |

O `/start` mostra apenas **🛒 Abrir catálogo**, **📦 Meus pedidos** e **💬 Suporte**.
Os comandos antigos de compras e os botões de mensagens antigas encaminham ao
Web App; não abrem mais os formulários do chat. `/saldo`, `/recarga` e `/pedidos`
abrem as respectivas telas. O painel administrativo também fica na Carteira,
visível somente a IDs de `ADMIN_IDS` (a API verifica a permissão a cada chamada).

Exemplo: `/darsaldo 123456789 25,00 Bonificação de atendimento`. O cliente precisa
ter aberto o bot. São aceitos créditos positivos de R$ 0,01 a R$ 5.000,00. Cada
lançamento registra cliente, administrador, valor e motivo; reentregas do mesmo
update do Telegram ou da mesma confirmação HTTP não duplicam o crédito.

O painel administrativo do Web App também permite criar transmissões em texto,
acrescentar um botão de ação, revisar a prévia, acompanhar entregas/falhas e cancelar
os envios restantes. Apenas uma transmissão pode ficar ativa por vez.

A recarga do Mini App usa Pix nativo, com QR, copia e cola, histórico, retomada
da tentativa e consulta de confirmação. Os dados reais do pagador são exigidos
pelo contrato da integração; não são gravados no armazenamento do navegador e
são removidos do registro local da cobrança após a geração bem-sucedida.
`deploy/configure_deposits.py --apply` provisiona as 17 ofertas de R$ 20 a R$ 100
em passos de R$ 5, reaproveitando as existentes. O script altera a configuração
de ofertas, mas não gera cobranças nem movimenta dinheiro.

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
sudo cp deploy/maispopular-webapp.service deploy/maispopular-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo chmod 755 deploy/run_quick_tunnel.sh
sudo systemctl enable --now maispopular maispopular-webapp maispopular-tunnel
sudo systemctl status maispopular
sudo -u maispopular .venv/bin/python check_webapp.py
```

O Quick Tunnel gera um endereço HTTPS aleatório. O serviço grava a URL em
`data/webapp_url.txt`; o bot percebe mudanças e atualiza o botão **Abrir loja** em até 15
segundos. O túnel permanece em execução durante reinícios do bot e do WebApp, preservando o
endereço atual. Um reinício do próprio `cloudflared` ou da VPS ainda gera outro endereço;
para persistência inclusive nesses casos, use um Cloudflare Tunnel nomeado com domínio próprio.

Não execute uma segunda cópia com o mesmo token ou banco. Para backup online, copie o banco
usando a API de backup do SQLite ou inclua também os arquivos WAL/SHM.

## Referências técnicas

- [Autenticação OAuth2 da Cakto](https://docs.cakto.com.br/authentication)
- [Cobrança Pix transacional](https://docs.cakto.com.br/api-reference/payments/create-pix)
- [Idempotência da Cakto](https://docs.cakto.com.br/conceitos/idempotencia)
- [Consulta de pedidos Cakto](https://docs.cakto.com.br/api-reference/orders/retrieve)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Telegram Mini Apps](https://core.telegram.org/bots/webapps)
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
- [python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/)
