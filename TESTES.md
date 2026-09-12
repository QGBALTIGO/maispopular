# Validação da entrega

## Executado neste ambiente

- Compilação de sintaxe de todos os arquivos Python com `python -m compileall -q .`.
- `python -m unittest discover -s tests -v`: **54 testes passaram**.
- Ambiente dos testes: Python 3.13.5, httpx 0.28.1 e python-dotenv 1.2.2.

Os testes são offline. O cliente HTTP usa `httpx.MockTransport`; o motor de pedidos usa
respostas simuladas e SQLite temporário. Não foram feitas chamadas autenticadas ao Telegram
ou à conta SouPopular, nem operações de compra, cancelamento ou reposição reais.

## Publicação no GitHub

Os 54 testes offline foram executados novamente antes da publicação. A interface originalmente
concentrada em bot.py foi organizada em ui_common.py, ui_catalog.py, ui_checkout.py e ui_orders.py.
A equivalência sintática (AST) de todas as funções/classes originais foi conferida; a separação
não altera seus corpos. Tokens e chaves continuam somente no .env local, ignorado pelo Git.
A instalação completa das dependências também não ficou disponível neste ambiente de publicação;
a validação autenticada continua pendente.

## Cobertura principal

Preço por mil e por pacote conforme as convenções da implementação; valores monetários
inválidos; limites de quantidade; comentários; alternativas de enquete; URLs de destino;
serviços não suportados; moeda retornada pelo fornecedor; serialização dos campos ingleses;
cache; consultas em lote; timeout de escrita sem retry; HTTP 5xx de escrita sem retry;
resposta sem ID; JSON inválido; redirecionamentos sem encaminhar credenciais; ocultação de
chave em erros; controle de administradores e propriedade de pedidos; simulação sem envio;
confirmação repetida e concorrente; orçamento expirado; alteração de preço, moeda ou modo;
saldo insuficiente; teto local; estados UNKNOWN e REJECTED; recuperação após reinicialização;
mesmo destino com pedido ativo; liberação após conclusão; lista de serviços autorizados;
reposição/cancelamento; ações incertas; notificações de pedidos terminais ainda pendentes.

## Não validado nesta entrega

A biblioteca python-telegram-bot não estava instalada no ambiente de geração. A tentativa
de instalá-la falhou por indisponibilidade de rede/DNS. Portanto, **a inicialização efetiva
da Application e a interface do Telegram não foram executadas aqui**. O arquivo bot.py foi
verificado sintaticamente, não por um teste de integração com a biblioteca instalada.

A configuração de dependência python-telegram-bot 22.8 foi baseada na documentação oficial
consultada. A compatibilidade de ponta a ponta deve ser homologada na máquina de execução.
Docker e systemd foram fornecidos como configurações, não construídos/iniciados neste ambiente.

Sem a chave da conta também não foi possível confirmar catálogo autenticado, descontos,
moeda efetiva, unidade de cobrança de tipos especiais, indicadores de reposição/cancelamento,
respostas reais de cancelamento ou o processamento efetivo de pedidos. Os valores dos testes
não são ofertas, preços, saldos ou IDs reais.

Comece com DRY_RUN=true, rode check_api.py e teste o bot no privado. Antes de permitir envios
reais, revise as regras dos serviços e mantenha ALLOWED_SERVICE_IDS restrito aos IDs homologados.
