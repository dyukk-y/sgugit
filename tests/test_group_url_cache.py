import json
import tempfile
import unittest
from pathlib import Path

from app.providers.site import (
    GROUP_URL_CACHE_TTL,
    _load_group_url_cache,
    _save_group_url_cache,
)


class GroupUrlCacheTests(unittest.TestCase):
    def test_fresh_cache_returns_validated_groups_without_rescan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "group_urls.json"
            groups = [("ИС-11", "https://sgugit.ru/raspisanie/group/1616/")]
            _save_group_url_cache(path, groups, now=10_000)

            cached, fresh = _load_group_url_cache(path, now=10_100)

            self.assertEqual(cached, groups)
            self.assertTrue(fresh)

    def test_expired_cache_requires_rescan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "group_urls.json"
            _save_group_url_cache(
                path,
                [("ИС-11", "https://sgugit.ru/raspisanie/group/1616/")],
                now=10_000,
            )

            cached, fresh = _load_group_url_cache(
                path, now=10_000 + GROUP_URL_CACHE_TTL
            )

            self.assertEqual(len(cached), 1)
            self.assertFalse(fresh)

    def test_invalid_entries_are_ignored_without_breaking_valid_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "group_urls.json"
            path.write_text(
                json.dumps({
                    "checked_at": 10_000,
                    "groups": [
                        ["ИС-11", "https://sgugit.ru/raspisanie/group/1616/"],
                        ["bad entry"],
                        None,
                        ["not a group", "https://sgugit.ru/teachers/"],
                    ],
                }),
                encoding="utf-8",
            )

            cached, fresh = _load_group_url_cache(path, now=10_100)

            self.assertEqual(cached, [
                ("ИС-11", "https://sgugit.ru/raspisanie/group/1616/")
            ])
            self.assertTrue(fresh)

    def test_legacy_cache_is_read_but_marked_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "group_urls.json"
            path.write_text(
                json.dumps({"groups": [
                    ["ИС-11", "https://sgugit.ru/raspisanie/group/1616/"]
                ]}),
                encoding="utf-8",
            )

            cached, fresh = _load_group_url_cache(path, now=10_100)

            self.assertEqual(len(cached), 1)
            self.assertFalse(fresh)


if __name__ == "__main__":
    unittest.main()
