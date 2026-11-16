import unittest

from app.bot.background import _sync_is_fresh


class StartupSyncFreshnessTests(unittest.TestCase):
    def test_recent_success_skips_startup_download(self):
        self.assertTrue(_sync_is_fresh(last_ok=9_950, max_age=1_800, now=10_000))

    def test_old_success_requires_refresh(self):
        self.assertFalse(_sync_is_fresh(last_ok=8_000, max_age=1_800, now=10_000))

    def test_missing_success_requires_initial_sync(self):
        self.assertFalse(_sync_is_fresh(last_ok=0, max_age=1_800, now=10_000))

    def test_nonpositive_window_never_marks_cache_fresh(self):
        self.assertFalse(_sync_is_fresh(last_ok=9_999, max_age=0, now=10_000))


if __name__ == "__main__":
    unittest.main()
