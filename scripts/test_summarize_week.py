"""summarize_week.py unit tests (stdlib unittest, no pytest needed).

Run:  python -m unittest discover -s scripts -p "test_*.py" -v

All CJK / fullwidth literals are written as \\u escapes on purpose so the file
stays pure-ASCII and cannot be corrupted by console codepage issues on Windows.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import summarize_week as sw  # noqa: E402


GAME_A = "AlphaQuest"
GAME_B = "BetaLand"


def _bucket(**kwargs):
    base = sw._empty_bucket()
    base.update(kwargs)
    return base


class TestHeatFormula(unittest.TestCase):
    def test_missing_signals_are_zero_not_penalty(self):
        bucket = _bucket(articles=[{}, {}, {}], sources={"3dmgame", "youxia"})
        score, parts = sw.heat_breakdown(bucket)
        self.assertEqual(parts["reservation"], 0.0)
        self.assertEqual(parts["community"], 0.0)
        self.assertEqual(parts["rank"], 0.0)
        self.assertGreater(score, 0.0)

    def test_rank_score_window(self):
        self.assertEqual(sw.rank_score(None), 0.0)
        self.assertEqual(sw.rank_score(51), 0.0)
        self.assertAlmostEqual(sw.rank_score(1), 1.0)
        self.assertAlmostEqual(sw.rank_score(26), 0.5)

    def test_qualifies_thresholds(self):
        self.assertTrue(sw.qualifies(_bucket(articles=[{}, {}, {}])))
        self.assertTrue(sw.qualifies(_bucket(sources={"a", "b"})))
        self.assertTrue(sw.qualifies(_bucket(reservation=10000)))
        self.assertTrue(sw.qualifies(_bucket(follow=10000)))
        self.assertTrue(sw.qualifies(_bucket(best_rank=20)))
        self.assertFalse(sw.qualifies(_bucket(articles=[{}, {}], reservation=9999)))


class TestCommunityDelta(unittest.TestCase):
    def test_snapshot_reads_taptap_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "taptap_upcoming.json"), "w", encoding="utf-8") as fh:
                json.dump(
                    [
                        {
                            "game_name": GAME_A,
                            "follow_count": "1.2\u4e07",
                            "review_count": 300,
                            "discussion_count": None,
                        },
                        {"game_name": "", "follow_count": 999},
                        {"game_name": GAME_B},
                    ],
                    fh,
                )
            snapshot = sw.community_snapshot(tmp)
        self.assertEqual(
            snapshot, {sw.stat_key(GAME_A): {"follow": 12000, "review": 300}}
        )

    def test_history_overwrites_same_day_and_skips_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = sw.stat_key(GAME_A)
            sw.update_community_history(tmp, {key: {"follow": 10}}, today=date(2026, 8, 23))
            sw.update_community_history(tmp, {key: {"follow": 20}}, today=date(2026, 8, 23))
            self.assertIsNone(sw.update_community_history(tmp, {}, today=date(2026, 8, 24)))
            payload = sw.load_json(os.path.join(tmp, sw.COMMUNITY_HISTORY_NAME))
        self.assertEqual(len(payload["snapshots"]), 1)
        self.assertEqual(payload["snapshots"][0]["date"], "2026-08-23")
        self.assertEqual(payload["snapshots"][0]["games"][key], {"follow": 20})

    def _history(self, *rows):
        return {"snapshots": [{"date": day, "games": games} for day, games in rows]}

    def test_delta_needs_pre_window_baseline(self):
        key = sw.stat_key(GAME_A)
        history = self._history(
            ("2026-08-18", {key: {"follow": 100}}),
            ("2026-08-23", {key: {"follow": 500}}),
        )
        self.assertEqual(
            sw.community_deltas(history, date(2026, 8, 17), date(2026, 8, 23)), {}
        )

    def test_delta_is_window_increment_clamped_and_intersected(self):
        key = sw.stat_key(GAME_A)
        history = self._history(
            ("2026-08-10", {key: {"follow": 100, "review": 80, "discussion": 5}}),
            ("2026-08-16", {key: {"follow": 200, "review": 90}}),
            ("2026-08-20", {key: {"follow": 260, "review": 60, "discussion": 9}}),
            ("2026-08-23", {key: {"follow": 500, "review": 70}}),
            ("2026-08-30", {key: {"follow": 900, "review": 999}}),
        )
        deltas = sw.community_deltas(history, date(2026, 8, 17), date(2026, 8, 23))
        # \u57fa\u7ebf\u7528 08-16\uff0c\u7ec8\u503c\u7528 08-23\uff1bdiscussion \u4e24\u8fb9\u4e0d\u5168\u4e0d\u8ba1
        self.assertEqual(deltas, {key: {"follow": 300, "review": 0}})

    def test_heat_uses_delta_not_stock(self):
        stock_only = _bucket(articles=[{}], follow=500000)
        delta_only = _bucket(articles=[{}], community_delta={"follow": 5000})
        self.assertEqual(sw.heat_breakdown(stock_only)[1]["community"], 0.0)
        self.assertGreater(sw.heat_breakdown(delta_only)[1]["community"], 0.0)


class TestFeaturedAndRules(unittest.TestCase):
    def test_game_news_prefers_event_titles(self):
        bucket = _bucket(
            articles=[
                {
                    "title": GAME_A + " dlc",
                    "url": "https://example.com/plain",
                    "source": "3DMGame",
                    "published_at": "2026-08-21 10:00:00",
                },
                {
                    "title": GAME_A + " " + "\u53d1\u552e",
                    "url": "https://example.com/event",
                    "source": "3DMGame",
                    "published_at": "2026-08-20 10:00:00",
                },
            ],
            sources={"3dmgame"},
        )
        row = {"name": GAME_A, "heat": 0.5, "bucket": bucket, "key": GAME_A.lower()}
        news = sw.pick_game_news(row, limit=2)
        self.assertEqual(len(news), 1)
        self.assertEqual(news[0]["url"], "https://example.com/event")
        self.assertEqual(news[0]["published_at"], "2026-08-20")

    def test_game_news_respects_limit_and_recency(self):
        bucket = _bucket(
            articles=[
                {
                    "title": "%s \u66f4\u65b0 %d" % (GAME_A, i),
                    "url": "https://example.com/%d" % i,
                    "source": "3DMGame",
                    "published_at": "2026-08-2%d 10:00:00" % i,
                }
                for i in range(4)
            ],
            sources={"3dmgame"},
        )
        row = {"name": GAME_A, "heat": 0.5, "bucket": bucket, "key": GAME_A.lower()}
        news = sw.pick_game_news(row, limit=2)
        self.assertEqual(len(news), 2)
        self.assertEqual(news[0]["url"], "https://example.com/3")
        self.assertEqual(news[1]["url"], "https://example.com/2")

    def test_heat_formula_note_lists_weights(self):
        note = sw.heat_formula_note()
        self.assertIn("30%", note)
        self.assertIn(str(sw.MEDIA_CAP), note)

    def test_rules_overview_contains_counts(self):
        articles = [{"game_name": GAME_A}, {"game_name": ""}]
        ranked = [
            {
                "name": GAME_A,
                "bucket": _bucket(articles=[{"title": "x"}] * 4),
            }
        ]
        text = sw.rules_overview(date(2026, 8, 16), date(2026, 8, 22), articles, ranked)
        self.assertIn("2", text)
        self.assertIn(GAME_A, text)


class TestCollectAndPayload(unittest.TestCase):
    def test_week_hash_stable(self):
        articles = [
            {"url": "https://b.example/2"},
            {"url": "https://a.example/1"},
        ]
        self.assertEqual(sw.week_input_hash(articles), sw.week_input_hash(list(reversed(articles))))

    def test_collect_from_temp_dir(self):
        start, end = date(2026, 8, 16), date(2026, 8, 22)
        with tempfile.TemporaryDirectory() as tmp:
            news = {
                "items": [
                    {
                        "title": GAME_A + " " + "\u53d1\u552e",
                        "url": "https://news.example/a1",
                        "game_name": GAME_A,
                        "published_at": "2026-08-20 12:00:00",
                        "summary": "",
                    },
                    {
                        "title": GAME_A + " " + "\u6d4b\u8bd5",
                        "url": "https://news.example/a2",
                        "game_name": GAME_A,
                        "published_at": "2026-08-21 12:00:00",
                        "summary": "",
                    },
                    {
                        "title": GAME_A + " dlc",
                        "url": "https://news.example/a3",
                        "game_name": GAME_A,
                        "published_at": "2026-08-18 12:00:00",
                        "summary": "",
                    },
                    {
                        "title": "industry",
                        "url": "https://news.example/x",
                        "game_name": "",
                        "published_at": "2026-08-19 12:00:00",
                        "summary": "",
                    },
                    {
                        "title": "too old",
                        "url": "https://news.example/old",
                        "game_name": GAME_B,
                        "published_at": "2026-08-01 12:00:00",
                        "summary": "",
                    },
                ]
            }
            with open(os.path.join(tmp, "3dmgame_news.json"), "w", encoding="utf-8") as handle:
                json.dump(news, handle)
            with open(os.path.join(tmp, "youxia_news.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "items": [
                            {
                                "title": GAME_A + " review",
                                "url": "https://youxia.example/a",
                                "game_name": GAME_A,
                                "published_at": "2026-08-17 08:00:00",
                                "summary": "",
                            }
                        ]
                    },
                    handle,
                )
            articles, ranked = sw.collect_games(tmp, start, end)
            self.assertEqual(len(articles), 5)
            self.assertTrue(ranked)
            self.assertEqual(ranked[0]["name"], GAME_A)
            self.assertGreaterEqual(len(ranked[0]["bucket"]["articles"]), 4)
            self.assertEqual(len(ranked[0]["bucket"]["sources"]), 2)

    def test_run_skips_write_when_no_articles(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sw, "llm_enabled", return_value=False):
                ok = sw.run(data_dir=tmp, today=date(2026, 8, 23))
            self.assertFalse(ok)
            self.assertFalse(os.path.exists(os.path.join(tmp, "weekly_digest.json")))

    def test_run_writes_rules_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "items": [
                    {
                        "title": GAME_A + " " + "\u53d1\u552e",
                        "url": "https://news.example/%d" % i,
                        "game_name": GAME_A,
                        "published_at": "2026-08-1%d 12:00:00" % (2 + (i % 3)),
                        "summary": "",
                    }
                    for i in range(3)
                ]
            }
            with open(os.path.join(tmp, "3dmgame_news.json"), "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            with mock.patch.object(sw, "llm_enabled", return_value=False):
                ok = sw.run(data_dir=tmp, today=date(2026, 8, 23))
            self.assertTrue(ok)
            out_path = os.path.join(tmp, "weekly_digest.json")
            with open(out_path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["week_start"], "2026-08-10")
            self.assertEqual(data["week_end"], "2026-08-16")
            self.assertEqual(data["digest_source"], "rules")
            self.assertEqual(data["article_count"], 3)
            self.assertTrue(data["hot_ranking"])
            self.assertEqual(data["hot_ranking"][0]["name"], GAME_A)
            self.assertEqual(data["hot_ranking"][0]["media_count"], 3)


class TestVerifyDigest(unittest.TestCase):
    def test_leading_zero_date_is_allowed(self):
        source = "\u65e5\u671f\uff1a2026-08-21\n\u5171 12 \u6761"
        filler = (
            "\u6d89\u53ca\u591a\u6b3e\u6e38\u620f\u7684\u53d1\u552e\u4e0e\u66f4\u65b0\u52a8\u6001\uff0c"
            "\u62a5\u9053\u96c6\u4e2d\u5728\u51e0\u6b3e\u70ed\u95e8\u4f5c\u54c1\u7684\u7248\u672c\u524d\u77bb\u4e0e\u6d4b\u8bd5\u6392\u671f\u3002"
        )
        text = "8\u670821\u65e5\u5171 12 \u6761\u65b0\u95fb\uff0c" + filler * 3
        ok, reason = sw.verify_digest(text, source)
        self.assertTrue(ok, reason)

    def test_fabricated_number_is_rejected(self):
        source = "\u65e5\u671f\uff1a2026-08-21\n\u5171 12 \u6761"
        filler = (
            "\u6d89\u53ca\u591a\u6b3e\u6e38\u620f\u7684\u53d1\u552e\u4e0e\u66f4\u65b0\u52a8\u6001\uff0c"
            "\u62a5\u9053\u96c6\u4e2d\u5728\u51e0\u6b3e\u70ed\u95e8\u4f5c\u54c1\u7684\u7248\u672c\u524d\u77bb\u4e0e\u6d4b\u8bd5\u6392\u671f\u3002"
        )
        text = "8\u670821\u65e5\u5171 12 \u6761\u65b0\u95fb\uff0c\u9500\u91cf\u8d85 300 \u4e07\uff0c" + filler * 3
        ok, reason = sw.verify_digest(text, source)
        self.assertFalse(ok)
        self.assertIn("300", reason)

    def test_retry_after_prefers_header(self):
        import summarize_news as sn

        resp = mock.Mock()
        resp.headers = {"Retry-After": "20"}
        resp.json.side_effect = ValueError("no json")
        self.assertEqual(sn.retry_after_seconds(resp), 20)
        resp.headers = {}
        resp.json.side_effect = ValueError("no json")
        self.assertEqual(sn.retry_after_seconds(resp), sn.LLM_RETRY_WAIT)
        resp.headers = {"Retry-After": "5"}
        resp.json.side_effect = ValueError("no json")
        self.assertEqual(sn.retry_after_seconds(resp), sn.LLM_RETRY_WAIT)

    def test_spark_auth_hint_on_11200(self):
        import summarize_news as sn

        hint = sn.spark_auth_hint('{"error":{"message":"AppIdNoAuthError","code":"11200"}}')
        self.assertIn("APIPassword", hint)
        self.assertEqual(sn.spark_auth_hint("429 too many requests"), "")

    def test_parse_joins_wrapped_overview(self):
        import summarize_news as sn

        raw = (
            "\u7efc\u8ff0\uff1a8\u670821\u65e5\u5171 12 \u6761\u65b0\u95fb\uff0c\n"
            "\u6d89\u53ca\u591a\u6b3e\u6e38\u620f\u7684\u53d1\u552e\u4e0e\u66f4\u65b0\u52a8\u6001\uff0c"
            "\u62a5\u9053\u96c6\u4e2d\u5728\u51e0\u6b3e\u70ed\u95e8\u4f5c\u54c1\u3002\n"
            "\n"
            "AlphaQuest\uff5c\u5f53\u5929\u66f4\u65b0\u4e86\u6d4b\u8bd5\u6392\u671f\u3002"
        )
        overview, summaries = sn.parse_model_output(raw)
        self.assertIn("12", overview)
        self.assertGreaterEqual(len(overview), 40)
        self.assertIn(sw.stat_key("AlphaQuest"), summaries)

    def test_parse_without_overview_prefix_joins_prose(self):
        import summarize_news as sn

        raw = (
            "8\u670821\u65e5\u5171 12 \u6761\u65b0\u95fb\u3002\n"
            "\u62a5\u9053\u96c6\u4e2d\u5728\u70ed\u95e8\u4f5c\u54c1\u7684\u53d1\u552e\u4e0e\u66f4\u65b0\u3002\n"
            "AlphaQuest\uff5c\u5f53\u5929\u66f4\u65b0\u4e86\u6d4b\u8bd5\u6392\u671f\u3002"
        )
        overview, summaries = sn.parse_model_output(raw)
        self.assertIn("12", overview)
        self.assertIn("\u53d1\u552e", overview)
        self.assertIn(sw.stat_key("AlphaQuest"), summaries)

    def test_extract_falls_back_to_reasoning(self):
        import summarize_news as sn

        empty = {"choices": [{"message": {"content": "", "reasoning_content": "ok"}}]}
        self.assertEqual(sn.extract_message_text(empty), "ok")
        filled = {"choices": [{"message": {"content": "body", "reasoning_content": "draft"}}]}
        self.assertEqual(sn.extract_message_text(filled), "body")



if __name__ == "__main__":
    unittest.main()
