"""Tests for the shared upper-bound guard used by all news crawlers."""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from news_dates import is_within_news_window  # noqa: E402


class TestNewsDates(unittest.TestCase):
    def setUp(self):
        self.start = date(2026, 9, 9)
        self.today = date(2026, 9, 18)

    def test_accepts_inclusive_window_boundaries(self):
        self.assertTrue(is_within_news_window("2026-09-09 00:00:00", self.start, self.today))
        self.assertTrue(is_within_news_window("2026-09-18 23:59:59", self.start, self.today))

    def test_rejects_future_dates(self):
        self.assertFalse(is_within_news_window("2026-10-10 06:28:32", self.start, self.today))

    def test_rejects_malformed_dates(self):
        self.assertFalse(is_within_news_window("", self.start, self.today))
        self.assertFalse(is_within_news_window("not-a-date", self.start, self.today))


if __name__ == "__main__":
    unittest.main()
