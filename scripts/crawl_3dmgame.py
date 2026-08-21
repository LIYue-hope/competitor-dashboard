"""3DMGAME 新闻 & 测评滚动窗口采集脚本。

数据源：
  新闻列表：https://www.3dmgame.com/news/game/ （第 1 页），
            翻页规律 https://www.3dmgame.com/news/game_{page}/（page 从 2 开始）
  测评列表：https://www.3dmgame.com/original_40_1/ （第 1 页），
            翻页规律 https://www.3dmgame.com/original_40_{page}/（page 从 1 开始递增）

两个列表页均为服务端渲染的静态 HTML，requests 直接抓取即可解析，无需 JS 渲染。

采集窗口与滚动更新逻辑（与本项目其它脚本不同，两个输出文件都不是全量覆盖）：
  新闻窗口 10 天、测评窗口 15 天，均为 [today - (N-1) days, today]。
  测评窗口更长是因为测评产出频率远低于新闻（每天多则数条、常常整周为 0），
  10 天窗口经常只剩零星几条甚至空列表，拉长到 15 天才够撑起一屏内容。
  1. 读取已有输出文件（若存在）
  2. 本次翻页抓取新数据，直到某一页所有条目 published_at 都早于窗口起始日期
     就停止翻页，避免无限翻旧页
  3. 新旧数据按 url 去重合并（同一 url 用最新抓到的那条覆盖旧的）
  4. 过滤：只保留 published_at 日期部分 >= 窗口起始日期的条目
  5. 按 published_at 降序排序后写入文件
  6. 若本次抓取彻底失败（网络错误、解析到 0 条），不用空结果覆盖旧文件，
     保留旧数据不变

输出：
  data/3dmgame_news.json
    {"crawled_at": "...", "window_days": 10, "items": [
      {title, url, game_name, published_at, summary}, ...
    ]}
  data/3dmgame_reviews.json
    {"crawled_at": "...", "window_days": 15, "items": [
      {title, url, score, published_at, comment_count, author}, ...
    ]}

"""
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import DEFAULT_HEADERS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawl_3dmgame")

NEWS_FIRST_PAGE_URL = "https://www.3dmgame.com/news/game/"
NEWS_PAGE_URL_TMPL = "https://www.3dmgame.com/news/game_{page}/"

REVIEW_PAGE_URL_TMPL = "https://www.3dmgame.com/original_40_{page}/"

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
NEWS_OUTPUT_PATH = os.path.join(DATA_DIR, "3dmgame_news.json")
REVIEWS_OUTPUT_PATH = os.path.join(DATA_DIR, "3dmgame_reviews.json")

# 采集窗口：新闻 [today - 9 天, today]，共 10 天
NEWS_WINDOW_DAYS = 10
# 测评窗口比新闻长：测评产出频率远低于新闻（常常连续多天为 0），10 天窗口经常
# 只剩零星几条，拉长到 15 天才够撑起前端一屏内容。
REVIEWS_WINDOW_DAYS = 15

MAX_PAGES = 60  # 兜底翻页上限，避免站点结构异常导致死循环


def fetch_page(url):
    """请求 3dmgame 页面，返回文本，失败返回 None。"""
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        return resp.text
    except requests.RequestException as exc:
        logger.warning("请求 3dmgame 页面失败：%s，原因：%s", url, exc)
        return None


def load_existing_items(path):
    """读取已有输出文件的 items 列表，文件不存在或解析失败则返回空列表。"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取已有文件失败：%s，原因：%s，视为空列表处理", path, exc)
        return []


def merge_and_filter(old_items, new_items, window_start):
    """按 url 去重合并新旧数据，并过滤出窗口内的条目，按 published_at 降序排序。"""
    merged = {}
    for item in old_items:
        url = item.get("url")
        if url:
            merged[url] = item
    for item in new_items:
        url = item.get("url")
        if url:
            merged[url] = item  # 同一 url 用最新抓到的那条覆盖旧的

    window_start_str = window_start.isoformat()
    filtered = [
        item
        for item in merged.values()
        if item.get("published_at", "")[:10] >= window_start_str
    ]
    filtered.sort(key=lambda item: item.get("published_at", ""), reverse=True)
    return filtered


def parse_news_page(html):
    """解析新闻列表页，返回本页条目列表（含 published_at 为 datetime 供比较，
    最终写入前会转成字符串）。"""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("li.selectpost"):
        text_div = li.find("div", class_="text")
        if not text_div:
            continue
        a_bt = text_div.find("a", class_="bt")
        if not a_bt:
            continue
        title = a_bt.get_text(strip=True)
        url = a_bt.get("href", "").strip()
        if not title or not url:
            continue

        bq = text_div.find("div", class_="bq")
        game_name = ""
        published_at = None
        if bq:
            a_game = bq.find("a", class_="a")
            if a_game:
                game_name = a_game.get_text(strip=True)
            time_span = bq.find("span", class_="time")
            if time_span:
                time_text = time_span.get_text(strip=True)
                try:
                    published_at = datetime.strptime(time_text, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    logger.warning("新闻条目发布时间解析失败：%s（%s）", time_text, url)

        if published_at is None:
            continue

        summary_div = text_div.find("div", class_="miaoshu")
        summary = summary_div.get_text(strip=True) if summary_div else ""

        items.append(
            {
                "title": title,
                "url": url,
                "game_name": game_name,
                "published_at": published_at,
                "summary": summary,
            }
        )
    return items


def parse_review_page(html):
    """解析测评列表页，返回本页条目列表（published_at 为 datetime）。"""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("li.listb"):
        bt_div = li.find("div", class_="bt")
        a_bt = bt_div.find("a", class_="a_bt") if bt_div else None
        if not a_bt:
            continue
        title = a_bt.get_text(strip=True)
        url = a_bt.get("href", "").strip()
        if not title or not url:
            continue

        net_div = li.find("div", class_="net")
        score = None
        published_at = None
        comment_count = 0
        author = ""
        if net_div:
            p_div = net_div.find("div", class_="p")
            if p_div:
                font_a = p_div.find("a", class_="font")
                if font_a:
                    score_text = font_a.get_text(strip=True)
                    score = score_text or None

            btn_list = net_div.find("div", class_="btn_list")
            if btn_list:
                time_div = btn_list.find("div", class_="time")
                if time_div:
                    time_text = time_div.get_text(strip=True)
                    try:
                        published_at = datetime.strptime(time_text, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        logger.warning("测评条目发布时间解析失败：%s（%s）", time_text, url)

                pl_a = btn_list.find("a", class_="pl")
                if pl_a:
                    num_span = pl_a.find("span", class_="selectarcnum")
                    if num_span:
                        num_text = num_span.get_text(strip=True)
                        try:
                            comment_count = int(num_text)
                        except ValueError:
                            comment_count = 0

                name_a = btn_list.find("a", class_="name")
                if name_a:
                    author = name_a.get_text(strip=True)

        if published_at is None:
            continue

        items.append(
            {
                "title": title,
                "url": url,
                "score": score,
                "published_at": published_at,
                "comment_count": comment_count,
                "author": author,
            }
        )
    return items


def crawl_paginated(first_page_url, page_url_tmpl, parse_func, window_start, label):
    """通用翻页采集：从第一页开始翻页，直到当页所有条目发布时间都早于窗口起始日期。

    - first_page_url: 第一页 URL（可能与 page_url_tmpl.format(page=1) 不同，如新闻列表）
    - page_url_tmpl: 第 2 页起的 URL 模板，形如 ".../xxx_{page}/"
    - parse_func: 解析单页 HTML 返回条目列表（published_at 为 datetime）的函数
    - window_start: 窗口起始日期（date 对象）
    - label: 日志用标签
    返回：(items 列表，published_at 已转为字符串, 实际翻页数)
    """
    all_items = []
    page = 1
    reached_window_start = False
    while page <= MAX_PAGES:
        url = first_page_url if page == 1 else page_url_tmpl.format(page=page)
        html = fetch_page(url)
        if not html:
            logger.warning("%s 第 %d 页请求失败，停止翻页", label, page)
            break

        page_items = parse_func(html)
        if not page_items:
            logger.info("%s 第 %d 页解析到 0 条，停止翻页", label, page)
            break

        all_items.extend(page_items)

        oldest_on_page = min(item["published_at"] for item in page_items).date()
        logger.info(
            "%s 第 %d 页抓到 %d 条，本页最早发布时间 %s",
            label, page, len(page_items), oldest_on_page,
        )
        if oldest_on_page < window_start:
            # 该页最早一条已早于窗口起始日期，说明后续页只会更旧，停止翻页
            reached_window_start = True
            break

        page += 1

    if not reached_window_start and page > MAX_PAGES:
        # 触到翻页上限而非"翻出窗口"才退出：说明本次没能覆盖完整窗口，最早若干天
        # 的数据会缺失。稳态下靠与旧文件合并可能掩盖，必须显式告警避免长期沉默。
        logger.warning(
            "%s 翻页到上限 %d 页仍未覆盖到窗口起始日期 %s，本次可能缺少较早日期的数据",
            label, MAX_PAGES, window_start.isoformat(),
        )


    for item in all_items:
        item["published_at"] = item["published_at"].strftime("%Y-%m-%d %H:%M:%S")

    return all_items, page


def crawl_news(window_start):
    """采集新闻列表，返回本次抓取到的新条目列表（未与旧数据合并）。"""
    items, pages = crawl_paginated(
        NEWS_FIRST_PAGE_URL, NEWS_PAGE_URL_TMPL, parse_news_page, window_start, "新闻",
    )
    logger.info("新闻采集完成，共翻 %d 页，抓到 %d 条", pages, len(items))
    return items


def crawl_reviews(window_start):
    """采集测评列表，返回本次抓取到的新条目列表（未与旧数据合并）。"""
    items, pages = crawl_paginated(
        REVIEW_PAGE_URL_TMPL.format(page=1), REVIEW_PAGE_URL_TMPL, parse_review_page,
        window_start, "测评",
    )
    logger.info("测评采集完成，共翻 %d 页，抓到 %d 条", pages, len(items))
    return items


def write_output(path, items, label, window_days):
    """写出单个数据源的结果。

    window_days 必须由调用方按数据源传入（新闻 10、测评 15），不能共用一个
    全局常量：前端「近 N 天」文案直接读这个字段，写错会显示成错误的天数。
    """
    output = {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "window_days": window_days,
        "items": items,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("写入 %s（%s，%d 条）", path, label, len(items))


def run_news(today, window_start):
    try:
        new_items = crawl_news(window_start)
    except Exception:
        logger.exception("新闻采集异常，保留旧数据不写入")
        return 1

    if not new_items:
        logger.error("新闻采集结果为空（0 条），疑似解析失效，终止写入以避免覆盖旧数据")
        return 1

    old_items = load_existing_items(NEWS_OUTPUT_PATH)
    merged = merge_and_filter(old_items, new_items, window_start)
    write_output(NEWS_OUTPUT_PATH, merged, "新闻", NEWS_WINDOW_DAYS)
    return 0


def run_reviews(today, window_start):
    try:
        new_items = crawl_reviews(window_start)
    except Exception:
        logger.exception("测评采集异常，保留旧数据不写入")
        return 1

    if not new_items:
        logger.error("测评采集结果为空（0 条），疑似解析失效，终止写入以避免覆盖旧数据")
        return 1

    old_items = load_existing_items(REVIEWS_OUTPUT_PATH)
    merged = merge_and_filter(old_items, new_items, window_start)
    write_output(REVIEWS_OUTPUT_PATH, merged, "测评", REVIEWS_WINDOW_DAYS)
    return 0


def main():
    today = date.today()
    # 新闻与测评窗口长度不同，各自单独算窗口起始日期
    news_window_start = today - timedelta(days=NEWS_WINDOW_DAYS - 1)
    reviews_window_start = today - timedelta(days=REVIEWS_WINDOW_DAYS - 1)
    logger.info(
        "开始抓取 3DMGAME 新闻与测评，新闻窗口 %s ~ %s（%d 天），测评窗口 %s ~ %s（%d 天）",
        news_window_start.isoformat(), today.isoformat(), NEWS_WINDOW_DAYS,
        reviews_window_start.isoformat(), today.isoformat(), REVIEWS_WINDOW_DAYS,
    )

    news_result = run_news(today, news_window_start)
    reviews_result = run_reviews(today, reviews_window_start)

    return 0 if news_result == 0 and reviews_result == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
