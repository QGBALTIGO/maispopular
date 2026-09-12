# Validação

## Testes offline

Execute:

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

A suíte cobre cálculo 2×, arredondamento em centavos, filtro e agrupamento do catálogo,
validação de CPF/telefone/e-mail, recarga mínima, idempotência de crédito e estorno,
débito único da carteira, devolução em rejeição, duplo clique e contrato HTTP da Cakto.

## Verificações ao implantar

1. Importar todos os módulos dentro do virtualenv da VPS.
2. Rodar a suíte completa antes de reiniciar o serviço.
3. Confirmar autenticação somente de leitura na API de serviços.
4. Validar que a oferta Cakto está ativa, é pagamento único e custa o valor unitário configurado.
5. Validar o token Telegram com `getMe` e conferir o log do `systemd`.
6. Abrir `/start`, catálogo, carteira e tela de recarga no chat privado.

Uma cobrança Pix real exige dados verdadeiros do pagador. Não gere uma cobrança artificial para
teste: use uma recarga real controlada e confirme crédito, segunda conciliação sem crédito duplicado
e apresentação do QR Code antes de liberar divulgação ampla.
