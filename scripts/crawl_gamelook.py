"""GameLook（gamelook.com.cn）新闻滚动窗口采集脚本（该站只有新闻，没有评测）。

数据源（WordPress REST API，不抓 HTML）：
  http://www.gamelook.com.cn/wp-json/wp/v2/posts?per_page=20&page=N

站点特点（均为实测结论）：
  1. 不抓 HTML 而走 REST API：首页原始 HTML 里混着 29 个侧边栏推荐文章 id，噪音
     极大；且 /page/1/ 会 302 到 /，"首页当 page/1 处理"的语义映射到 API 的
     page=1 即可。
  2. API 响应体带 UTF-8 BOM，resp.json() 会抛
     "JSONDecodeError: Unexpected UTF-8 BOM"，必须用
     json.loads(resp.content.decode("utf-8-sig")) 手工解码。
  3. 响应头 X-WP-TotalPages 实测 2134，按发布时间倒序返回。
  4. date 字段是站点本地时间（形如 2026-08-21T11:10:17），实测就是北京时间
     （date_gmt 恰好早 8 小时），直接按北京时间解析，不做时区换算。
  5. excerpt.rendered 是带 <p> 标签与 HTML 实体的摘要，且末尾常带"阅读全文"类
     残留，需要清洗。

采集窗口与滚动更新逻辑（与 scripts/crawl_youxia.py 一致，输出不是全量覆盖）：
  新闻窗口 10 天。
  1. 读取已有输出文件（若存在）
  2. 从 page=1 起逐页翻，某一页所有条目都早于窗口起始日期就停止翻页
     （用户要求的"首页 + page/2"两页必然被完整覆盖，窗口内更早的条目也会自然补齐）
  3. 新旧数据按 url 去重合并（同一 url 用最新抓到的那条覆盖旧的）
  4. 只保留 published_at 日期部分 >= 窗口起始日期的条目
  5. 按 published_at 降序排序后写入文件

写文件保护：
  本次 API 解析出的原始条目数为 0 才抛异常拒绝写（接口改版/字段失效）；原始条目
  正常、只是窗口内筛出 0 条属正常情况，照常写入。

输出：
  data/gamelook_news.json
    {"crawled_at": "...", "window_days": 10, "items": [
      {title, url, published_at, summary, post_id}, ...
    ]}
    （GameLook 列表接口没有游戏名与作者名，故不输出 game_name / author 字段）
"""
import html
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import DEFAULT_HEADERS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawl_gamelook")

API_URL_TMPL = (
    "http://www.gamelook.com.cn/wp-json/wp/v2/posts?per_page={per_page}&page={page}"
)
PER_PAGE = 20

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
NEWS_OUTPUT_PATH = os.path.join(DATA_DIR, "gamelook_news.json")

# 采集窗口：新闻 [today - 9 天, today]，共 10 天
NEWS_WINDOW_DAYS = 10

MAX_PAGES = 30  # 兜底翻页上限，避免接口异常导致死循环

REQUEST_INTERVAL = 1  # 每次请求前的间隔（秒），避免给站点造成压力

# 摘要末尾的"阅读全文"类残留（可能带方括号/省略号/箭头等装饰）
READ_MORE_RE = re.compile(r"[\[\(（【]?\s*(阅读全文|查看全文|继续阅读|详情|更多)\s*[\]\)）】…\.>》]*\s*$")


def fetch_page(page, retries=2, backoff=1.5):
    """请求 REST API 的第 page 页，返回文章列表，重试若干次后仍失败返回 None。

    响应体带 UTF-8 BOM，resp.json() 会抛 "Unexpected UTF-8 BOM"，
    必须用 utf-8-sig 手工解码后再 json.loads。
    """
    url = API_URL_TMPL.format(per_page=PER_PAGE, page=page)
    for attempt in range(1, retries + 2):
        time.sleep(REQUEST_INTERVAL)
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
            resp.raise_for_status()
            posts = json.loads(resp.content.decode("utf-8-sig"))
            if not isinstance(posts, list):
                logger.warning("GameLook 接口返回结构异常（非列表）：%s", url)
                return None
            return posts
        except (requests.RequestException, json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning(
                "请求 GameLook 接口失败（第 %d 次）：%s，原因：%s", attempt, url, exc
            )
            if attempt <= retries:
                time.sleep(backoff * attempt)
    logger.error("请求彻底失败，放弃：%s", url)
    return None


def clean_summary(raw_html):
    """把 excerpt.rendered 清成纯文本摘要：去标签 + 反转义实体 + 去"阅读全文"残留。"""
    if not raw_html:
        return ""
    text = BeautifulSoup(raw_html, "html.parser").get_text(" ")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return READ_MORE_RE.sub("", text).strip()


def parse_post(post):
    """把单条 API 文章对象转成输出条目，字段缺失返回 None。

    date 字段是站点本地时间（实测即北京时间），直接解析、不做时区换算；
    额外附带 pub_date（date 对象）供翻页判断，写文件前由调用方剔除。
    """
    title = html.unescape((post.get("title") or {}).get("rendered", "")).strip()
    url = (post.get("link") or "").strip()
    date_text = (post.get("date") or "").strip()
    if not title or not url or not date_text:
        logger.warning("GameLook 条目字段缺失，跳过：id=%s", post.get("id"))
        return None
    try:
        published = datetime.strptime(date_text[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        logger.warning("GameLook 条目发布时间解析失败：%s（%s）", date_text, url)
        return None

    return {
        "title": title,
        "url": url,
        "published_at": published.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": clean_summary((post.get("excerpt") or {}).get("rendered", "")),
        "post_id": post.get("id"),
        "pub_date": published.date(),
    }


def load_existing_items(path):
    """读取已有输出文件里的 items，文件不存在或损坏都返回空列表。"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取已有文件失败：%s，原因：%s，按无历史数据处理", path, exc)
        return []


def crawl_news(window_start):
    """从 page=1 起逐页翻，返回 (窗口内条目列表, 原始解析条目数, 实际翻页数)。

    停止翻页条件：本页所有条目都早于窗口起始日期（接口按时间倒序，后续页只会更旧）。
    原始解析条目数用于区分"接口/字段失效"和"窗口内没有内容"。
    """
    items = []
    raw_count = 0
    page = 1
    stopped_by_window = False
    while page <= MAX_PAGES:
        posts = fetch_page(page)
        if posts is None:
            logger.warning("新闻第 %d 页请求失败，停止翻页", page)
            break
        if not posts:
            logger.info("新闻第 %d 页返回 0 条，停止翻页", page)
            break
        raw_count += len(posts)

        page_items = [parsed for parsed in (parse_post(post) for post in posts) if parsed]
        if not page_items:
            logger.warning("新闻第 %d 页 %d 条原始数据全部解析失败，停止翻页", page, len(posts))
            break

        oldest_on_page = min(item["pub_date"] for item in page_items)
        items.extend(item for item in page_items if item["pub_date"] >= window_start)
        logger.info(
            "新闻第 %d 页抓到 %d 条，本页最早日期 %s，窗口内累计 %d 条",
            page, len(page_items), oldest_on_page.isoformat(), len(items),
        )

        if oldest_on_page < window_start:
            stopped_by_window = True
            break
        page += 1

    if not stopped_by_window and page > MAX_PAGES:
        # 触到翻页上限而非"翻出窗口"退出：本次没能覆盖完整窗口，最早若干天会缺数据。
        # 稳态下与旧文件合并可能掩盖问题，必须显式告警避免长期沉默。
        logger.warning(
            "新闻翻页到上限 %d 页仍未覆盖到窗口起始日期 %s，本次可能缺少较早日期的数据",
            MAX_PAGES, window_start.isoformat(),
        )
    logger.info("新闻采集完成，共翻 %d 页，原始 %d 条，窗口内 %d 条",
                min(page, MAX_PAGES), raw_count, len(items))
    return items, raw_count, min(page, MAX_PAGES)


def merge_and_filter(old_items, new_items, window_start):
    """按 url 去重合并新旧条目，只保留窗口内的，按发布时间降序。"""
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


def strip_internal_fields(items):
    """去掉只在采集过程中用到的中间字段，避免写进输出文件。"""
    for item in items:
        item.pop("pub_date", None)
    return items


def write_output(path, items, label, window_days):
    """写出结果。window_days 由调用方传入：前端「近 N 天」文案直接读这个字段。"""
    output = {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "window_days": window_days,
        "items": items,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("写入 %s（%s，%d 条）", path, label, len(items))


def run_news(window_start):
    try:
        new_items, raw_count, _pages = crawl_news(window_start)
    except Exception:
        logger.exception("新闻采集异常，保留旧数据不写入")
        return 1

    if raw_count == 0:
        logger.error("GameLook 接口解析到 0 条原始条目，疑似接口失效，终止写入以避免覆盖旧数据")
        return 1

    old_items = load_existing_items(NEWS_OUTPUT_PATH)
    merged = merge_and_filter(old_items, strip_internal_fields(new_items), window_start)
    logger.info("新闻合并后 %d 条", len(merged))
    write_output(NEWS_OUTPUT_PATH, merged, "新闻", NEWS_WINDOW_DAYS)
    return 0


def main():
    today = date.today()
    window_start = today - timedelta(days=NEWS_WINDOW_DAYS - 1)
    logger.info(
        "开始抓取 GameLook 新闻，窗口 %s ~ %s（%d 天）",
        window_start.isoformat(), today.isoformat(), NEWS_WINDOW_DAYS,
    )
    return run_news(window_start)


if __name__ == "__main__":
    sys.exit(main())

