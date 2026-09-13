# Vitrine e fila de entrega

A vitrine usa o catálogo real, com preço de revenda já aplicado pelo servidor. As três artes em `webapp_static/banners` foram fornecidas pelo proprietário. Nenhum contador de clientes, desconto ou estoque foi inventado. BaltigoFlix é apenas um link direto externo; não usa a carteira desta loja.

## Pedido pago sem capacidade operacional

1. O cliente confirma orçamento válido e com saldo suficiente na própria carteira.
2. Uma transação SQLite debita a carteira uma única vez e registra `QUEUED`.
3. Com saldo operacional e condições de preço preservadas, o envio passa por uma atualização condicional `QUEUED -> SENDING` antes da chamada ao fornecedor.
4. Saldo insuficiente mantém a fila; o bot tenta novamente em intervalos de aproximadamente um minuto (worker a cada 30 segundos). O administrador recebe aviso com acesso ao painel.
5. Resposta incerta ao enviar muda para `UNKNOWN`: não há reenvio automático, por risco de duplicidade. Resolver essa situação exige verificar o pedido externo no painel.
6. Rejeição explícita que não seja falta de fundos cancela e devolve o saldo à carteira. Não significa estorno bancário do Pix.

## Atendimento manual

Em Carteira → Administração → Fila de entrega, registre uma observação e assuma o pedido. Só execute a entrega externa depois de confirmar o estado manual. O responsável pode concluir uma entrega efetivamente realizada, cancelar com devolução à carteira ou devolver à fila se não houve entrega externa. Outro administrador não pode liberar um pedido já assumido, evitando corrida com trabalho manual em curso.

Todas as decisões manuais registram administrador, pedido, ação, nota e horário em `fulfillment_audit`. O cliente vê processamento/conclusão/cancelamento, sem custos ou motivos internos. Informações sobre prazos e condições continuam visíveis antes de contratar.

Fila, propriedade manual e lançamentos persistem em SQLite. Reinício mantém `QUEUED` e `MANUAL`; envio interrompido vira `UNKNOWN`. Nunca restaure um banco antigo depois de movimentações reais: o backup pré-deploy serve para recuperação coordenada, não rollback indiscriminado de saldos.

## Verificação

`python -m unittest discover -s tests -q` verifica saldo, pagamento, autorização, fila e concorrência. `deploy/preview_ui.py` usa catálogo real somente para leitura, provedor de envio bloqueado, carteira temporária e Pix fictício. Nenhuma compra ou crédito real deve ser usado como teste sem autorização específica.

Após publicar, execute `check_webapp.py` internamente e pelo túnel, confirme serviços ativos e URL atual do menu do bot. O túnel aleatório muda quando reiniciado.
