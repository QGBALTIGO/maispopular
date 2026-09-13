import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from broadcasts import poll_broadcasts
from storage import Store


class BroadcastWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "db.sqlite3")
        self.store.register_user(1, "one", "One")
        self.store.register_user(2, "two", "Two")
        settings = SimpleNamespace(webapp_url=lambda: "https://shop.example")
        panel = SimpleNamespace(store=self.store, settings=settings)
        self.bot = AsyncMock()
        self.context = SimpleNamespace(
            bot=self.bot, application=SimpleNamespace(bot_data={"panel": panel})
        )

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_worker_delivers_persistent_job_and_finishes(self):
        job = self.store.create_broadcast(9, "request-1", "Olá!", "Abrir", "catalog")
        await poll_broadcasts(self.context)
        await poll_broadcasts(self.context)
        self.assertEqual(self.bot.send_message.await_count, 2)
        result = next(row for row in self.store.broadcasts() if row["id"] == job["id"])
        self.assertEqual((result["status"], result["sent"], result["failed"]), ("COMPLETED", 2, 0))
        self.assertTrue(all(call.kwargs["reply_markup"] for call in self.bot.send_message.await_args_list))

    async def test_cancel_stops_unsent_recipients(self):
        job = self.store.create_broadcast(9, "request-2", "Aviso", "", "none")
        self.store.cancel_broadcast(job["id"])
        await poll_broadcasts(self.context)
        self.bot.send_message.assert_not_awaited()
