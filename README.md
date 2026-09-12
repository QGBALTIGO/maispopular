# Mais Popular — Bot para Telegram

Primeira versão administrativa, em português, com botões e armazenamento local.
Não é uma loja pública: não há carteira por cliente, Pix, Cakto ou cobrança automática.
Todos os administradores autorizados utilizam a mesma conta SouPopular e seu saldo.
Cada administrador consulta, neste bot, somente os pedidos que ele próprio criou.

**Padrão de entrega: `DRY_RUN=true`. Nenhum pedido, reposição ou cancelamento é enviado nesse modo.**
Catálogo e saldo, mesmo em simulação, exigem uma chave válida porque são consultas reais.
Nenhuma credencial foi incluída no projeto. Nenhum pedido real foi feito durante a criação.

## Recursos implementados

- Catálogo da API com categorias, paginação, busca por nome/categoria/ID e filtro por IDs autorizados.
- Detalhes de tarifa, limites, tipo e descrição quando o fornecedor a retorna.
- Formulários: Default, Custom Comments, Package e Poll. Outros tipos ficam apenas para consulta.
- Orçamento com Decimal; moeda lida do saldo, sem presumir BRL; confirmação expira em cinco minutos.
- Revalidação de tarifa, moeda, tipo, limites, teto estimado e saldo antes de um envio real.
- Histórico SQLite, consulta de status e notificações periódicas no privado quando o status muda.
- Solicitação de reposição/cancelamento com confirmação; consulta de status de reposição.
- Controle por ADMIN_IDS em toda a interface e no motor das operações de escrita.
- Cliente Python para services, balance, add, status simples/em lote, refill simples/em lote,
  refill_status simples/em lote e cancel em lote. A interface não oferece envio de pedidos em lote.

As condições dos serviços são do fornecedor. O bot não comprova qualidade, autenticidade,
velocidade ou taxa de entrega, nem garante reposição, cancelamento, reembolso ou resultado.
Use os serviços somente para finalidades permitidas e respeite as regras das plataformas envolvidas.

## Configuração inicial — Linux/VPS

Requer Python 3.11 ou superior e acesso de saída ao Telegram e à SouPopular.

No Ubuntu/Debian, instale os pré-requisitos e clone o repositório:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
git clone https://github.com/QGBALTIGO/maispopular.git
cd maispopular
```

Dentro da pasta do projeto:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
nano .env
```

Preencha BOT_TOKEN com o token criado no @BotFather e SOUPOPULAR_API_KEY com a chave de sua conta.
Não envie essas credenciais no chat, no GitHub ou em capturas de tela.

Pode deixar ADMIN_IDS vazio na primeira inicialização. Vazio **não libera o acesso**: apenas
/start e /meuid funcionam para descobrir o seu número.

```bash
python bot.py
```

Abra seu bot no privado e envie `/meuid`. Pare o processo com Ctrl+C, coloque seu número
em ADMIN_IDS, salve e reinicie. Vários administradores: `ADMIN_IDS=111111111,222222222`.
Os números são exemplos, não contas pré-autorizadas.

Mantenha `DRY_RUN=true`. Faça uma busca e conclua uma simulação. O pedido deverá aparecer
como simulado e sem ID do fornecedor. Saldo zero não impede a simulação, mas impede pedidos
reais de custo positivo.

Diagnóstico opcional, apenas de leitura:

```bash
python check_api.py
```

## Habilitar pedidos reais

Revise os serviços e suas regras no painel. É recomendável começar com um único ID de serviço
Default homologado em `ALLOWED_SERVICE_IDS`. Configure um teto pequeno em MAX_ORDER_COST.
Depois de revisar tudo, altere `DRY_RUN=false` e reinicie o processo.

**Só a confirmação final no chat envia o pedido. Nesse modo, ela pode consumir saldo real.**
O botão é identificado como “Confirmar pedido REAL”. Orçamentos de outro modo são invalidados.

MAX_ORDER_COST limita o **orçamento local**, na moeda da API. Não é um limite rígido garantido
pelo fornecedor: o endpoint público `add` não documenta um campo de preço máximo. Há uma
janela entre a leitura da tarifa e a aceitação do pedido. A cobrança final exibida é `charge`
retornada por `status`. Nenhuma conversão cambial é feita.

Para Default, Poll e Custom Comments, usa-se tarifa × quantidade / 1.000. Nos comentários,
a quantidade é o número de linhas não vazias. **Package usa `rate` por pacote nesta implementação.**
A documentação pública não esclarece detalhadamente a unidade de cobrança de cada tipo especial.
Homologue essa convenção na sua conta antes de permitir Package em produção. Assinaturas,
drip-feed e tipos desconhecidos não são enviados pela interface.

## Comandos

| Comando | Finalidade |
|---|---|
| /start | Menu e modo de operação |
| /catalogo | Categorias e serviços |
| /buscar termo | Buscar nome, categoria ou ID |
| /pedidos | Histórico criado neste bot pelo administrador atual |
| /pedido ID | Consultar pelo ID no fornecedor, desde que vinculado ao administrador |
| /saldo | Saldo da conta SouPopular, não carteira de clientes |
| /cancelar | Descartar formulário/rascunho; não cancela um pedido real já enviado |
| /meuid | Mostrar seu ID numérico |
| /ajuda | Instruções dentro do bot |

Para pedir cancelamento de um pedido real, abra-o em Meus pedidos e use **Pedir cancelamento**.
Reposição e cancelamento podem ser recusados pelo fornecedor. O catálogo pode não informar
os indicadores dessas capacidades; nesse caso o bot permite solicitar, mas não promete suporte.
Quando o indicador é explicitamente falso, a operação é bloqueada.

## Proteções contra repetição e falhas ambíguas

Cada confirmação tem um identificador persistido em SQLite. A transição para SENDING é atômica.
Cliques repetidos no mesmo orçamento não repetem o envio. Pedidos ativos ou incertos do mesmo
serviço e destino exato também bloqueiam outro envio pelo bot, inclusive entre administradores.
Essa comparação não identifica todos os links equivalentes ou pedidos criados fora do bot.

Consultas podem ser repetidas após falhas transitórias. **Operações de escrita nunca recebem
retry automático.** Se a conexão cair, houver HTTP inesperado ou faltar o ID de confirmação,
o registro passa a UNKNOWN. O fornecedor pode já ter aceitado a solicitação.

Na reinicialização, SENDING é convertido para UNKNOWN; não é reprocessado. A trava de instância
impede dois processos com o mesmo banco local. Execute apenas uma instância por bot/conta.
A trava não coordena servidores diferentes, cópias diferentes do banco ou pedidos externos.

### Resolver um pedido incerto

Confira no painel o destino, serviço, quantidade e horário. A API de status não retorna dados
suficientes para comprovar automaticamente que um ID corresponde ao rascunho local.
Após confirmar pessoalmente que o pedido foi criado, vincule:

```text
/resolver ID_LOCAL ID_DO_FORNECEDOR CONFIRMO
```

Se você verificou o painel e, quando necessário, confirmou com o suporte que ele NÃO foi criado:

```text
/resolver ID_LOCAL naocriado CONFIRMO
```

Isso não reenvia o pedido. Apenas registra sua confirmação e encerra a incerteza local.
Uma consulta de status isolada não comprova a inexistência de um pedido sem ID.

Ações de reposição/cancelamento também possuem confirmação persistente e proteção contra
repetição. Reposições aceitas têm um intervalo local mínimo de 24 horas; esse é um limite do
bot, não uma garantia ou regra universal do fornecedor. Cancelamento aceito não é repetido.
Ações incertas ficam bloqueadas até conferência manual. Somente após confirmar que uma ação
incerta NÃO foi aceita no fornecedor, use:

```text
/liberar_acao ID_LOCAL_DA_ACAO CONFIRMO
```

## Execução persistente com systemd

Alternativa à execução manual. Não rode os dois processos ao mesmo tempo.
Os comandos abaixo pressupõem que você copiou o projeto, incluindo o `.env` configurado, para `/opt/maispopular`. Para uma instalação nova nesse caminho, use `sudo git clone https://github.com/QGBALTIGO/maispopular.git /opt/maispopular` e configure o `.env` antes de continuar.

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
sudo journalctl -u maispopular -f
```

Se a conta de serviço já existir, não repita useradd. O `.env` precisa ser um **arquivo**
configurado antes de iniciar o serviço. Após mudar variáveis:

```bash
sudo systemctl restart maispopular
```

Não exponha o banco por HTTP. Faça backup protegido do diretório data com o bot parado,
ou usando o mecanismo de backup do SQLite. Ao fazer backup com o processo em execução,
não copie apenas o arquivo `.sqlite3` ignorando WAL e SHM. Para restaurar, pare a instância.

## Execução com Docker

Alternativa ao systemd/manual; requer Docker com Compose instalado. Configure `.env` primeiro.

```bash
docker compose up -d --build
docker compose logs -f
```

O volume nomeado preserva o banco entre reinicializações. **Não use `docker compose down -v`
sem backup:** isso pode apagar o histórico e a proteção contra repetição de confirmações antigas.
Após editar `.env`, recrie o contêiner com `docker compose up -d --force-recreate`.
Não há porta pública, domínio ou webhook a configurar: este projeto usa polling do Telegram.

## Testes e limites da validação

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

Consulte TESTES.md para o que foi efetivamente executado e o que não pôde ser validado.
As respostas dos testes são simuladas, não números reais de saldo ou pedidos da sua conta.

## Arquitetura

- bot.py — inicialização, comandos, roteamento e notificações do Telegram.
- ui_common.py — botões, mensagens, autorização e utilitários compartilhados.
- ui_catalog.py — menu, catálogo, busca e detalhes dos serviços.
- ui_checkout.py — formulários e confirmação dos orçamentos.
- ui_orders.py — histórico, status, reposição e cancelamento.
- provider.py — cliente HTTP assíncrono, serialização, TLS e erros seguros.
- domain.py — serviços, validações, preços e tradução de status.
- engine.py — orçamento, confirmação, envio e proteção de operações.
- storage.py — SQLite, histórico, estados e confirmação atômica.
- config.py — variáveis de ambiente.
- check_api.py — diagnóstico apenas de leitura.
- tests/test_core.py — testes offline do núcleo, cliente e persistência.

Formulários em preenchimento ficam em memória e devem ser reiniciados após reiniciar o bot.
Orçamentos já gerados, pedidos e ações são persistidos. Dados não são removidos automaticamente;
o banco contém IDs do Telegram, destinos, comentários fornecidos e histórico. Restrinja o acesso
e defina uma política de retenção antes de abrir o serviço a outras pessoas.

## Documentação usada

- API pública: https://soupopular.net/api
- Exemplo oficial original: https://soupopular.net/example.txt
- Catálogo público: https://soupopular.net/services
- Biblioteca Telegram: https://docs.python-telegram-bot.org/en/stable/
- Verificação TLS: https://www.python-httpx.org/advanced/ssl/
- Criação de bot: https://core.telegram.org/bots/features#creating-a-new-bot

O exemplo PHP colado na conversa havia sido traduzido, inclusive palavras reservadas e chaves.
A API usa `key`, `action`, `order`, `orders`, `services`, `balance`, `refill` e `refill_status`.
A tabela pública de status contém uma inconsistência: mostra `service` onde o exemplo oficial
original usa `order`/`orders`. Este cliente segue o exemplo original. A confirmação final dessa
integração depende da resposta autenticada da conta; ela não foi feita durante esta entrega.

O exemplo PHP desativa a verificação do certificado. Este cliente mantém TLS verificado e
não segue redirecionamentos com a chave. O catálogo não garante descrição completa, moeda
por serviço ou indicadores de reposição/cancelamento; o código não inventa essas informações.
