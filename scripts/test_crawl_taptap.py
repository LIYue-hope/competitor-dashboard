# -*- coding: utf-8 -*-
"""crawl_taptap.py \u91cc\u7eaf\u51fd\u6570\u7684\u5355\u6d4b\uff08\u4e0d\u8d70\u7f51\u7edc\uff09\u3002

\u6d4b\u8bd5\u7ebf\u7d22\uff1a\u65b0\u7248\u672c\u6539\u7528 webapiv2 \u65e5\u5386\u63a5\u53e3
(/webapiv2/calendar/v1/upcoming)\uff0c\u4e8b\u4ef6\u7ed3\u6784\u4e3a app_card_info
\uff08title/tags/stat.rating\uff09\uff0c\u4ee5\u771f\u5b9e\u63a5\u53e3\u6837\u4f8b
scripts/_api_dumps/upcoming_type1.json \u7684\u5b57\u6bb5\u7ed3\u6784\u4e3a\u4f9d\u636e\u6784\u9020
\u56fa\u5b9a\u4f8b\u3002\u4e2d\u6587\u5b57\u9762\u91cf\u5747\u4e3a \\uXXXX \u8f6c\u4e49\uff0c
\u6587\u4ef6\u4fdd\u6301\u7eaf ASCII\u3002
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crawl_taptap as ct

FOLLOW = "\u5173\u6ce8"        # 关注
REVIEW = "\u8bc4\u4ef7"        # 评价
DISCUSS = "\u8ba8\u8bba"       # 讨论
WAN = "\u4e07"                 # 万

YYS = "\u9634\u9633\u5e08"                 # 阴阳师
JWM = "\u4e5d\u4e07\u4ea9"                 # 九万亩
WZWXQ = "\u738b\u8005\u4e07\u8c61\u68cb"   # 王者万象棋
KAPAI = "\u5361\u724c"                      # 卡牌
YANGCHENG = "\u517b\u6210"                  # 养成
HUIHEZHI = "\u56de\u5408\u5236"             # 回合制
CELUE = "\u7b56\u7565"                      # 策略
XIANSU = "\u50cf\u7d20"                     # 像素
JINGJI = "\u7ade\u6280"                     # 竞技
NEW_VER = "\u65b0\u7248\u672c\u66f4\u65b0"  # 新版本更新
XIANLIANG = "\u9650\u91cf\u6d4b\u8bd5"      # 限量测试
SHOUFA = "\u9996\u53d1"                     # 首发

# Beijing-day epoch seconds (real sample values) -> YYYY-MM-DD
DAY_0909 = 1788883200
DAY_0910 = 1788969600


def _tag(value):
    return {"id": 1, "value": value, "uri": "", "web_url": ""}


def _event(game_id, title, tags=None, score=None, status=None):
    """\u6309\u771f\u5b9e upcoming \u63a5\u53e3\u7684 event \u7ed3\u6784\u6784\u9020\u4e00\u4e2a\u4e8b\u4ef6\u3002"""
    stat = {}
    if score is not None:
        stat["rating"] = {"score": str(score), "max": 10}
    app = {
        "title": title,
        "tags": [_tag(t) for t in (tags or [])],
        "stat": stat,
        "developers": [],
    }
    event = {
        "game_id": game_id,
        "app_card_info": app,
        "sub_event_type_title": status,
    }
    return event


def _day_group(day, events):
    return {"day": day, "list": events}


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


class TestDayToIso(unittest.TestCase):
    def test_beijing_day_zero_to_iso(self):
        self.assertEqual(ct._day_to_iso(DAY_0909), "2026-09-09")
        self.assertEqual(ct._day_to_iso(DAY_0910), "2026-09-10")

    def test_invalid_day_returns_none(self):
        self.assertIsNone(ct._day_to_iso(None))
        self.assertIsNone(ct._day_to_iso("abc"))
        self.assertIsNone(ct._day_to_iso(""))


class TestEventToGame(unittest.TestCase):
    def test_full_mapping(self):
        event = _event(
            12492,
            YYS,
            tags=[KAPAI, YANGCHENG, HUIHEZHI],
            score="7.4",
            status=NEW_VER,
        )
        game = ct._event_to_game(event, "2026-09-09")
        self.assertIsNotNone(game)
        self.assertEqual(game["app_id"], "12492")
        self.assertEqual(game["name"], YYS)
        self.assertEqual(game["score"], "7.4")
        self.assertEqual(game["status_tag"], NEW_VER)
        self.assertEqual(game["tags"], [KAPAI, YANGCHENG, HUIHEZHI])
        self.assertEqual(game["release_date"], "2026-09-09")
        self.assertEqual(game["detail_url"], "https://www.taptap.cn/app/12492")

    def test_title_as_text_dict_is_unwrapped(self):
        event = _event(12492, {"text": YYS})
        game = ct._event_to_game(event, "2026-09-09")
        self.assertIsNotNone(game)
        self.assertEqual(game["name"], YYS)

    def test_missing_title_returns_none(self):
        event = _event(12492, "")
        self.assertIsNone(ct._event_to_game(event, "2026-09-09"))
        event2 = _event(12492, None)
        self.assertIsNone(ct._event_to_game(event2, "2026-09-09"))
        event3 = _event(12492, "   ")
        self.assertIsNone(ct._event_to_game(event3, "2026-09-09"))

    def test_missing_game_id_returns_none(self):
        event = _event(None, YYS)
        self.assertIsNone(ct._event_to_game(event, "2026-09-09"))
        event2 = {"app_card_info": {"title": YYS}}
        self.assertIsNone(ct._event_to_game(event2, "2026-09-09"))

    def test_non_dict_app_card_info_returns_none(self):
        event = {"game_id": 12492, "app_card_info": None, "sub_event_type_title": SHOUFA}
        self.assertIsNone(ct._event_to_game(event, "2026-09-09"))

    def test_no_rating_score_keeps_score_none(self):
        event = _event(12492, YYS, tags=[KAPAI])  # stat has no rating
        game = ct._event_to_game(event, "2026-09-09")
        self.assertIsNotNone(game)
        self.assertIsNone(game["score"])

    def test_empty_tag_values_are_dropped(self):
        app = {
            "title": YYS,
            "tags": [
                {"id": 1, "value": KAPAI, "uri": "", "web_url": ""},
                {"id": 2, "value": "", "uri": "", "web_url": ""},
                {"id": 3, "value": None, "uri": "", "web_url": ""},
                "not-a-dict",
            ],
            "stat": {},
        }
        event = {"game_id": 12492, "app_card_info": app, "sub_event_type_title": NEW_VER}
        game = ct._event_to_game(event, "2026-09-09")
        self.assertEqual(game["tags"], [KAPAI])


class TestParseDayGroups(unittest.TestCase):
    def test_flat_map_and_beijing_dates(self):
        groups = [
            _day_group(
                DAY_0909,
                [
                    _event(12492, YYS, tags=[KAPAI, YANGCHENG, HUIHEZHI], score="7.4", status=NEW_VER),
                    _event(715863, JWM, tags=[CELUE, "SLG", XIANSU], score="8.9", status=XIANLIANG),
                ],
            ),
            _day_group(
                DAY_0910,
                [_event(243110, WZWXQ, tags=[JINGJI, "PVP", HUIHEZHI], score="7.6", status=SHOUFA)],
            ),
        ]
        games = ct.parse_day_groups(groups)
        self.assertEqual([g["app_id"] for g in games], ["12492", "715863", "243110"])
        self.assertEqual([g["release_date"] for g in games], ["2026-09-09", "2026-09-09", "2026-09-10"])
        first = games[0]
        self.assertEqual(first["name"], YYS)
        self.assertEqual(first["score"], "7.4")
        self.assertEqual(first["status_tag"], NEW_VER)
        self.assertEqual(first["tags"], [KAPAI, YANGCHENG, HUIHEZHI])
        self.assertEqual(games[2]["name"], WZWXQ)
        self.assertEqual(games[2]["release_date"], "2026-09-10")

    def test_dedup_by_app_id_keeps_first(self):
        # same game_id: two events on one day (shoufa + pre-download) and again on another day
        groups = [
            _day_group(
                DAY_0909,
                [
                    _event(758860, YYS, score="7.4", status=SHOUFA),
                    _event(758860, YYS, score="7.4", status=NEW_VER),
                    _event(715863, JWM, score="8.9", status=XIANLIANG),
                ],
            ),
            _day_group(DAY_0910, [_event(758860, YYS, score="7.4", status=SHOUFA)]),
        ]
        games = ct.parse_day_groups(groups)
        self.assertEqual([g["app_id"] for g in games], ["758860", "715863"])
        # first occurrence wins: its date and status tag are kept
        self.assertEqual(games[0]["release_date"], "2026-09-09")
        self.assertEqual(games[0]["status_tag"], SHOUFA)

    def test_bad_groups_and_events_are_skipped(self):
        groups = [
            "not-a-dict",
            None,
            _day_group(DAY_0909, [_event(12492, YYS, tags=[KAPAI]), "not-an-event", None]),
            {"day": DAY_0909, "list": [_event(None, YYS)]},  # missing game_id -> dropped
        ]
        games = ct.parse_day_groups(groups)
        self.assertEqual([g["app_id"] for g in games], ["12492"])


class TestEnrichReleaseDateGuard(unittest.TestCase):
    """\u4e30\u5bcc\u7ec6\u8282\u9875\u65f6\uff0c\u5b8c\u6574 YYYY-MM-DD \u65e5\u671f\u4e0d\u518d\u88ab MM/DD \u56de\u9000\u6539\u5199\u3002"""

    ASCII_HTML = "<html><body><div>some game intro text</div><div>placeholder</div></body></html>"

    def _base_game(self, release_date):
        return {
            "app_id": "12492",
            "name": "SomeGame",
            "score": None,
            "status_tag": None,
            "tags": [],
            "release_date": release_date,
            "detail_url": "https://www.taptap.cn/app/12492",
        }

    def test_full_date_untouched_when_no_detail_date(self):
        game = self._base_game("2026-09-09")
        with mock.patch("crawl_taptap.fetch_html", return_value=self.ASCII_HTML) as m:
            result = ct.enrich_with_detail(game)
        m.assert_called_once_with("https://www.taptap.cn/app/12492")
        self.assertEqual(result["release_date"], "2026-09-09")

    def test_mmdd_style_date_still_rewritten(self):
        # only when the field is NOT a full date (legacy SSR MM/DD group title) is it rewritten
        game = self._base_game("06/15")
        with mock.patch("crawl_taptap.fetch_html", return_value=self.ASCII_HTML):
            result = ct.enrich_with_detail(game)
        bj_now = datetime.now(timezone.utc) + timedelta(hours=8)
        self.assertEqual(result["release_date"], "%d-06-15" % bj_now.year)

    def test_detail_fetch_failure_keeps_game_untouched(self):
        game = self._base_game("2026-09-09")
        with mock.patch("crawl_taptap.fetch_html", return_value=None):
            result = ct.enrich_with_detail(game)
        self.assertIs(result, game)
        self.assertEqual(result["release_date"], "2026-09-09")
        self.assertNotIn("publisher", result)


if __name__ == "__main__":
    unittest.main()
