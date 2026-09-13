import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

from raffle import _join_keyboard, _missing_channels_text, _run_draw, _show_status
from recovery import poll_recovery
from storage import Store


class BotAssemblyTests(unittest.TestCase):
    def test_application_registers_recovery_and_raffle_handlers(self):
        from bot import build_app

        panel = SimpleNamespace(
            settings=SimpleNamespace(bot_token="123456:dummy", poll_seconds=60)
        )
        app = build_app(panel)
        patterns = [
            getattr(handler, "pattern", None)
            for handlers in app.handlers.values()
            for handler in handlers
        ]
        self.assertTrue(any(pattern and pattern.pattern == r"^raffle:" for pattern in patterns))
        self.assertTrue(any(pattern and pattern.pattern == r"^recovery:" for pattern in patterns))


class RaffleStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "db.sqlite3")
        with self.store.db:
            self.store.db.execute(
                "UPDATE raffle_campaigns SET scheduled_at=4102444800,status='OPEN' WHERE id='set26'"
            )
        for user_id in range(1, 9):
            self.store.register_user(user_id, f"user{user_id}", f"User {user_id}")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def join(self, user_id, referrer=0):
        self.store.join_raffle(user_id, referrer)
        return self.store.verify_raffle_participant(user_id)

    def test_six_dice_values_and_one_base_card_are_idempotent(self):
        first = self.join(1)
        second = self.store.verify_raffle_participant(1)
        self.assertEqual(len(first["cards"]), 1)
        self.assertEqual(len(second["cards"]), 1)
        values = [int(value) for value in first["cards"][0]["numbers"].split(",")]
        self.assertEqual(len(values), 6)
        self.assertTrue(all(1 <= value <= 6 for value in values))

    def test_valid_referral_awards_exactly_one_bonus_card(self):
        self.join(1)
        self.store.join_raffle(2, 1)
        verified = self.store.verify_raffle_participant(2)
        self.assertEqual(verified["bonusReferrer"], 1)
        self.assertEqual(len(self.store.raffle_summary(1)["cards"]), 2)
        repeated = self.store.verify_raffle_participant(2)
        self.assertEqual(repeated["bonusReferrer"], 0)
        self.assertEqual(len(self.store.raffle_summary(1)["cards"]), 2)

    def test_self_or_late_referral_does_not_bind(self):
        self.store.join_raffle(1, 1)
        self.store.join_raffle(2, 1)  # referrer is not eligible yet
        self.store.verify_raffle_participant(1)
        self.store.verify_raffle_participant(2)
        self.assertEqual(self.store.raffle_summary(1)["referrals"], 0)

    def test_exact_then_nearest_ranking_and_unique_winners(self):
        for user_id in range(1, 7):
            self.join(user_id)
        with self.store.db:
            cards = self.store.db.execute(
                "SELECT id FROM raffle_cards WHERE campaign_id='set26' ORDER BY user_id"
            ).fetchall()
            # Ensure deterministic known candidates without violating the campaign uniqueness rule.
            known = ["1,2,3,4,5,6", "1,2,3,4,5,5", "6,6,6,6,6,6", "2,2,2,2,2,2", "3,3,3,3,3,3", "4,4,4,4,4,4"]
            for row in cards:
                self.store.db.execute("UPDATE raffle_cards SET numbers=? WHERE id=?", (f"9,9,9,9,9,{row['id']}", row["id"]))
            for row, numbers in zip(cards, known):
                self.store.db.execute("UPDATE raffle_cards SET numbers=? WHERE id=?", (numbers, row["id"]))
        exact = self.store.raffle_candidates("set26", [1, 2, 3, 4, 5, 6], 1)[0]
        self.assertEqual((exact["user_id"], exact["distance"]), (1, 0))
        self.store.save_raffle_winner("set26", 1, exact, [1, 2, 3, 4, 5, 6], list(range(1, 7)))
        nearest = self.store.raffle_candidates("set26", [1, 2, 3, 4, 5, 6], 2)[0]
        self.assertEqual(nearest["user_id"], 2)

    def test_rolls_and_winner_writes_are_restart_safe(self):
        for user_id in range(1, 6):
            self.join(user_id)
        with self.store.db:
            self.store.db.execute("UPDATE raffle_campaigns SET scheduled_at=0 WHERE id='set26'")
        self.assertTrue(self.store.begin_raffle("set26"))
        for position, value in enumerate([1, 6, 2, 5, 3, 4], 1):
            self.store.save_raffle_roll("set26", 1, position, value, 100 + position)
            self.store.save_raffle_roll("set26", 1, position, 1, 999)
        rolls = self.store.raffle_rolls("set26", 1)
        self.assertEqual([row["value"] for row in rolls], [1, 6, 2, 5, 3, 4])
        candidate = self.store.raffle_candidates("set26", [1, 6, 2, 5, 3, 4], 1)[0]
        self.assertTrue(self.store.save_raffle_winner("set26", 1, candidate, [1, 6, 2, 5, 3, 4], [101, 102, 103, 104, 105, 106]))
        self.assertFalse(self.store.save_raffle_winner("set26", 1, candidate, [6] * 6, [9] * 6))


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "db.sqlite3")
        self.store.register_user(7, "ana", "Ana Cliente")
        settings = SimpleNamespace(webapp_url=lambda: "https://shop.example")
        panel = SimpleNamespace(store=self.store, settings=settings)
        self.bot = AsyncMock()
        self.context = SimpleNamespace(
            bot=self.bot, application=SimpleNamespace(bot_data={"panel": panel})
        )

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_schedule_is_30_minutes_then_24_hours(self):
        row = self.store.track_interest(7, "Instagram", "Seguidores", 42, now=1000)
        self.assertIsNone(self.store.claim_interest_notification(now=2799))
        claimed, stage = self.store.claim_interest_notification(now=2800)
        self.assertEqual((claimed["id"], stage), (row["id"], 1))
        self.store.finish_interest_notification(row["id"], 1, True)
        self.assertIsNone(self.store.claim_interest_notification(now=87399))
        claimed, stage = self.store.claim_interest_notification(now=87400)
        self.assertEqual(stage, 2)

    async def test_worker_sends_personalized_reminder_and_marks_stage(self):
        row = self.store.track_interest(7, "Instagram", "Seguidores", 42, now=1000)
        with self.store.db:
            self.store.db.execute(
                "UPDATE interest_events SET first_due_at=0,second_due_at=4102444800 WHERE id=?",
                (row["id"],),
            )
        await poll_recovery(self.context)
        self.bot.send_message.assert_awaited_once()
        call = self.bot.send_message.await_args
        self.assertIn("Ana", call.args[1])
        self.assertIn("Seguidores", call.args[1])
        self.assertIn("service=42", call.kwargs["reply_markup"].inline_keyboard[0][0].web_app.url)
        saved = self.store.db.execute("SELECT * FROM interest_events WHERE id=?", (row["id"],)).fetchone()
        self.assertGreater(saved["first_sent_at"], 0)

    async def test_new_interest_supersedes_old_and_optout_stops_tracking(self):
        first = self.store.track_interest(7, "Instagram", "Seguidores", 42, now=1000)
        second = self.store.track_interest(7, "TikTok", "Curtidas", 55, now=1100)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.store.db.execute("SELECT status FROM interest_events WHERE id=?", (first["id"],)).fetchone()[0], "SUPERSEDED")
        self.store.recovery_opt_out(7)
        self.assertIsNone(self.store.track_interest(7, "YouTube", "Visualizações", 60, now=1200))


class RaffleDrawTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "db.sqlite3")
        with self.store.db:
            self.store.db.execute(
                "UPDATE raffle_campaigns SET scheduled_at=0,status='OPEN' WHERE id='set26'"
            )
        for user_id in range(1, 6):
            self.store.register_user(user_id, f"user{user_id}", f"User {user_id}")
            with self.store.db:
                self.store.db.execute(
                    "INSERT INTO raffle_participants(campaign_id,user_id,status,joined_at,verified_at) VALUES('set26',?,'ELIGIBLE',1,1)",
                    (user_id,),
                )
                self.store._create_raffle_card("set26", user_id, "BASE")
        self.assertTrue(self.store.begin_raffle("set26"))
        panel = SimpleNamespace(store=self.store, settings=SimpleNamespace(admin_ids=frozenset()))
        self.bot = AsyncMock()
        values = [1, 2, 3, 4, 5, 6] * 5
        self.bot.send_dice.side_effect = [
            SimpleNamespace(dice=SimpleNamespace(value=value), message_id=100 + index)
            for index, value in enumerate(values)
        ]
        self.context = SimpleNamespace(
            bot=self.bot, application=SimpleNamespace(bot_data={"panel": panel})
        )

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_five_rounds_use_thirty_official_dice_and_unique_people(self):
        with patch("raffle.membership", new=AsyncMock(return_value=(True, []))), patch(
            "raffle.asyncio.sleep", new=AsyncMock()
        ):
            await _run_draw(self.context, self.store.raffle_campaign("set26"))
        self.assertEqual(self.bot.send_dice.await_count, 30)
        winners = self.store.raffle_admin_summary("set26")["winners"]
        self.assertEqual(len(winners), 5)
        self.assertEqual(len({row["user_id"] for row in winners}), 5)
        self.assertEqual(self.store.raffle_campaign("set26")["status"], "COMPLETED")

    async def test_participant_panel_has_invite_catalog_and_clean_channel_links(self):
        panel = self.context.application.bot_data["panel"]
        panel.settings = SimpleNamespace(
            admin_ids=frozenset(),
            bot_username="MaisPopularBot",
            webapp_url=lambda: "https://shop.example",
        )
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=1),
            effective_message=SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )
        await _show_status(update, self.context)
        markup = update.effective_message.reply_text.await_args.kwargs["reply_markup"]
        self.assertEqual([button.text for button in markup.inline_keyboard[0]], ["📨 Convidar amigos", "🛒 Abrir catálogo"])
        self.assertEqual(markup.inline_keyboard[0][1].web_app.url, "https://shop.example")
        missing = _missing_channels_text(["Central de Animes", "Mais Popular"])
        self.assertIn("https://t.me/centraldeanimes_baltigo", missing)
        self.assertIn("https://t.me/MaisPopular", missing)
        self.assertEqual(_join_keyboard().inline_keyboard[-1][0].text, "✅ Confirmar participação")
