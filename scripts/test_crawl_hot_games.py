"""热门游戏动态通用官网列表解析的离线单测。"""
import unittest
from datetime import date
from unittest.mock import patch

from bs4 import BeautifulSoup

from crawl_hot_games import fetch_official_html_updates, parse_official_html_updates


class OfficialHtmlUpdatesTests(unittest.TestCase):
    def test_keeps_dated_items_and_resolves_relative_detail_url(self):
        game = {
            "game_name": "\u6d4b\u8bd5\u6e38\u620f",
            "official_url": "https://example.com/home/news/",
            "list_url": "https://example.com/home/news/",
            "dom": {
                # 官网常以 article/li 作条目容器，详情链接在内部 a 元素。
                "item": ".news-item",
                "date_sel": ".date",
                "date_fmt": "%Y-%m-%d",
                "title_sel": ".title",
                "label_sel": ".type",
                "summary_sel": ".summary",
            },
        }
        html = """
        <nav><a class="news-item" href="/ignore">\u6ca1\u6709\u65e5\u671f\u7684\u5bfc\u822a</a></nav>
        <article class="news-item"><a href="detail/42"><span class="type">\u6d3b\u52a8</span>
          <h2 class="title">\u767b\u5f55\u798f\u5229</h2><time class="date">2026-09-18</time>
          <p class="summary">\u5b8c\u6210\u4efb\u52a1\u5373\u53ef\u9886\u53d6\u5956\u52b1\u3002</p></a></article>
        <article class="news-item"><a href="detail/42"><span class="type">\u6d3b\u52a8</span>
          <h2 class="title">\u540c\u94fe\u63a5\u91cd\u590d\u9879</h2><time class="date">2026-09-18</time></a></article>
        <article class="news-item"><a href="/old"><h2 class="title">\u65e7\u52a8\u6001</h2>
          <time class="date">2026-09-10</time></a></article>
        """

        updates = parse_official_html_updates(game, html, cutoff=date(2026, 9, 12))

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["title"], "\u767b\u5f55\u798f\u5229")
        self.assertEqual(updates[0]["type"], "\u65b0\u6d3b\u52a8")
        self.assertEqual(updates[0]["date"], "2026-09-18")
        self.assertEqual(updates[0]["url"], "https://example.com/home/news/detail/42")
        self.assertEqual(updates[0]["summary"], "\u5b8c\u6210\u4efb\u52a1\u5373\u53ef\u9886\u53d6\u5956\u52b1\u3002")

    def test_fetch_raises_when_news_selector_matches_nothing(self):
        game = {
            "game_name": "\u6d4b\u8bd5\u6e38\u620f",
            "official_url": "https://example.com/home/news/",
            "list_url": "https://example.com/home/news/",
            "dom": {"item": ".news-item", "date_sel": ".date", "date_fmt": "%Y-%m-%d"},
        }
        with patch(
            "crawl_hot_games._netease_soup",
            return_value=BeautifulSoup("<main><a href='/news'>menu</a></main>", "html.parser"),
        ):
            with self.assertRaisesRegex(RuntimeError, "\u672a\u627e\u5230\u65b0\u95fb\u5217\u8868"):
                fetch_official_html_updates(game)

    def test_fetch_raises_when_candidates_have_no_parseable_dates(self):
        game = {
            "game_name": "\u6d4b\u8bd5\u6e38\u620f",
            "official_url": "https://example.com/home/news/",
            "list_url": "https://example.com/home/news/",
            "dom": {"item": ".news-item", "date_sel": ".date", "date_fmt": "%Y-%m-%d"},
        }
        html = """
        <article class="news-item"><a href="detail/42"><time class="date">not-a-date</time></a></article>
        """
        with patch(
            "crawl_hot_games._netease_soup",
            return_value=BeautifulSoup(html, "html.parser"),
        ):
            with self.assertRaisesRegex(RuntimeError, "\u7f3a\u5c11\u53ef\u89e3\u6790\u65e5\u671f"):
                fetch_official_html_updates(game)


if __name__ == "__main__":
    unittest.main()
