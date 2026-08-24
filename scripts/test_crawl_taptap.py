# -*- coding: utf-8 -*-
"""crawl_taptap.py \u91cc\u7eaf\u51fd\u6570\u7684\u5355\u6d4b\uff08\u4e0d\u8d70\u7f51\u7edc\uff09\u3002"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crawl_taptap as ct

FOLLOW = "\u5173\u6ce8"       # 关注
REVIEW = "\u8bc4\u4ef7"       # 评价
DISCUSS = "\u8ba8\u8bba"      # 讨论
WAN = "\u4e07"                # 万


class TestExtractMetric(unittest.TestCase):
    def test_plain_number_after_newline(self):
        text = FOLLOW + "\n2390\n" + REVIEW + "\n188"
        self.assertEqual(ct.extract_metric(text, FOLLOW), "2390")
        self.assertEqual(ct.extract_metric(text, REVIEW), "188")

    def test_wan_with_space_is_kept(self):
        text = FOLLOW + "\n214 " + WAN + "\n"
        self.assertEqual(ct.extract_metric(text, FOLLOW), "214" + WAN)

    def test_decimal_wan(self):
        self.assertEqual(ct.extract_metric(DISCUSS + "\n1.2" + WAN, DISCUSS), "1.2" + WAN)

    def test_missing_label_returns_none(self):
        self.assertIsNone(ct.extract_metric(FOLLOW + "\n10", DISCUSS))

    def test_empty_inputs(self):
        self.assertIsNone(ct.extract_metric("", FOLLOW))
        self.assertIsNone(ct.extract_metric(FOLLOW + "\n10", ""))
        self.assertIsNone(ct.extract_metric(None, FOLLOW))


if __name__ == "__main__":
    unittest.main()
