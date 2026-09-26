import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:offline-test-token")
os.environ.setdefault("GIGACHAT_CREDENTIALS", "offline-test")
import bot
from context_memory import ConversationMemory
from test_context import message


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        silent = patch("builtins.print")
        silent.start()
        self.addCleanup(silent.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.memory = ConversationMemory(Path(self.tmp.name) / "memory.sqlite3")
        self.context = NS(application=NS(bot_data={"conversation_memory": self.memory}),
                          bot=NS(id=999, username="comment_bot", send_chat_action=AsyncMock()))

    def require_integration(self):
        self.assertTrue(hasattr(bot, "collect_context"), "Bot has no context collector")

    async def test_passive_messages_are_saved_without_answer(self):
        self.require_integration()
        m = message(1, text="We discussed a trip")
        m.reply_text = AsyncMock()
        update = NS(message=m)
        await bot.collect_context(update, self.context)
        with patch.object(bot, "run_with_one_retry", new=AsyncMock()) as generate:
            await bot.handle_text(update, self.context)
            generate.assert_not_called()
        self.assertIn("trip", self.memory.history(self.memory.scope_for(m)))
        m.reply_text.assert_not_called()

    async def test_text_uses_prior_messages_and_saves_sent_answer(self):
        self.require_integration()
        earlier = message(1, text="Our destination is Kazan", private=True)
        await bot.collect_context(NS(message=earlier), self.context)
        current = message(2, text="What can we see there?", private=True)
        sent = message(3, text="Visit the Kremlin", private=True)
        current.reply_text = AsyncMock(return_value=sent)
        await bot.collect_context(NS(message=current), self.context)
        with patch.object(bot, "run_with_one_retry", new=AsyncMock(return_value=sent.text)) as generate:
            await bot.handle_text(NS(message=current), self.context)
            self.assertIn("Kazan", generate.call_args.args[-1])
            self.assertNotIn("What can we see there", generate.call_args.args[-1])
        self.assertIn("Visit the Kremlin", self.memory.history(self.memory.scope_for(current)))

    async def test_photo_uses_history(self):
        self.require_integration()
        self.memory.record(message(1, text="This is Kazan", private=True))
        m = message(2, text=None, private=True)
        photo = NS(get_file=AsyncMock(return_value=NS(download_to_drive=AsyncMock())))
        m.photo = [photo]
        m.media_group_id = None
        m.reply_text = AsyncMock(return_value=message(3, text="Nice view", private=True))
        await bot.collect_context(NS(message=m), self.context)
        with patch.object(bot, "run_with_one_retry", new=AsyncMock(return_value="Nice view")) as generate:
            await bot.handle_photo(NS(message=m), self.context)
            self.assertIn("Kazan", generate.call_args.args[-1])

    async def test_failed_generation_is_not_saved_as_bot_answer(self):
        self.require_integration()
        m = message(1, private=True)
        m.reply_text = AsyncMock()
        await bot.collect_context(NS(message=m), self.context)
        with patch.object(bot, "run_with_one_retry", new=AsyncMock(side_effect=RuntimeError("offline"))):
            await bot.handle_text(NS(message=m), self.context)
        self.assertNotIn('"role": "assistant"', self.memory.history(self.memory.scope_for(m)))

    async def test_text_model_receives_context(self):
        self.require_integration()
        client = MagicMock()
        client.chat.return_value.choices = [NS(message=NS(content="answer"))]
        with patch.object(bot, "create_gigachat_client") as create:
            create.return_value.__enter__.return_value = client
            bot.generate_text_comment("current", '[{"text":"earlier Kazan"}]')
        self.assertIn("earlier Kazan", client.chat.call_args.args[0])

    async def test_image_model_receives_context_and_attachment(self):
        self.require_integration()
        image = Path(self.tmp.name) / "photo.jpg"
        image.write_bytes(b"offline image")
        client = MagicMock()
        client.upload_file.return_value.id_ = "image-id"
        client.chat.return_value.choices = [NS(message=NS(content="answer"))]
        with patch.object(bot, "create_gigachat_client") as create:
            create.return_value.__enter__.return_value = client
            bot.generate_image_comment(image, "caption", "earlier Kazan")
        sent = client.chat.call_args.args[0]["messages"][0]
        self.assertIn("earlier Kazan", sent["content"])
        self.assertEqual(sent["attachments"], ["image-id"])
        client.delete_file.assert_called_once_with("image-id")

    async def test_existing_reply_triggers_are_preserved(self):
        ordinary = message(1)
        self.assertFalse(bot.should_process_message(ordinary, self.context))
        self.assertTrue(bot.should_process_message(message(2, auto=True), self.context))
        self.assertTrue(bot.should_process_message(message(3, text="@comment_bot hello"), self.context))
        sent = message(4)
        sent.from_user.id = 999
        self.assertTrue(bot.should_process_message(message(5, reply=sent), self.context))

    async def test_collector_is_registered_before_reply_handlers(self):
        self.require_integration()
        builder = MagicMock()
        for name in ("token", "connect_timeout", "read_timeout", "get_updates_connect_timeout",
                     "get_updates_read_timeout", "proxy", "get_updates_proxy"):
            getattr(builder, name).return_value = builder
        with patch.object(bot.Application, "builder", return_value=builder):
            bot.main()
        app = builder.build.return_value
        self.assertTrue(any(call.kwargs.get("group") == -1 for call in app.add_handler.call_args_list))
        app.run_polling.assert_called_once_with(drop_pending_updates=True)

if __name__ == "__main__":
    unittest.main()
