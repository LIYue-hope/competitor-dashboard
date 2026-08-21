"""游民星空（gamersky.com）新闻 & 评测滚动窗口采集脚本。

数据源（均为实测确认的接口，勿改）：
  列表翻页接口（新闻与评测共用，游民星空所有列表 tab 都走它）：
    GET https://db2.gamersky.com/LabelJsonpAjax.aspx?jsondata=<urlencode 的 JSON>&callback=cb
    jsondata = {"type":"updatenodelabel","isCache":true,"cacheTime":60,
                "nodeId":"<节点 id>","isNodeId":"true","page":<页码，从 1 开始>}
    新闻 Referer 用 https://www.gamersky.com/news/，评测用 https://www.gamersky.com/review/。
  新闻 4 个频道：单机电玩 129、NS 21160、手游 20260、网游 20225（各 20 条/页）
  评测：全部评测 20915（14 条/页）

站点特点（实测结论）：
  1. 响应是 JSONP（`cb({...});`），需先剥壳再 json.loads；字段 status/totalPages/body，
     其中 body 是一段 <li> HTML 片段。响应头 charset 不可靠，一律按 utf-8 解码。
  2. 必须从 page=1 开始翻 API，不要混用频道页面内嵌的首屏 HTML：内嵌 pager 声称
     pagesize=50，但 API 恒定每页返回固定条数，混用会产生重复条目。
  3. 列表里的文章链接域名不止 www：还有 shouyou.gamersky.com（手游）、ol.gamersky.com
     （网游）、www.gamersky.com/hardware/... 等，也可能是根相对路径
     /news/202608/2188836.shtml。必须 urljoin 补全，并用宽松正则判断有效性，
     不能因为域名不是 www 就丢弃。
  4. 单机电玩（129）出稿极快（约 20 条 / 1.3 小时），10 天窗口要翻很多页，
     所以每个频道加 MAX_PAGES_PER_CHANNEL 上限兜底，防止异常时无限翻页。
  5. 手游频道（20260）已长期停更（实测最新一条 2026-07-31），10 天窗口内为 0 条
     属站点本身没更新，不是解析失效。

采集窗口与滚动更新逻辑（与 scripts/crawl_youxia.py 一致，输出不是全量覆盖）：
  新闻窗口 10 天、评测窗口 15 天。
  1. 读取已有输出文件（若存在）
  2. 本次翻页抓取新数据，某一页所有条目都早于窗口起始日期就停止翻页
  3. 新旧数据按 url 去重合并（同一 url 用最新抓到的那条覆盖旧的）
  4. 只保留 published_at 日期部分 >= 窗口起始日期的条目
  5. 按 published_at 降序排序后写入文件

写文件保护（同 crawl_youxia.py）：按"解析是否崩了"判断——列表接口解析出的原始
条目数为 0 才抛异常拒绝写（节点 id 失效/改版）；原始条目正常、只是窗口内筛出
0 条属正常情况（如手游频道停更），照常写入。

输出：
  data/gamersky_news.json
    {"crawled_at": "...", "window_days": 10, "items": [
      {title, url, published_at, summary, author, channel, cover}, ...
    ]}
  data/gamersky_reviews.json
    {"crawled_at": "...", "window_days": 15, "items": [
      {title, url, score, published_at, summary, author, cover}, ...
    ]}
    （score 为列表页 div.pc > div.num，站点显示 -- 或空时为 None）
"""
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import DEFAULT_HEADERS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawl_gamersky")

LIST_API_URL = "https://db2.gamersky.com/LabelJsonpAjax.aspx"
JSONP_CALLBACK = "cb"
# 站内链接可能是根相对路径，统一以主站域名为基准 urljoin 补全
SITE_BASE_URL = "https://www.gamersky.com/"
NEWS_REFERER = "https://www.gamersky.com/news/"
REVIEWS_REFERER = "https://www.gamersky.com/review/"

# 新闻 4 个频道：(channel 字段值, nodeId)，抓完后合并去重
NEWS_CHANNELS = [
    ("单机电玩", "129"),
    ("NS", "21160"),
    ("手游", "20260"),
    ("网游", "20225"),
]
# 评测：全部评测节点
REVIEWS_NODE_ID = "20915"

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
NEWS_OUTPUT_PATH = os.path.join(DATA_DIR, "gamersky_news.json")
REVIEWS_OUTPUT_PATH = os.path.join(DATA_DIR, "gamersky_reviews.json")

# 采集窗口：新闻 [today - 9 天, today]，共 10 天
NEWS_WINDOW_DAYS = 10
# 评测产出频率远低于新闻，窗口放长到 15 天，避免前端长期空着
REVIEWS_WINDOW_DAYS = 15

# 单个频道的翻页上限：单机电玩（129）出稿极快，没有上限时异常情况下会一直翻
MAX_PAGES_PER_CHANNEL = 200

REQUEST_INTERVAL = 1  # 每次请求前的间隔（秒），避免给站点造成压力

# JSONP 剥壳：响应形如 cb({...});
JSONP_RE = re.compile(r"^\s*%s\((.*)\)\s*;?\s*$" % JSONP_CALLBACK, re.S)
# 文章链接有效性判断：域名不限于 www（还有 shouyou./ol.），路径段不限于 news
ARTICLE_URL_RE = re.compile(
    r"^https?://[a-z0-9.]*gamersky\.com/[^\s\"]*?/(\d{6})/(\d+)\.shtml"
)
AUTHOR_PREFIX_RE = re.compile(r"^作者[:：]\s*")


def fetch_page(url, referer, retries=2, backoff=1.5):
    """请求游民星空接口/页面，返回文本，重试若干次后仍失败返回 None。

    响应头 charset 不可靠（apparent_encoding 在 JSONP 上也会猜错），一律按
    utf-8 解码。Referer 必须带：不带时接口会返回空 body。
    """
    headers = dict(DEFAULT_HEADERS)
    headers["Referer"] = referer
    for attempt in range(1, retries + 2):
        time.sleep(REQUEST_INTERVAL)
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except requests.RequestException as exc:
            logger.warning(
                "请求游民星空失败（第 %d 次）：%s，原因：%s", attempt, url, exc
            )
            if attempt <= retries:
                time.sleep(backoff * attempt)
    logger.error("请求彻底失败，放弃：%s", url)
    return None


def list_api_url(node_id, page):
    """拼出列表翻页接口 URL（jsondata 需整体 urlencode）。"""
    jsondata = {
        "type": "updatenodelabel",
        "isCache": True,
        "cacheTime": 60,
        "nodeId": node_id,
        "isNodeId": "true",
        "page": page,
    }
    query = urlencode(
        {
            "jsondata": json.dumps(jsondata, separators=(",", ":")),
            "callback": JSONP_CALLBACK,
        }
    )
    return "%s?%s" % (LIST_API_URL, query)


def fetch_list_body(node_id, page, referer):
    """取某节点某页的 <li> HTML 片段，返回 (body, total_pages)，失败返回 (None, None)。"""
    text = fetch_page(list_api_url(node_id, page), referer)
    if not text:
        return None, None
    match = JSONP_RE.match(text)
    if not match:
        logger.warning("节点 %s 第 %d 页响应不是预期的 JSONP 结构", node_id, page)
        return None, None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("节点 %s 第 %d 页 JSON 解析失败：%s", node_id, page, exc)
        return None, None
    if data.get("status") != "ok":
        logger.warning(
            "节点 %s 第 %d 页接口返回 status=%s", node_id, page, data.get("status")
        )
        return None, None
    return data.get("body") or "", data.get("totalPages")


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


def parse_score(li):
    """解析评测分数（div.pc > div.num），无分数/占位符返回 None。

    新闻列表没有这个节点，返回 None 即正常；评测未打分时站点显示 -- 或空。
    """
    num_div = li.select_one("div.pc div.num")
    if not num_div:
        return None
    text = num_div.get_text(strip=True)
    if not text or text.strip("-—") == "":
        return None
    try:
        return float(text)
    except ValueError:
        logger.info("评分无法解析：%s", text)
        return None


def parse_list_items(body_html):
    """解析接口返回的 <li> 片段，返回本页条目列表（新闻与评测同构）。

    每条附带 pub_dt（datetime）供翻页判断，写文件前由调用方剔除。
    """
    soup = BeautifulSoup(body_html, "html.parser")
    items = []
    for li in soup.find_all("li"):
        a_title = li.select_one("div.tit a")
        if not a_title:
            continue
        # title 属性与锚文本都可能被截断（属性值里未转义的双引号会截断属性，
        # 锚文本则被站点用省略号截短），取更长的那个互补
        attr_title = (a_title.get("title") or "").strip()
        text_title = a_title.get_text(strip=True)
        title = attr_title if len(attr_title) >= len(text_title) else text_title
        href = (a_title.get("href") or "").strip()
        if not title or not href:
            continue

        # 链接可能是根相对路径，也可能在 shouyou./ol. 等兄弟域名下，统一补全后校验
        url = urljoin(SITE_BASE_URL, href)
        if not ARTICLE_URL_RE.match(url):
            logger.warning("条目链接不符合文章格式，跳过：%s", url)
            continue

        time_div = li.select_one("div.tem div.time")
        time_text = time_div.get_text(strip=True) if time_div else ""
        try:
            pub_dt = datetime.strptime(time_text, "%Y-%m-%d %H:%M")
        except ValueError:
            logger.warning("条目时间解析失败：%s（%s）", time_text, url)
            continue

        summary_div = li.select_one("div.txt")
        summary = re.sub(r"\s+", " ", summary_div.get_text()).strip() if summary_div else ""

        tag_div = li.select_one("div.tem div.tag")
        author = AUTHOR_PREFIX_RE.sub("", tag_div.get_text(strip=True)) if tag_div else ""

        img = li.select_one("div.img img[src]")
        cover = (img.get("src") or "").strip() if img else ""

        items.append(
            {
                "title": title,
                "url": url,
                "published_at": pub_dt.strftime("%Y-%m-%d %H:%M:00"),
                "summary": summary,
                "author": author,
                "score": parse_score(li),
                "cover": cover,
                "pub_dt": pub_dt,
            }
        )
    return items


def crawl_node(node_id, referer, window_start, label, max_pages=MAX_PAGES_PER_CHANNEL):
    """从 page=1 起逐页翻某个节点，返回 (窗口内条目, 原始解析条目数, 实际翻页数)。

    停止翻页的条件（任一满足）：
      - 本页所有条目都早于窗口起始日期（后续页只会更旧）
      - 已翻到接口声明的 totalPages
      - 触到 max_pages 上限（异常兜底，会告警）
    原始解析条目数用于区分"解析失效"和"窗口内没有内容"。
    """
    items = []
    raw_count = 0
    page = 1
    stopped_by_window = False
    while page <= max_pages:
        body, total_pages = fetch_list_body(node_id, page, referer)
        if body is None:
            logger.warning("%s 第 %d 页请求失败，停止翻页", label, page)
            break

        page_items = parse_list_items(body)
        if not page_items:
            logger.info("%s 第 %d 页解析到 0 条，停止翻页", label, page)
            break
        raw_count += len(page_items)

        oldest_on_page = min(item["pub_dt"] for item in page_items)
        items.extend(
            item for item in page_items if item["pub_dt"].date() >= window_start
        )
        logger.info(
            "%s 第 %d 页抓到 %d 条，本页最早时间 %s，窗口内累计 %d 条",
            label, page, len(page_items),
            oldest_on_page.strftime("%Y-%m-%d %H:%M"), len(items),
        )

        if oldest_on_page.date() < window_start:
            stopped_by_window = True
            break
        if total_pages and page >= int(total_pages):
            logger.info("%s 已翻到接口声明的末页（共 %s 页），停止翻页", label, total_pages)
            stopped_by_window = True
            break

        page += 1

    if not stopped_by_window and page > max_pages:
        # 触到翻页上限而非"翻出窗口"退出：本次没能覆盖完整窗口，最早若干天会缺数据。
        # 稳态下与旧文件合并可能掩盖问题，必须显式告警避免长期沉默。
        logger.warning(
            "%s 翻页到上限 %d 页仍未覆盖到窗口起始日期 %s，本次可能缺少较早日期的数据",
            label, max_pages, window_start.isoformat(),
        )
    return items, raw_count, page


def crawl_news(window_start):
    """采集新闻 4 个频道并合并，返回 (条目列表, 原始解析条目总数)。

    每条打 channel 字段标明来源频道；跨频道可能有同一篇稿子，由 merge_and_filter
    按 url 去重（保留后抓到的那个频道标记）。
    """
    all_items = []
    raw_total = 0
    for channel, node_id in NEWS_CHANNELS:
        label = "新闻·%s（nodeId=%s）" % (channel, node_id)
        items, raw_count, pages = crawl_node(node_id, NEWS_REFERER, window_start, label)
        if raw_count == 0:
            logger.warning("%s 解析到 0 条原始条目，疑似节点失效", label)
        for item in items:
            item["channel"] = channel
        logger.info("%s 采集完成，共翻 %d 页，原始 %d 条，窗口内 %d 条",
                    label, pages, raw_count, len(items))
        all_items.extend(items)
        raw_total += raw_count
    return all_items, raw_total


def crawl_reviews(window_start):
    """采集评测（nodeId=20915，全部评测），返回 (条目列表, 原始解析条目数)。"""
    label = "评测（nodeId=%s）" % REVIEWS_NODE_ID
    items, raw_count, pages = crawl_node(
        REVIEWS_NODE_ID, REVIEWS_REFERER, window_start, label,
    )
    logger.info("%s 采集完成，共翻 %d 页，原始 %d 条，窗口内 %d 条",
                label, pages, raw_count, len(items))
    return items, raw_count


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
        item.pop("pub_dt", None)
    return items


def write_output(path, items, label, window_days):
    """写出单个数据源的结果。

    window_days 必须由调用方按数据源传入（新闻 10、评测 15），不能共用一个
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


def run_news(window_start):
    try:
        new_items, raw_count = crawl_news(window_start)
    except Exception:
        logger.exception("新闻采集异常，保留旧数据不写入")
        return 1

    if raw_count == 0:
        logger.error("新闻列表接口解析到 0 条原始条目，疑似解析失效，终止写入以避免覆盖旧数据")
        return 1

    old_items = load_existing_items(NEWS_OUTPUT_PATH)
    merged = merge_and_filter(old_items, strip_internal_fields(new_items), window_start)
    write_output(NEWS_OUTPUT_PATH, merged, "新闻", NEWS_WINDOW_DAYS)
    return 0


def run_reviews(window_start):
    try:
        new_items, raw_count = crawl_reviews(window_start)
    except Exception:
        logger.exception("评测采集异常，保留旧数据不写入")
        return 1

    if raw_count == 0:
        logger.error("评测列表接口解析到 0 条原始条目，疑似解析失效，终止写入以避免覆盖旧数据")
        return 1

    old_items = load_existing_items(REVIEWS_OUTPUT_PATH)
    merged = merge_and_filter(old_items, strip_internal_fields(new_items), window_start)
    write_output(REVIEWS_OUTPUT_PATH, merged, "评测", REVIEWS_WINDOW_DAYS)
    return 0


def main():
    today = date.today()
    # 新闻与评测窗口长度不同，各自单独算窗口起始日期
    news_window_start = today - timedelta(days=NEWS_WINDOW_DAYS - 1)
    reviews_window_start = today - timedelta(days=REVIEWS_WINDOW_DAYS - 1)
    logger.info(
        "开始抓取游民星空新闻与评测，新闻窗口 %s ~ %s（%d 天），评测窗口 %s ~ %s（%d 天）",
        news_window_start.isoformat(), today.isoformat(), NEWS_WINDOW_DAYS,
        reviews_window_start.isoformat(), today.isoformat(), REVIEWS_WINDOW_DAYS,
    )
    news_result = run_news(news_window_start)
    reviews_result = run_reviews(reviews_window_start)
    return 0 if news_result == 0 and reviews_result == 0 else 1


if __name__ == "__main__":
    sys.exit(main())


