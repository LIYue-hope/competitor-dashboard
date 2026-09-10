"""Tests for daily news-count snapshots (stdlib unittest, no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import snapshot_daily_news_counts as snapshot  # noqa: E402


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 10, 8, 0, tzinfo=tz)


class TestDailyNewsSnapshot(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.output = self.data / "daily_news_history.json"
        self.patches = [
            mock.patch.object(snapshot, "DATA", self.data),
            mock.patch.object(snapshot, "OUTPUT", self.output),
            mock.patch.object(snapshot, "datetime", _FixedDateTime),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def _write_source(self, filename, items):
        (self.data / filename).write_text(
            json.dumps({"items": items}), encoding="utf-8"
        )

    def _write_all_sources(self, items_by_key=None):
        items_by_key = items_by_key or {}
        for key, _label, filename in snapshot.SOURCES:
            # A non-news item marks a crawler response as available while
            # contributing no count from the tracked date range.
            self._write_source(filename, items_by_key.get(key, [{"published_at": ""}]))

    def _history(self):
        return json.loads(self.output.read_text(encoding="utf-8"))

    def _save_history(self, days):
        self.output.write_text(json.dumps({"days": days}), encoding="utf-8")

    def test_first_snapshot_creates_counts_and_zero_news_today(self):
        self._write_all_sources({"dm": [{"published_at": "2026-09-09 12:00:00"}]})
        snapshot.main()
        days = {row["date"]: row["counts"] for row in self._history()["days"]}
        self.assertEqual(days["2026-09-09"]["dm"], 1)
        self.assertEqual(days["2026-09-10"], {key: 0 for key, _label, _file in snapshot.SOURCES})

    def test_repeat_run_is_idempotent(self):
        self._write_all_sources({"dm": [{"published_at": "2026-09-09 12:00:00"}]})
        snapshot.main()
        first = self._history()
        snapshot.main()
        second = self._history()
        self.assertEqual(first["days"], second["days"])

    def test_missing_bad_or_empty_source_keeps_existing_count(self):
        self._save_history([{"date": "2026-09-09", "counts": {"dm": 7, "yx": 8, "gs": 9}}])
        # dm is missing; yx is malformed; gs is an empty crawler output.
        (self.data / "youxia_news.json").write_text("{", encoding="utf-8")
        (self.data / "gamersky_news.json").write_text("", encoding="utf-8")
        self._write_all_sources()
        # Restore the three unavailable variants after creating the remaining sources.
        (self.data / "3dmgame_news.json").unlink()
        (self.data / "youxia_news.json").write_text("{", encoding="utf-8")
        (self.data / "gamersky_news.json").write_text("", encoding="utf-8")
        snapshot.main()
        counts = self._history()["days"][0]["counts"]
        self.assertEqual((counts["dm"], counts["yx"], counts["gs"]), (7, 8, 9))

    def test_all_unavailable_does_not_create_zero_day(self):
        snapshot.main()
        self.assertEqual(self._history()["days"], [])

    def test_all_unavailable_keeps_historical_days(self):
        self._save_history([{"date": "2026-09-01", "counts": {"dm": 12}}])
        snapshot.main()
        days = self._history()["days"]
        self.assertEqual(len(days), 1)
        self.assertEqual(days[0]["date"], "2026-09-01")
        self.assertEqual(days[0]["counts"]["dm"], 12)

    def test_new_date_from_another_source_does_not_zero_unavailable_source(self):
        self._write_all_sources({"yx": [{"published_at": "2026-09-09 10:00:00"}]})
        (self.data / "3dmgame_news.json").unlink()
        snapshot.main()
        days = {row["date"]: row["counts"] for row in self._history()["days"]}
        self.assertEqual(days["2026-09-09"]["yx"], 1)
        self.assertNotIn("dm", days["2026-09-09"])

    def test_today_keeps_unavailable_source_missing(self):
        self._write_all_sources()
        (self.data / "3dmgame_news.json").unlink()
        snapshot.main()
        days = {row["date"]: row["counts"] for row in self._history()["days"]}
        self.assertNotIn("dm", days["2026-09-10"])
        self.assertEqual(days["2026-09-10"]["yx"], 0)

    def test_visible_window_can_correct_prior_count(self):
        self._save_history([{"date": "2026-09-09", "counts": {"dm": 5}}])
        self._write_all_sources(
            {"dm": [
                {"published_at": "2026-09-09 09:00:00"},
                {"published_at": "2026-09-09 10:00:00"},
            ]}
        )
        snapshot.main()
        days = {row["date"]: row["counts"] for row in self._history()["days"]}
        self.assertEqual(days["2026-09-09"]["dm"], 2)


if __name__ == "__main__":
    unittest.main()
