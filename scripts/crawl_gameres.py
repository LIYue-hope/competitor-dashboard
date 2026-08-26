"""游资网（gameres.com）新闻滚动窗口采集脚本（该站只有新闻，没有评测）。

数据源（站点自有 JSON 接口，不抓 HTML）：
  https://www.gameres.com/api/v1/portal/articles?page_size=50[&cursor=<next_cursor>]

站点特点（均为实测结论）：
  1. 列表接口按 cursor 翻页而不是页号：响应信封为
     {"code":200,"msg":"ok","data":{"list":[...],"next_cursor":"..."}}，
     下一页把上一页的 next_cursor 原样回传即可；next_cursor 为 null/空串表示
     没有下一页。page_size 上限 50，传 >50 接口直接返回 422。
  2. code != 200 视为失败（业务层错误），与网络异常一样走重试。
  3. 反爬只看 User-Agent：不带 UA 或 python-requests 默认 UA 都是 403，带浏览器
     UA（utils.DEFAULT_HEADERS）即可正常返回。
  4. 全站 UTF-8 无 BOM，resp.json() 可直接用（与 GameLook 的 WordPress REST API
     不同，那边必须 utf-8-sig 手工解码）。
  5. dateline 是 Unix 秒，转北京时间后格式化成 YYYY-MM-DD HH:MM:SS，与其它来源
     的 published_at 口径一致。
  6. 条目的 url 字段是站内 /wl?m=xxx 形式的 302 跳板，不能直接输出：
     is_wailian == 1 时真实地址在 wailian 字段（多为微信公众号文章），
     其余用 pid 拼站内正文页 https://www.gameres.com/{pid}.html
     （实测 pid=901202675 对应 https://www.gameres.com/901202675.html）。

分类过滤：
  只要「推荐 / 原创 / 产品 / 厂商 / 市场」5 类，按条目 tags 里的 tid 判断，
  任一 tid 命中白名单即保留，详见 ALLOWED_TAG_IDS 的注释。

采集窗口与滚动更新逻辑（与 scripts/crawl_gamelook.py 一致，输出不是全量覆盖）：
  新闻窗口 10 天。
  1. 读取已有输出文件（若存在）
  2. 从第一页起按 cursor 逐页翻，某一页所有条目都早于窗口起始日期就停止翻页
  3. 新旧数据按 url 去重合并（同一 url 用最新抓到的那条覆盖旧的）
  4. 只保留 published_at 日期部分 >= 窗口起始日期的条目
  5. 按 published_at 降序排序后写入文件
  注意"是否继续翻页"用的是**未经分类过滤**的原始条目时间：某一页可能整页都被
  白名单筛掉，若拿过滤后的结果判断会误判成"已翻到窗口外"而提前停止。

写文件保护：
  本次接口解析出的原始条目数为 0 才抛异常拒绝写（接口改版/字段失效）；原始条目
  正常、只是分类过滤或窗口筛出 0 条属正常情况，照常写入。

输出：
  data/gameres_news.json
    {"crawled_at": "...", "window_days": 10, "items": [
      {title, url, published_at, summary, author, game_name, post_id}, ...
    ]}
    （game_name 由标题里的《》/【】提取，判定不出时为空串；本站 tags 是频道分类
      而不是游戏名，故不作为 game_name 兜底。author 可能为空串，与游侠网一致仍
      输出该字段）
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
from game_name import derive_game_name  # noqa: E402
from utils import DEFAULT_HEADERS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawl_gameres")

SITE_BASE = "https://www.gameres.com"
LIST_URL = f"{SITE_BASE}/api/v1/portal/articles"
PAGE_SIZE = 50  # 接口上限，传 >50 返回 422

# dateline 是 Unix 秒，统一按北京时间输出
BEIJING_TZ = timezone(timedelta(hours=8))

# 分类白名单（按 tid 匹配，不要按 tname 文字匹配）：
#   推荐 4 / 原创 43 / 产品动态 6 / 厂商 1
#   市场(13) 展开为子标签: 38 职场 / 34 运营 / 47 海外 / 33 数据 / 46 AppStore / 40 Steam
# 两组分开写的原因（均为实测结论）：
#   1. 「产品」这一类的 tname 实际是"产品动态"、bieming 才是"产品"，按文字匹配会
#      整类漏掉，所以只认 tid。
#   2. 「市场」tid=13 是聚合父类，任何文章的 tags 里都不会出现 tid=13
#      （?category_id=13 返回 50 条，tags 里 0 个"市场"），必须展开成上面 6 个子标签。
# 不收：研发(31) 及其子标签(24/25/26/27/28/29)、观察(11)、活动(22)、专访(12)、
#       人工智能AI(50) 等。
ALLOWED_TAG_IDS = {4, 43, 6, 1, 38, 34, 47, 33, 46, 40}

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
NEWS_OUTPUT_PATH = os.path.join(DATA_DIR, "gameres_news.json")

# 采集窗口：新闻 [today - 9 天, today]，共 10 天
NEWS_WINDOW_DAYS = 10

MAX_PAGES = 30  # 兜底翻页上限，避免接口异常导致死循环

REQUEST_INTERVAL = 0.8  # 每次请求前的间隔（秒），避免给站点造成压力

# 摘要末尾的"阅读全文"类残留（可能带方括号/省略号/箭头等装饰）
READ_MORE_RE = re.compile(r"[\[\(（【]?\s*(阅读全文|查看全文|继续阅读|详情|更多)\s*[\]\)）】…\.>》]*\s*$")


def fetch_page(session, cursor=None, retries=2, backoff=1.5):
    """请求列表接口的一页，返回 (文章列表, next_cursor)，重试若干次后仍失败返回 None。

    cursor 为 None/空表示第一页。信封里 code != 200 属业务层失败，同样计入重试
    （json.JSONDecodeError 是 ValueError 的子类，与这里手工抛的 ValueError 一并捕获）。
    """
    params = {"page_size": PAGE_SIZE}
    if cursor:
        params["cursor"] = cursor
    for attempt in range(1, retries + 2):
        time.sleep(REQUEST_INTERVAL)
        try:
            resp = session.get(LIST_URL, params=params, headers=DEFAULT_HEADERS, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 200:
                raise ValueError(
                    f"接口返回业务错误 code={payload.get('code')} msg={payload.get('msg')}"
                )
            data = payload.get("data") or {}
            articles = data.get("list")
            if not isinstance(articles, list):
                logger.warning("游资网接口返回结构异常（data.list 非列表）：cursor=%s", cursor)
                return None
            return articles, (data.get("next_cursor") or "")
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                "请求游资网接口失败（第 %d 次）：cursor=%s，原因：%s", attempt, cursor, exc
            )
            if attempt <= retries:
                time.sleep(backoff * attempt)
    logger.error("请求彻底失败，放弃：cursor=%s", cursor)
    return None


def clean_summary(raw_html):
    """把 summary 清成纯文本摘要：去标签 + 反转义实体 + 去"阅读全文"残留。"""
    if not raw_html:
        return ""
    text = BeautifulSoup(raw_html, "html.parser").get_text(" ")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return READ_MORE_RE.sub("", text).strip()


def has_allowed_tag(article):
    """tags 里任一 tid 命中白名单即保留（见 ALLOWED_TAG_IDS 的注释，只认 tid）。"""
    for tag in article.get("tags") or []:
        if isinstance(tag, dict) and tag.get("tid") in ALLOWED_TAG_IDS:
            return True
    return False


def resolve_url(article):
    """算出条目真实可访问的地址，取不到返回空串。

    条目自带的 url 字段是 /wl?m=xxx 形式的站内 302 跳板，一律不输出：
    is_wailian == 1 时真实地址在 wailian，其余用 pid 拼站内正文页。
    """
    if article.get("is_wailian") == 1:
        wailian = (article.get("wailian") or "").strip()
        if wailian:
            return wailian
        logger.warning("游资网外链条目缺 wailian，回退站内地址：id=%s", article.get("id"))
    pid = article.get("pid")
    return f"{SITE_BASE}/{pid}.html" if pid else ""


def parse_article(article):
    """把单条接口文章对象转成输出条目，字段缺失返回 None。

    dateline 是 Unix 秒，按北京时间格式化；额外附带 pub_date（date 对象）供翻页
    判断，写文件前由调用方剔除。
    """
    title = html.unescape(article.get("subject") or "").strip()
    url = resolve_url(article)
    dateline = article.get("dateline")
    if not title or not url or not dateline:
        logger.warning("游资网条目字段缺失，跳过：id=%s", article.get("id"))
        return None
    try:
        published = datetime.fromtimestamp(int(dateline), BEIJING_TZ)
    except (TypeError, ValueError, OSError, OverflowError):
        logger.warning("游资网条目发布时间解析失败：%s（%s）", dateline, url)
        return None

    return {
        "title": title,
        "url": url,
        "published_at": published.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": clean_summary(article.get("summary")),
        "author": (article.get("author") or "").strip(),
        "post_id": article.get("id"),
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
    """按 cursor 逐页翻，返回 (窗口内条目列表, 原始解析条目数, 分类过滤后条目数, 实际翻页数)。

    停止翻页条件：本页所有条目都早于窗口起始日期（接口按时间倒序，后续页只会更旧），
    或接口不再返回 next_cursor。这里的"本页最早日期"取自**未经分类过滤**的条目，
    否则整页都被白名单筛掉时会误判成已翻出窗口。
    原始解析条目数用于区分"接口/字段失效"和"窗口内没有内容"。
    """
    session = requests.Session()
    items = []
    raw_count = 0
    allowed_count = 0
    cursor = None
    page = 1
    stopped_by_window = False
    while page <= MAX_PAGES:
        result = fetch_page(session, cursor)
        if result is None:
            logger.warning("新闻第 %d 页请求失败，停止翻页", page)
            break
        articles, next_cursor = result
        if not articles:
            logger.info("新闻第 %d 页返回 0 条，停止翻页", page)
            break
        raw_count += len(articles)

        page_items = [
            (article, parsed)
            for article, parsed in ((a, parse_article(a)) for a in articles)
            if parsed
        ]
        if not page_items:
            logger.warning("新闻第 %d 页 %d 条原始数据全部解析失败，停止翻页", page, len(articles))
            break

        oldest_on_page = min(parsed["pub_date"] for _article, parsed in page_items)
        page_allowed = [parsed for article, parsed in page_items if has_allowed_tag(article)]
        allowed_count += len(page_allowed)
        items.extend(parsed for parsed in page_allowed if parsed["pub_date"] >= window_start)
        logger.info(
            "新闻第 %d 页抓到 %d 条（命中分类 %d 条），本页最早日期 %s，窗口内累计 %d 条",
            page, len(page_items), len(page_allowed), oldest_on_page.isoformat(), len(items),
        )

        if oldest_on_page < window_start:
            stopped_by_window = True
            break
        if not next_cursor:
            logger.info("新闻第 %d 页没有 next_cursor，已到最后一页", page)
            break
        cursor = next_cursor
        page += 1

    if not stopped_by_window and page > MAX_PAGES:
        # 触到翻页上限而非"翻出窗口"退出：本次没能覆盖完整窗口，最早若干天会缺数据。
        # 稳态下与旧文件合并可能掩盖问题，必须显式告警避免长期沉默。
        logger.warning(
            "新闻翻页到上限 %d 页仍未覆盖到窗口起始日期 %s，本次可能缺少较早日期的数据",
            MAX_PAGES, window_start.isoformat(),
        )
    logger.info(
        "新闻采集完成，共翻 %d 页，原始 %d 条，命中分类 %d 条，窗口内 %d 条",
        min(page, MAX_PAGES), raw_count, allowed_count, len(items),
    )
    return items, raw_count, allowed_count, min(page, MAX_PAGES)


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


def apply_game_names(items):
    """对合并后的全部条目重算 game_name（只从标题的书名号提取，本站无游戏标签）。

    对「合并后」而不是「本次新抓到」的条目执行：game_name 是标题的纯函数，
    这样窗口内从旧 JSON 继承下来的老条目也会顺带补上，不需要单独的回填脚本。
    """
    for item in items:
        item["game_name"] = derive_game_name(item.get("title", ""))
    return items


def run_news(window_start):
    try:
        new_items, raw_count, _allowed_count, _pages = crawl_news(window_start)
    except Exception:
        logger.exception("新闻采集异常，保留旧数据不写入")
        return 1

    if raw_count == 0:
        logger.error("游资网接口解析到 0 条原始条目，疑似接口失效，终止写入以避免覆盖旧数据")
        return 1

    old_items = load_existing_items(NEWS_OUTPUT_PATH)
    merged = merge_and_filter(old_items, strip_internal_fields(new_items), window_start)
    apply_game_names(merged)
    named = sum(1 for item in merged if item.get("game_name"))
    logger.info("新闻合并后 %d 条，其中 %d 条识别出游戏名", len(merged), named)
    write_output(NEWS_OUTPUT_PATH, merged, "新闻", NEWS_WINDOW_DAYS)
    return 0


def main():
    today = date.today()
    window_start = today - timedelta(days=NEWS_WINDOW_DAYS - 1)
    logger.info(
        "开始抓取游资网新闻，窗口 %s ~ %s（%d 天）",
        window_start.isoformat(), today.isoformat(), NEWS_WINDOW_DAYS,
    )
    return run_news(window_start)


if __name__ == "__main__":
    sys.exit(main())






