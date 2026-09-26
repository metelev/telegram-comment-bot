import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS


def message(mid, chat=1, text="hello", reply=None, topic=None, auto=False, private=False):
    return NS(message_id=mid, chat_id=chat, chat=NS(type="private" if private else "supergroup"),
              text=text, caption=None, photo=[], message_thread_id=topic,
              is_topic_message=bool(topic), is_automatic_forward=auto,
              reply_to_message=reply, from_user=NS(id=7, full_name="Анна", is_bot=False), sender_chat=None)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("context_memory"),
                             "Persistent conversation memory has not been implemented")
        from context_memory import ConversationMemory
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "memory.sqlite3"
        self.memory = ConversationMemory(self.path)

    def test_history_survives_restart(self):
        m = message(1, private=True)
        scope = self.memory.record(m)
        from context_memory import ConversationMemory
        self.assertIn("hello", ConversationMemory(self.path).history(scope))

    def test_chats_and_topics_are_isolated(self):
        a = self.memory.record(message(1, text="secret A", topic=10))
        b = self.memory.record(message(2, text="secret B", topic=20))
        c = self.memory.record(message(1, chat=2, text="secret C", topic=10))
        self.assertEqual(len({a, b, c}), 3)
        self.assertNotIn("secret B", self.memory.history(a))
        self.assertNotIn("secret C", self.memory.history(a))

    def test_channel_posts_and_nested_replies_are_isolated_after_restart(self):
        post = message(100, text="first post", auto=True)
        a = self.memory.record(post)
        self.memory.record(message(200, text="other post", auto=True))
        reply = message(101, text="first comment", reply=post)
        self.assertEqual(self.memory.record(reply), a)
        from context_memory import ConversationMemory
        restarted = ConversationMemory(self.path)
        self.assertEqual(restarted.record(message(102, text="nested", reply=reply)), a)
        self.assertNotIn("other post", restarted.history(a))

    def test_reply_to_unseen_post_preserves_post(self):
        post = message(100, text="unseen root", auto=True)
        scope = self.memory.record(message(101, text="comment", reply=post))
        self.assertIn("unseen root", self.memory.history(scope))

    def test_unknown_reply_does_not_mix_general_chat(self):
        general = self.memory.record(message(1, text="general secret"))
        orphan = self.memory.record(message(5, reply=message(4, text="parent")))
        self.assertNotEqual(general, orphan)
        self.assertNotIn("general secret", self.memory.history(orphan))

    def test_only_latest_twenty_and_no_duplicate_updates(self):
        for i in range(30):
            scope = self.memory.record(message(i, text=f"entry {i}", private=True))
        self.memory.record(message(29, text="entry 29", private=True))
        items = json.loads(self.memory.history(scope, max_chars=100000))
        self.assertEqual(len(items), 20)
        self.assertEqual(items[0]["text"], "entry 10")

    def test_current_message_is_excluded(self):
        scope = self.memory.record(message(1, text="before", private=True))
        self.memory.record(message(2, text="current", private=True))
        history = self.memory.history(scope, exclude_message_id=2)
        self.assertIn("before", history)
        self.assertNotIn("current", history)

    def test_sent_bot_reply_retains_scope(self):
        scope = self.memory.record(message(1, auto=True))
        sent = message(2, text="bot answer")
        self.memory.record(sent, scope=scope, role="assistant")
        self.assertEqual(self.memory.record(message(3, reply=sent)), scope)
        self.assertIn('"role": "assistant"', self.memory.history(scope))

    def test_history_is_bounded_valid_json(self):
        for i in range(20):
            scope = self.memory.record(message(i, text="x" * 9000, private=True))
        history = self.memory.history(scope)
        self.assertLessEqual(len(history), 12000)
        self.assertTrue(json.loads(history))

    def test_old_photo_is_caption_not_image_file(self):
        m = message(1, text=None, private=True)
        m.photo = [object()]
        m.caption = "holiday"
        scope = self.memory.record(m)
        self.assertIn("holiday", self.memory.history(scope))
        self.assertIn("Фото", self.memory.history(scope))

if __name__ == "__main__":
    unittest.main()
