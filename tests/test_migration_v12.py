import asyncio
import unittest

from app.db.core import Database
from app.db.schema import migrate


class MigrationV14Tests(unittest.TestCase):
    def test_v14_adds_group_settings_and_preserves_existing_rows(self):
        async def run():
            db = Database("sqlite:///:memory:")
            await db.connect()
            try:
                await migrate(db)
                # Seed representative pre-v12 production rows before simulating an upgrade.
                await db.execute("INSERT INTO settings (k, v) VALUES (?, ?)", "keep_me", "unchanged")
                await db.execute("INSERT INTO groups (id, name, norm, created_at) VALUES (?, ?, ?, ?)", 7, "ИС-21", "ис-21", 100)
                await db.execute("INSERT INTO users (id, group_id, fio, created_at, last_seen) VALUES (?, ?, ?, ?, ?)", 101, 7, "Иванов Иван", 110, 120)
                await db.execute("INSERT INTO lessons (id, group_id, day, num, start_t, end_t, subject) VALUES (?, ?, ?, ?, ?, ?, ?)", 201, 7, "2026-11-16", 1, "09:00", "10:30", "Математика")
                await db.execute("INSERT INTO chats (chat_id, title, group_id) VALUES (?, ?, ?)", -100123, "ИС-21", 7)
                await db.execute("DROP TABLE group_schedule_changes")
                await db.execute("DROP TABLE teacher_accounts")
                await db.execute("ALTER TABLE chats DROP COLUMN cleanup_on")
                await db.execute("ALTER TABLE chats DROP COLUMN private_questions")
                await db.execute("ALTER TABLE chats DROP COLUMN notifications_on")
                await db.execute("UPDATE meta SET v = ? WHERE k = ?", "11", "schema_version")

                version = await migrate(db)
                saved = await db.scalar("SELECT v FROM settings WHERE k = ?", "keep_me")
                table = await db.scalar(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                    "group_schedule_changes")
                index = await db.scalar(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = ?",
                    "ix_gsc_group_day_status")
                self.assertEqual(version, 15)
                self.assertEqual(saved, "unchanged")
                self.assertEqual(await db.scalar("SELECT fio FROM users WHERE id = ?", 101), "Иванов Иван")
                self.assertEqual(await db.scalar("SELECT subject FROM lessons WHERE id = ?", 201), "Математика")
                self.assertEqual(await db.scalar("SELECT title FROM chats WHERE chat_id = ?", -100123), "ИС-21")
                self.assertEqual(await db.scalar("SELECT name FROM groups WHERE id = ?", 7), "ИС-21")
                self.assertEqual(table, 1)
                self.assertEqual(index, 1)
                teacher_accounts = await db.scalar(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                    "teacher_accounts")
                self.assertEqual(teacher_accounts, 1)
                columns = await db.fetchall("PRAGMA table_info(chats)")
                names = {row["name"] for row in columns}
                self.assertIn("notifications_on", names)
                self.assertIn("cleanup_on", names)
                self.assertIn("private_questions", names)
            finally:
                await db.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
