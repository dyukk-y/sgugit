import asyncio
import unittest

from app.db.core import Database
from app.db.schema import migrate


class MigrationV12Tests(unittest.TestCase):
    def test_v12_adds_only_new_table_and_preserves_existing_rows(self):
        async def run():
            db = Database("sqlite:///:memory:")
            await db.connect()
            try:
                await migrate(db)
                await db.execute("INSERT INTO settings (k, v) VALUES (?, ?)", "keep_me", "unchanged")
                await db.execute("DROP TABLE group_schedule_changes")
                await db.execute("DROP TABLE teacher_accounts")
                await db.execute("UPDATE meta SET v = ? WHERE k = ?", "11", "schema_version")

                version = await migrate(db)
                saved = await db.scalar("SELECT v FROM settings WHERE k = ?", "keep_me")
                table = await db.scalar(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                    "group_schedule_changes")
                index = await db.scalar(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = ?",
                    "ix_gsc_group_day_status")
                self.assertEqual(version, 13)
                self.assertEqual(saved, "unchanged")
                self.assertEqual(table, 1)
                self.assertEqual(index, 1)
                teacher_accounts = await db.scalar(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                    "teacher_accounts")
                self.assertEqual(teacher_accounts, 1)
            finally:
                await db.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
