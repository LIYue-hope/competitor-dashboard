"""heat_utils.py unit tests (stdlib unittest, no pytest needed).

Run:  python -m unittest discover -s scripts -p "test_*.py" -v

All CJK / fullwidth literals are written as \\u escapes on purpose so the file
stays pure-ASCII and cannot be corrupted by console codepage issues on Windows.
"""
import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from heat_utils import (  # noqa: E402
    format_count_label,
    in_range,
    last_week_range,
    log_norm,
    parse_count,
    parse_date,
    pick_display_name,
)

WAN = "\u4e07"
NONE_LABEL = "\u6682\u65e0"


class TestParseCount(unittest.TestCase):
    def test_plain_integer(self):
        self.assertEqual(parse_count(2390), 2390)
        self.assertEqual(parse_count("2390"), 2390)

    def test_wan_suffix(self):
        self.assertEqual(parse_count("214" + WAN), 2140000)
        self.assertEqual(parse_count("123.7" + WAN), 1237000)
        self.assertEqual(parse_count("214 " + WAN), 2140000)

    def test_invalid_returns_none(self):
        self.assertIsNone(parse_count(None))
        self.assertIsNone(parse_count(""))
        self.assertIsNone(parse_count(NONE_LABEL))
        self.assertIsNone(parse_count(-1))
        self.assertIsNone(parse_count("abc"))
        self.assertIsNone(parse_count(True))


class TestLogNorm(unittest.TestCase):
    def test_zero_and_none(self):
        self.assertEqual(log_norm(None, 100), 0.0)
        self.assertEqual(log_norm(0, 100), 0.0)
        self.assertEqual(log_norm(10, 0), 0.0)

    def test_cap_is_one(self):
        self.assertEqual(log_norm(100, 100), 1.0)
        self.assertEqual(log_norm(200, 100), 1.0)

    def test_mid_is_between(self):
        mid = log_norm(10, 100)
        self.assertTrue(0.0 < mid < 1.0)


class TestLastWeekRange(unittest.TestCase):
    def test_known_sunday(self):
        # 2026-08-23 is Sunday; previous calendar week is Mon 08-10 .. Sun 08-16
        start, end = last_week_range(date(2026, 8, 23))
        self.assertEqual(start, date(2026, 8, 10))
        self.assertEqual(end, date(2026, 8, 16))

    def test_known_monday(self):
        # 2026-08-24 is Monday; previous calendar week is Mon 08-17 .. Sun 08-23
        start, end = last_week_range(date(2026, 8, 24))
        self.assertEqual(start, date(2026, 8, 17))
        self.assertEqual(end, date(2026, 8, 23))

    def test_always_monday_to_sunday(self):
        for day in range(17, 31):
            start, end = last_week_range(date(2026, 8, day))
            self.assertEqual(start.weekday(), 0)
            self.assertEqual(end.weekday(), 6)
            self.assertEqual((end - start).days, 6)
            self.assertLess(end, date(2026, 8, day))

    def test_datetime_uses_beijing_date(self):
        start, end = last_week_range(datetime(2026, 8, 23, 1, 0, 0))
        self.assertEqual(start, date(2026, 8, 10))
        self.assertEqual(end, date(2026, 8, 16))



class TestInRangeAndParseDate(unittest.TestCase):
    def test_parse_date(self):
        self.assertEqual(parse_date("2026-08-20 12:00:00"), date(2026, 8, 20))
        self.assertEqual(parse_date("2026-08-20"), date(2026, 8, 20))
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("not-a-date"))

    def test_in_range_inclusive(self):
        start, end = date(2026, 8, 16), date(2026, 8, 22)
        self.assertTrue(in_range("2026-08-16 00:00:00", start, end))
        self.assertTrue(in_range("2026-08-22 23:59:59", start, end))
        self.assertFalse(in_range("2026-08-15", start, end))
        self.assertFalse(in_range("2026-08-23", start, end))
        self.assertFalse(in_range("", start, end))


class TestDisplayHelpers(unittest.TestCase):
    def test_pick_display_name(self):
        self.assertEqual(pick_display_name({"A": 1, "AA": 1}), "AA")
        self.assertEqual(pick_display_name({"short": 1, "longer": 2}), "longer")
        self.assertEqual(pick_display_name({}), "")

    def test_format_count_label(self):
        self.assertIsNone(format_count_label(None))
        self.assertEqual(format_count_label(2390), "2390")
        self.assertEqual(format_count_label(10000), "1" + WAN)
        self.assertEqual(format_count_label(12370), "1.2" + WAN)


if __name__ == "__main__":
    unittest.main()
