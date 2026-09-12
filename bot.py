"""Bot administrativo Telegram / SouPopular. Execute: python bot.py"""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import logging
import math
import os
from pathlib import Path
import sys
import time

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard
from telegram import BotCommand, LinkPreviewOptions, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import (Application, ApplicationHandlerStop, CallbackQueryHandler,
                          CommandHandler, ContextTypes, MessageHandler, TypeHandler, filters)

from config import Settings
from domain import STATUS_PT, money, normalize, validate_target
from engine import Panel
from provider import ProviderError, SouPopular
from storage import Store

from ui_common import (LOG, PAGE, LOCAL_STATES, SecretFilter, e, btn, panel, uid,
                       category_key, pager, say, home_rows, guard)

from ui_catalog import (home, identity, help_page, balance_page, catalog_page,
                        category_page, search_prompt, search_page, service_page)
from ui_checkout import begin_order, text_input
from ui_orders import order_text, orders_page, order_page, action_preview, action_result

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    raw = update.callback_query.data or ''
    parts = raw.split(':')
    action = parts[0]
    if action == 'noop':
        return
    if action == 'home':
        await home(update,context)
    elif action == 'identity':
        await identity(update,context)
    elif action == 'help':
        await help_page(update,context)
    elif action == 'balance':
        await balance_page(update,context)
    elif action == 'catalog':
        await catalog_page(update,context,int(parts[1]))
    elif action == 'category':
        await category_page(update,context,parts[1],int(parts[2]))
    elif action == 'search_prompt':
        await search_prompt(update,context)
    elif action == 'search':
        await search_page(update,context,int(parts[1]))
    elif action == 'service':
        await service_page(update,context,int(parts[1]))
    elif action == 'buy':
        await begin_order(update,context,int(parts[1]))
    elif action == 'confirm':
        row = await panel(context).submit(parts[1],uid(update))
        await order_page(update,context,row['id'])
    elif action == 'orders':
        await orders_page(update,context,int(parts[1]))
    elif action in {'order','update'}:
        await order_page(update,context,parts[1],refresh=action=='update')
    elif action == 'action':
        await action_preview(update,context,parts[2],parts[1])
    elif action == 'action_confirm':
        await action_result(update,context,parts[1])
    elif action == 'refill_status':
        item = panel(context).store.action(parts[1],uid(update))
        if not item:
            raise ValueError('Reposição não encontrada para seu usuário.')
        refill = json.loads(item['result_json']).get('refill')
        if not refill:
            raise ValueError('Esta solicitação não tem ID de reposição.')
        result = await panel(context).api.refill_status(refill)
        await say(update,f'♻️ <b>Reposição #{e(refill)}</b>\n\nStatus: {e(result["status"])}',
                  [[btn('🔄 Atualizar',raw),btn('📦 Pedido',f'order:{item["order_id"]}')]])
    else:
        raise ValueError('Botão inválido ou de uma versão antiga. Use /start.')


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await search_prompt(update,context)
    else:
        context.user_data.pop('flow',None)
        context.user_data['search'] = ' '.join(context.args)[:100]
        await search_page(update,context)


async def order_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1 or not context.args[0].isdigit():
        raise ValueError('Use /pedido ID_DO_FORNECEDOR. O pedido precisa ter sido criado por você neste bot.')
    row = panel(context).store.by_provider(context.args[0],uid(update))
    if not row:
        raise ValueError('Este ID não está vinculado a um pedido do seu usuário neste bot.')
    await order_page(update,context,row['id'],refresh=True)


async def resolve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    if len(context.args) != 3 or context.args[2] != 'CONFIRMO':
        raise ValueError('Depois de verificar manualmente o painel: /resolver ID_LOCAL ID_FORNECEDOR CONFIRMO; ou /resolver ID_LOCAL naocriado CONFIRMO. Nunca use naocriado sem verificar o painel e, se necessário, o suporte.')
    token, decision, _ = context.args
    async with p.mutation_lock:
        row = p.store.order(token,uid(update))
        if not row or row['state'] != 'UNKNOWN':
            raise ValueError('Somente um pedido incerto do seu usuário pode ser reconciliado.')
        if decision == 'naocriado':
            p.store.mark_order(token,'REJECTED',error='Administrador confirmou manualmente que não houve criação no fornecedor.')
        elif decision.isdigit() and int(decision) > 0:
            status = await p.api.status(decision)
            # A API de status não fornece destino/serviço para comprovar a correspondência.
            # CONFIRMO é a declaração explícita do administrador após conferir no painel.
            p.store.mark_order(token,'SUBMITTED',provider_id=decision)
            p.store.update_status(token,status)
        else:
            raise ValueError('Informe um ID positivo do fornecedor ou naocriado.')
    await order_page(update,context,token)


async def unlock_action_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    if len(context.args) != 2 or context.args[1] != 'CONFIRMO':
        raise ValueError('Somente após confirmar no painel/suporte que a ação NÃO foi aceita: /liberar_acao ID_LOCAL_ACAO CONFIRMO.')
    async with p.mutation_lock:
        action = p.store.action(context.args[0],uid(update))
        if not action or action['state'] != 'UNKNOWN':
            raise ValueError('Ação incerta não encontrada para seu usuário.')
        p.store.mark_action(action['id'],'REJECTED',error='Administrador confirmou que a ação não foi aceita.')
    await say(update,'✅ Registro marcado como não aceito, conforme sua confirmação. Nenhuma ação foi reenviada.',home_rows())


async def poll_orders(context: ContextTypes.DEFAULT_TYPE) -> None:
    p = panel(context)
    watched = p.store.watched(100)
    if not watched:
        return
    try:
        statuses = await p.api.multi_status([r['provider_id'] for r in watched])
    except ProviderError:
        LOG.warning('Consulta periódica indisponível; nenhum envio será repetido.')
        return
    for row in watched:
        p.store.touched(row['id'])
        data = statuses.get(row['provider_id'])
        if not isinstance(data,dict) or data.get('error') or not isinstance(data.get('status'),str) or not data['status'].strip():
            continue
        p.store.update_status(row['id'],data)
        row = p.store.order(row['id'],row['user_id'])
        if row['provider_status'] == row['notified_status']:
            continue
        if row['user_id'] not in p.settings.admin_ids:
            p.store.notified(row['id'],row['provider_status'])
            continue
        try:
            await context.bot.send_message(row['user_id'],'🔔 <b>Atualização de pedido</b>\n\n'+order_text(row),
                parse_mode='HTML',link_preview_options=LinkPreviewOptions(is_disabled=True),
                reply_markup=Keyboard([[btn('📦 Abrir pedido',f'order:{row["id"]}')]]))
        except TelegramError:
            LOG.warning('Notificação não entregue; será tentada em outra consulta.')
        else:
            p.store.notified(row['id'],row['provider_status'])
        await asyncio.sleep(0.08)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    # Não registrar update, request, URLs do Telegram ou payloads: podem conter dados/chaves.
    LOG.warning('Falha tratada (%s).',type(error).__name__)
    if not isinstance(update,Update) or not update.effective_message:
        return
    message = str(error) if isinstance(error,(ProviderError,ValueError,PermissionError)) else \
              'Não consegui concluir esta etapa. Confira /pedidos antes de tentar um novo envio.'
    # Mesmo mensagens inesperadas passam por remoção defensiva das credenciais conhecidas.
    settings = panel(context).settings
    for secret in (settings.api_key,settings.bot_token):
        if secret:
            message = message.replace(secret,'[segredo ocultado]')
    try:
        await update.effective_message.reply_text(f'⚠️ {message[:800]}')
    except TelegramError:
        LOG.warning('Não foi possível exibir a mensagem de erro no Telegram.')


async def post_init(app: Application) -> None:
    try:
        await app.bot.set_my_commands([BotCommand('start','Abrir menu'),BotCommand('catalogo','Ver serviços'),
            BotCommand('buscar','Buscar serviços'),BotCommand('pedidos','Meus pedidos'),
            BotCommand('pedido','Consultar pedido pelo ID'),BotCommand('saldo','Saldo do fornecedor'),
            BotCommand('cancelar','Descartar formulário atual'),BotCommand('meuid','Ver meu ID'),BotCommand('ajuda','Como funciona')])
    except TelegramError:
        LOG.warning('Não foi possível registrar o menu de comandos.')


async def post_shutdown(app: Application) -> None:
    await app.bot_data['panel'].api.close()


def build_app(p: Panel) -> Application:
    app = (Application.builder().token(p.settings.bot_token).concurrent_updates(False)
           .post_init(post_init).post_shutdown(post_shutdown).build())
    app.bot_data['panel'] = p
    app.add_handler(TypeHandler(Update,guard),group=-1)
    for command,handler in [('start',home),('catalogo',catalog_page),('buscar',search_command),
        ('pedidos',orders_page),('pedido',order_command),('saldo',balance_page),('cancelar',home),
        ('meuid',identity),('ajuda',help_page),('resolver',resolve_command),('liberar_acao',unlock_action_command)]:
        app.add_handler(CommandHandler(command,handler))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_input))
    app.add_error_handler(error_handler)
    if app.job_queue is None:
        raise RuntimeError('Instale python-telegram-bot[job-queue] conforme requirements.txt.')
    app.job_queue.run_repeating(poll_orders,interval=p.settings.poll_seconds,first=15,
                               job_kwargs={'max_instances':1,'coalesce':True})
    return app


@contextmanager
def instance_lock(path: Path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as file:
        try:
            if os.name == 'nt':
                import msvcrt
                file.seek(0)
                file.write(b'0')
                file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Já existe uma instância usando este banco. Não inicie duas cópias.') from None
        yield


def main() -> None:
    os.umask(0o077)
    logging.basicConfig(format='%(asctime)s %(levelname)s %(name)s: %(message)s',level=logging.INFO)
    for name in ('httpx','httpcore','telegram','apscheduler'):
        logging.getLogger(name).setLevel(logging.WARNING)
    settings = Settings.load()
    for handler in logging.getLogger().handlers:
        handler.addFilter(SecretFilter((settings.bot_token,settings.api_key)))
    LOG.info('Inicializando em modo %s.', 'SIMULAÇÃO' if settings.dry_run else 'REAL')
    if not settings.admin_ids:
        LOG.warning('Nenhum administrador liberado. Use /meuid e configure ADMIN_IDS.')
    with instance_lock(settings.db_path.with_suffix('.lock')):
        store = Store(settings.db_path)
        try:
            store.recover()
            p = Panel(settings,SouPopular(settings.api_key),store)
            app = build_app(p)
            app.run_polling(allowed_updates=['message','callback_query'],drop_pending_updates=False,bootstrap_retries=0)
        finally:
            store.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError,RuntimeError) as exc:
        print(f'Erro de configuração: {exc}',file=sys.stderr)
        sys.exit(1)
    except TelegramError as exc:
        print(f'Falha ao iniciar a conexão Telegram ({type(exc).__name__}). Confira o token e a rede.',file=sys.stderr)
        sys.exit(1)
