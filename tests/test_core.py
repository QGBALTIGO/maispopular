"""Testes offline: nenhum pedido ou solicitação é enviado a um provedor real."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx
from config import Settings, boolean, ids
from domain import Service, build_payload, capability, decimal_value, money, validate_target
from engine import Panel
from provider import SouPopular, ProviderError, UncertainWrite
from storage import Store


RAW = {'service':42,'name':'Serviço teste','category':'Categoria','type':'Default',
       'rate':'10.00','min':'10','max':'10000','refill':True,'cancel':True}


def service(**changes):
    return Service.parse({**RAW,**changes})


def settings(path: Path, **changes):
    return Settings('123456:dummy_for_tests','dummy_key',frozenset({11,22}),frozenset(),path,
                    changes.get('dry_run',True),changes.get('max_order_cost',Decimal('100')),120,'Painel teste')


class DomainTests(unittest.TestCase):
    def test_default_rate_per_thousand(self):
        payload,cost = build_payload(service(),'https://example.com/post','250')
        self.assertEqual(cost,Decimal('2.50'))
        self.assertEqual(payload,{'service':42,'link':'https://example.com/post','quantity':250})

    def test_comments_below_minimum(self):
        with self.assertRaises(ValueError):
            build_payload(service(type='Custom Comments'),'@teste','Um\n\nDois')

    def test_comments_no_quantity_field(self):
        payload,cost = build_payload(service(type='Custom Comments',min='1'),'@teste','Um\nDois')
        self.assertNotIn('quantity',payload)
        self.assertEqual(cost,Decimal('0.02'))

    def test_package_flat_rate(self):
        payload,cost = build_payload(service(type='Package'),'@teste')
        self.assertNotIn('quantity',payload)
        self.assertEqual(cost,Decimal('10'))

    def test_poll_answer(self):
        payload,cost = build_payload(service(type='Poll'),'https://example.com/p','100','3')
        self.assertEqual(payload['answer_number'],3)
        self.assertEqual(cost,Decimal('1'))

    def test_poll_invalid_answer(self):
        for value in ('0','a','-1',''):
            with self.subTest(value=value),self.assertRaises(ValueError):
                build_payload(service(type='Poll'),'@teste','100',value)

    def test_invalid_quantities(self):
        for value in ('0','-1','10001','1.000','1,000','2.5','9','abc'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                build_payload(service(),'@teste',value)

    def test_subscription_not_silently_treated_as_default(self):
        with self.assertRaises(ValueError):
            build_payload(service(type='Subscriptions'),'@teste','100')

    def test_invalid_money_rejected(self):
        for value in ('NaN','Infinity','-1','bad'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                decimal_value(value)

    def test_small_money_not_rounded_to_zero(self):
        self.assertEqual(money('0.000001','BRL'),'BRL 0,00001')

    def test_boolean_false_not_truthy_string(self):
        self.assertIs(capability('false'),False)
        self.assertIs(capability('0'),False)
        self.assertIsNone(capability(None))
        self.assertTrue(capability('true'))

    def test_invalid_targets(self):
        for target in ('','file:///etc/passwd','javascript:alert(1)','https://127.0.0.1/x',
                       'http://localhost/a','https://user:pass@example.com','https://example.com:999/a','abc def'):
            with self.subTest(target=target),self.assertRaises(ValueError):
                validate_target(target)

    def test_valid_targets(self):
        for target in ('@conta','https://t.me/canal','https://example.com/a?b=1'):
            self.assertEqual(validate_target(target),target)

    def test_config_fail_closed(self):
        self.assertEqual(ids(''),frozenset())
        with self.assertRaises(ValueError):
            ids('-1')
        with self.assertRaises(ValueError):
            boolean('maybe')


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()

    def api(self, handler):
        async def wrapped(request):
            self.calls.append(parse_qs(request.content.decode()))
            self.assertEqual(request.url,'https://soupopular.net/api/v2')
            self.assertEqual(request.method,'POST')
            self.assertIn('application/x-www-form-urlencoded',request.headers['content-type'])
            return handler(request)
        client = SouPopular('super_secret_key',transport=httpx.MockTransport(wrapped))
        self.clients.append(client)
        return client

    async def test_service_list_and_cache(self):
        api = self.api(lambda request:httpx.Response(200,json=[RAW]))
        self.assertEqual((await api.services())[0].id,42)
        await api.services()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0]['action'],['services'])
        self.assertEqual(self.calls[0]['key'],['super_secret_key'])

    async def test_status_uses_order_not_translated_or_service(self):
        api = self.api(lambda request:httpx.Response(200,json={'status':'Pending'}))
        await api.status(123)
        self.assertEqual(self.calls[0]['order'],['123'])
        self.assertNotIn('service',self.calls[0])
        self.assertNotIn('pedido',self.calls[0])

    async def test_multi_status_uses_orders(self):
        api = self.api(lambda request:httpx.Response(200,json={'1':{'status':'Completed'}}))
        await api.multi_status([1,2])
        self.assertEqual(self.calls[0]['orders'],['1,2'])

    async def test_add_reads_provider_id(self):
        api = self.api(lambda request:httpx.Response(200,json={'order':77}))
        self.assertEqual(await api.add({'service':42,'link':'@teste','quantity':100}),'77')
        self.assertEqual(self.calls[0]['action'],['add'])

    async def test_add_timeout_is_uncertain_and_not_retried(self):
        def handler(request):
            raise httpx.ReadTimeout('timeout',request=request)
        api = self.api(handler)
        with self.assertRaises(UncertainWrite):
            await api.add({'service':42})
        self.assertEqual(len(self.calls),1)

    async def test_add_5xx_not_retried(self):
        api = self.api(lambda request:httpx.Response(503,text='unavailable'))
        with self.assertRaises(UncertainWrite):
            await api.add({'service':42})
        self.assertEqual(len(self.calls),1)

    async def test_missing_order_id_uncertain(self):
        api = self.api(lambda request:httpx.Response(200,json={'ok':True}))
        with self.assertRaises(UncertainWrite):
            await api.add({'service':42})

    async def test_bad_json_write_uncertain(self):
        api = self.api(lambda request:httpx.Response(200,text='<html>Oops</html>'))
        with self.assertRaises(UncertainWrite):
            await api.add({'service':42})

    async def test_explicit_error_redacts_key(self):
        api = self.api(lambda request:httpx.Response(200,json={'error':'Invalid super_secret_key'}))
        with self.assertRaises(ProviderError) as cm:
            await api.add({'service':42})
        self.assertNotIn('super_secret_key',str(cm.exception))
        self.assertNotIsInstance(cm.exception,UncertainWrite)

    async def test_reads_can_retry(self):
        def handler(request):
            if len(self.calls) < 3:
                return httpx.Response(503)
            return httpx.Response(200,json={'balance':'10','currency':'BRL'})
        api = self.api(handler)
        with patch('provider.asyncio.sleep',new=AsyncMock()):
            result = await api.balance()
        self.assertEqual(result['currency'],'BRL')
        self.assertEqual(len(self.calls),3)

    async def test_redirect_does_not_forward_key(self):
        api = self.api(lambda request:httpx.Response(302,headers={'Location':'https://other.example/'}))
        with self.assertRaises(ProviderError):
            await api.balance()
        self.assertEqual(len(self.calls),1)

    async def test_refill_actions_use_english_fields(self):
        api = self.api(lambda request:httpx.Response(200,json={'refill':55,'status':'Pending'}))
        self.assertEqual(await api.refill(77),'55')
        await api.refill_status(55)
        self.assertEqual(self.calls[0]['action'],['refill'])
        self.assertEqual(self.calls[1]['action'],['refill_status'])
        self.assertEqual(self.calls[1]['refill'],['55'])

    async def test_balance_currency_not_assumed_brl(self):
        api = self.api(lambda request:httpx.Response(200,json={'balance':'100','currency':'USD'}))
        self.assertEqual((await api.balance())['currency'],'USD')

    async def test_invalid_service_skipped(self):
        api = self.api(lambda request:httpx.Response(200,json=[{'broken':1},RAW]))
        self.assertEqual(len(await api.services()),1)

    async def test_bad_ids_rejected_without_network(self):
        api = self.api(lambda request:httpx.Response(200,json={}))
        with self.assertRaises(ValueError):
            await api.multi_status([])
        with self.assertRaises(ValueError):
            await api.status(-1)
        self.assertEqual(len(self.calls),0)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'test.sqlite3'
        self.store = Store(self.path)
        self.api = AsyncMock(spec=SouPopular)
        self.api.services.return_value = [service()]
        self.api.balance.return_value = {'balance':'100','currency':'BRL'}
        self.api.add.return_value = '900'
        self.api.refill.return_value = '12'
        self.api.cancel.return_value = [{'order':900,'cancel':1}]
        self.p = Panel(settings(self.path),self.api,self.store)

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    async def quote(self):
        return await self.p.quote(11,42,'@teste','100')

    async def real_order(self):
        self.p.settings = replace(self.p.settings,dry_run=False)
        row = await self.quote()
        return await self.p.submit(row['id'],11)

    async def test_dry_run_never_calls_add(self):
        row = await self.quote()
        result = await self.p.submit(row['id'],11)
        self.assertEqual(result['state'],'SIMULATED')
        self.api.add.assert_not_awaited()

    async def test_real_double_click_sends_once(self):
        result = await self.real_order()
        await self.p.submit(result['id'],11)
        self.api.add.assert_awaited_once()
        self.assertEqual(result['provider_id'],'900')

    async def test_concurrent_double_click_sends_once(self):
        import asyncio
        self.p.settings = replace(self.p.settings,dry_run=False)
        row = await self.quote()
        await asyncio.gather(self.p.submit(row['id'],11),self.p.submit(row['id'],11))
        self.api.add.assert_awaited_once()

    async def test_unauthorized_user(self):
        with self.assertRaises(PermissionError):
            await self.p.quote(99,42,'@teste','100')
        self.api.add.assert_not_awaited()

    async def test_other_admin_cannot_use_order(self):
        row = await self.quote()
        with self.assertRaises(ValueError):
            await self.p.submit(row['id'],22)
        self.assertIsNone(self.store.order(row['id'],22))

    async def test_price_change_invalidates_quote(self):
        row = await self.quote()
        self.api.services.return_value = [service(rate='12')]
        with self.assertRaises(ValueError):
            await self.p.submit(row['id'],11)
        self.assertEqual(self.store.order(row['id'],11)['state'],'EXPIRED')
        self.api.add.assert_not_awaited()

    async def test_currency_change_invalidates_quote(self):
        row = await self.quote()
        self.api.balance.return_value = {'balance':'100','currency':'USD'}
        with self.assertRaises(ValueError):
            await self.p.submit(row['id'],11)
        self.api.add.assert_not_awaited()

    async def test_insufficient_balance_blocks_real(self):
        self.p.settings = replace(self.p.settings,dry_run=False)
        row = await self.quote()
        self.api.balance.return_value = {'balance':'0','currency':'BRL'}
        with self.assertRaises(ValueError):
            await self.p.submit(row['id'],11)
        self.api.add.assert_not_awaited()

    async def test_limit_blocks_quote(self):
        self.p.settings = replace(self.p.settings,max_order_cost=Decimal('0.5'))
        with self.assertRaises(ValueError):
            await self.quote()

    async def test_mode_change_invalidates_quote(self):
        row = await self.quote()
        self.p.settings = replace(self.p.settings,dry_run=False)
        with self.assertRaises(ValueError):
            await self.p.submit(row['id'],11)
        self.api.add.assert_not_awaited()

    async def test_timeout_marks_unknown_and_never_resubmits(self):
        self.p.settings = replace(self.p.settings,dry_run=False)
        row = await self.quote()
        self.api.add.side_effect = UncertainWrite('timeout')
        result = await self.p.submit(row['id'],11)
        await self.p.submit(row['id'],11)
        self.assertEqual(result['state'],'UNKNOWN')
        self.api.add.assert_awaited_once()

    async def test_explicit_rejection_not_unknown(self):
        self.p.settings = replace(self.p.settings,dry_run=False)
        row = await self.quote()
        self.api.add.side_effect = ProviderError('Saldo insuficiente')
        result = await self.p.submit(row['id'],11)
        self.assertEqual(result['state'],'REJECTED')

    async def test_new_quote_invalidates_old(self):
        first = await self.quote()
        await self.quote()
        self.assertEqual(self.store.order(first['id'],11)['state'],'ABORTED')

    async def test_expired_cannot_claim(self):
        row = await self.quote()
        with self.store.db:
            self.store.db.execute('UPDATE orders SET expires_at=0 WHERE id=?',(row['id'],))
        with self.assertRaises(ValueError):
            await self.p.submit(row['id'],11)
        self.api.add.assert_not_awaited()

    async def test_atomic_claim_can_only_succeed_once(self):
        row = await self.quote()
        self.assertTrue(self.store.claim_order(row['id'],11))
        self.assertFalse(self.store.claim_order(row['id'],11))

    async def test_restart_recovers_sending_to_unknown(self):
        row = await self.quote()
        self.store.claim_order(row['id'],11)
        self.store.recover()
        self.assertEqual(self.store.order(row['id'],11)['state'],'UNKNOWN')

    async def test_duplicate_active_target_blocked(self):
        await self.real_order()
        other = await self.quote()
        with self.assertRaises(ValueError):
            await self.p.submit(other['id'],11)
        self.api.add.assert_awaited_once()

    async def test_completed_allows_new_order(self):
        first = await self.real_order()
        self.store.update_status(first['id'],{'status':'Completed','charge':'1'})
        self.api.add.return_value = '901'
        other = await self.quote()
        result = await self.p.submit(other['id'],11)
        self.assertEqual(result['provider_id'],'901')

    async def test_service_allowlist_enforced(self):
        self.p.settings = replace(self.p.settings,allowed_services=frozenset({99}))
        with self.assertRaises(ValueError):
            await self.quote()

    async def test_refill_double_click_sends_once(self):
        row = await self.real_order()
        action = await self.p.prepare_action(row['id'],11,'refill')
        result = await self.p.submit_action(action['id'],11)
        await self.p.submit_action(action['id'],11)
        self.api.refill.assert_awaited_once()
        self.assertEqual(json.loads(result['result_json'])['refill'],'12')

    async def test_cancel_accepted_is_request_not_completed_order(self):
        row = await self.real_order()
        action = await self.p.prepare_action(row['id'],11,'cancel')
        result = await self.p.submit_action(action['id'],11)
        self.assertEqual(result['state'],'SUBMITTED')
        self.assertEqual(self.store.order(row['id'],11)['provider_status'],'awaiting')

    async def test_action_false_capability_blocks(self):
        row = await self.real_order()
        self.api.services.return_value = [service(refill=False)]
        with self.assertRaises(ValueError):
            await self.p.prepare_action(row['id'],11,'refill')
        self.api.refill.assert_not_awaited()

    async def test_unknown_refill_blocks_new_refill(self):
        row = await self.real_order()
        self.api.refill.side_effect = UncertainWrite('timeout')
        action = await self.p.prepare_action(row['id'],11,'refill')
        result = await self.p.submit_action(action['id'],11)
        other = await self.p.prepare_action(row['id'],11,'refill')
        with self.assertRaises(ValueError):
            await self.p.submit_action(other['id'],11)
        self.assertEqual(result['state'],'UNKNOWN')
        self.api.refill.assert_awaited_once()

    async def test_simulated_action_never_mutates_provider(self):
        row = await self.real_order()
        self.p.settings = replace(self.p.settings,dry_run=True)
        action = await self.p.prepare_action(row['id'],11,'cancel')
        result = await self.p.submit_action(action['id'],11)
        self.assertEqual(result['state'],'SIMULATED')
        self.api.cancel.assert_not_awaited()

    async def test_terminal_notification_pending_remains_watched(self):
        row = await self.real_order()
        self.store.update_status(row['id'],{'status':'Completed'})
        self.assertEqual(len(self.store.watched()),1)
        self.store.notified(row['id'],'Completed')
        self.assertEqual(self.store.watched(),[])


if __name__ == '__main__':
    unittest.main()
