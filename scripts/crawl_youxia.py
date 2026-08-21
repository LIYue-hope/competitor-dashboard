"""游侠网（ali213.net）新闻 & 评测滚动窗口采集脚本。

数据源：
  新闻主源：https://www.ali213.net/news/game/ （第 1 页），
            翻页规律 https://www.ali213.net/news/game/index_{page}.html（page 从 2 开始）
  新闻补充：https://www.ali213.net/news/new/ （全站最新，模板与 game 频道完全相同）
  评测列表：https://www.ali213.net/news/pingce/ （第 1 页），
            翻页规律 https://www.ali213.net/news/pingce/index_{page}.html

站点特点（均为实测结论）：
  1. 纯服务端渲染，无 JSON 接口，requests 直接抓即可解析；但响应不带 charset
     头，requests 会猜成 ISO-8859-1，列表页和详情页都必须显式指定 utf-8。
  2. 文章 URL 形如 /news/html/2026-8/1033129.html（月份无前导零），末段数字是
     全局唯一且单调递增的文章 id，可用来判断新旧、做去重辅助键。
  3. /news/game/ 是 /news/new/ 的严格子集，且滞后约 1 天：当天新发的稿子要隔天
     才进 game 频道。为了不丢当天资讯，用 /news/new/ 补充 id 大于本次 game 频道
     最大 id 的那一段。
  4. /news/new/ 的列表项和详情页都拿不到分类，无法直接判断某条是否为游戏资讯
     （实测 08-20 那天 164 条里只有 77 条进了 game 频道），只能用"减掉娱乐/动漫/
     影视/科技/电竞/大侠号六个兄弟频道"的集合差近似过滤。因此补充区条目打
     supplemented: true 标记，并在后续采集中自愈（见 merge_news）。
  5. PINGCE_LIST_SELECTOR 必须精确到 ul.ListB：同页 ul.ListA（精选评测）与
     ul.ListC（视频媒体）里的 div.time 分别是游戏时长和视频时长而非日期，且
     ul.ListC 的链接指向 bilibili 站外，混进来会静默产生错数据。

采集窗口与滚动更新逻辑（与 scripts/crawl_3dmgame.py 一致，输出文件不是全量覆盖）：
  新闻窗口 10 天、评测窗口 15 天（评测产出频率远低于新闻，实测常连续两周为 0）。
  1. 读取已有输出文件（若存在）
  2. 本次翻页抓取新数据，某一页所有条目都早于窗口起始日期就停止翻页
  3. 新旧数据按 url 去重合并（同一 url 用最新抓到的那条覆盖旧的）
  4. 只保留 published_at 日期部分 >= 窗口起始日期的条目
  5. 按 published_at 降序排序后写入文件

写文件保护（与 3DMGame 脚本的规则不同，务必注意）：
  3DMGame 用的是"本次窗口内 0 条就拒绝写"，但游侠网评测 15 天窗口内 0 条是常态
  （实测最新一条评测停在 2026-08-05），照搬会导致永远拒绝写。这里改成按"解析是
  否崩了"判断：列表页解析出的原始条目数为 0 才抛异常拒绝写（选择器失效/改版）；
  原始条目正常、只是窗口内筛出 0 条属正常情况，照常写入空 items。

输出：
  data/youxia_news.json
    {"crawled_at": "...", "window_days": 10, "items": [
      {title, url, published_at, summary, author, supplemented}, ...
    ]}
    （游侠网新闻列表没有游戏名，故不输出 game_name 字段）
  data/youxia_reviews.json
    {"crawled_at": "...", "window_days": 15, "items": [
      {title, url, score, published_at, comment_count, author, summary,
       platforms, cover}, ...
    ]}
    （评论数在列表页和详情页都是 JS 异步加载，拿不到，comment_count 固定 None）
"""
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
logger = logging.getLogger("crawl_youxia")

NEWS_CHANNEL_FIRST_PAGE_TMPL = "https://www.ali213.net/news/{channel}/"
NEWS_CHANNEL_PAGE_TMPL = "https://www.ali213.net/news/{channel}/index_{page}.html"

# 主源频道（只收游戏资讯，但滞后约 1 天）与补充频道（全站最新，含非游戏内容）
GAME_CHANNEL = "game"
LATEST_CHANNEL = "new"
# 用于给补充区做集合差的兄弟频道：命中这些频道的文章 id 视为非游戏资讯。
# 实测新鲜度：amuse/comic 到当天，movie/tech 到前一天，esports 较旧但仍有效；
# mobile 已停更、pingce/video 模板不同，都不适合放进来。zl 模板也不同，但能单独
# 提取文章链接，见下方 ZL_CHANNEL。
SIBLING_CHANNELS = ["amuse", "comic", "movie", "tech", "esports"]
SIBLING_PAGES = 3  # 每个兄弟频道抓前 3 页（20 条/页），足以覆盖 1~2 天

# zl（大侠号自媒体）用的是另一套订阅流模板，parse_news_page 在它上面解析出 0 条，
# 所以单独走「只提取文章链接」的轻量分支（集合差只需要 id，不需要标题日期）。
# 实测 https://www.ali213.net/news/zl/ 首页列表容器内有 10 条文章链接，且没有
# index_{page}.html 分页（index_2.html 返回 404，后续内容靠 JS「加载更多」拉），
# 因此只抓第 1 页。
ZL_CHANNEL = "zl"
# 只取列表容器内的链接：页头轮播与右侧推荐里也有文章链接，混进来会污染排除集
ZL_LIST_SELECTOR = ".subscribe-list .subscribe-li a[href]"

REVIEW_FIRST_PAGE_URL = "https://www.ali213.net/news/pingce/"
REVIEW_PAGE_URL_TMPL = "https://www.ali213.net/news/pingce/index_{page}.html"

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
NEWS_OUTPUT_PATH = os.path.join(DATA_DIR, "youxia_news.json")
REVIEWS_OUTPUT_PATH = os.path.join(DATA_DIR, "youxia_reviews.json")

# 采集窗口：新闻 [today - 9 天, today]，共 10 天
NEWS_WINDOW_DAYS = 10
# 评测窗口更长：评测产出频率远低于新闻（实测近 15 天为 0、近 30 天仅 3 条），
# 窗口太短前端会长期空着。
REVIEWS_WINDOW_DAYS = 15

NEWS_MAX_PAGES = 60  # 兜底翻页上限，避免站点结构异常导致死循环
SUPPLEMENT_MAX_PAGES = 10  # 补充区只覆盖 game 频道滞后的约 1 天，页数很少
REVIEWS_MAX_PAGES = 10  # 每页 6 条，10 页 60 条已覆盖约半年

REQUEST_INTERVAL = 1  # 每次请求前的间隔（秒），避免给站点造成压力

# 文章 URL 形如 /news/html/2026-8/1033129.html，月份无前导零，末段是文章 id
ARTICLE_URL_RE = re.compile(r"/news/html/(\d{4})-(\d{1,2})/(\d+)\.html")
# 详情页发布时间：<meta property="article:published_time" content="2026-08-05 10:32:43" />
PUBLISHED_TIME_RE = re.compile(r'article:published_time"\s+content="([\d\-: ]+)"')
AUTHOR_RE = re.compile(r'article:author"\s+content="([^"]*)"')
MONTH_DAY_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")


def fetch_page(url):
    """请求游侠网页面，返回文本，失败返回 None。

    游侠网响应头不带 charset，requests 会猜成 ISO-8859-1 导致中文全乱，
    apparent_encoding 在部分页面也会猜错，所以这里直接写死 utf-8。
    """
    time.sleep(REQUEST_INTERVAL)
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except requests.RequestException as exc:
        logger.warning("请求游侠网页面失败：%s，原因：%s", url, exc)
        return None


def news_page_url(channel, page):
    """新闻类频道的分页 URL：第 1 页是频道目录本身，第 N 页是 index_{N}.html。"""
    if page == 1:
        return NEWS_CHANNEL_FIRST_PAGE_TMPL.format(channel=channel)
    return NEWS_CHANNEL_PAGE_TMPL.format(channel=channel, page=page)


def parse_article_url(url):
    """从文章 URL 解析出 (年, 月, 文章 id)，不匹配返回 None。"""
    match = ARTICLE_URL_RE.search(url or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def resolve_published_date(url_year, url_month, month_day_text, url):
    """结合 URL 目录段的年月与列表页的 MM-DD 推断发布日期，失败返回 None。

    列表页只给 MM-DD 不给年份，直接按 %m-%d 裸解析会把跨年的 12 月条目算成当年。
    URL 目录段（如 /2026-8/）本身就是发布年月，比列表文本可靠，所以年份一律取
    URL，月份不一致时也以 URL 为准并告警（说明站点结构变了，需要复查）。
    """
    match = MONTH_DAY_RE.match((month_day_text or "").strip())
    if not match:
        logger.warning("新闻条目日期解析失败：%s（%s）", month_day_text, url)
        return None
    month, day = int(match.group(1)), int(match.group(2))
    if month != url_month:
        logger.warning(
            "新闻条目月份与 URL 目录段不一致：列表 %s vs URL %d-%d，以 URL 为准（%s）",
            month_day_text, url_year, url_month, url,
        )
        month = url_month
    try:
        return date(url_year, month, day)
    except ValueError:
        logger.warning("新闻条目日期非法：%d-%d-%d（%s）", url_year, month, day, url)
        return None


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


def parse_news_page(html):
    """解析新闻类频道列表页，返回本页条目列表。

    每条附带 article_id 与 pub_date（date 对象）供翻页判断和集合差使用，
    写文件前由调用方剔除。
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for box in soup.select(".news_list .n_lone"):
        a_title = box.select_one("h2.lone_t a")
        if not a_title:
            continue
        # 标题两个来源都可能被截断，所以取更长的那个：
        #   - title 属性：站点直接把未转义的英文双引号写进属性值（真实样例
        #     title="告别"头显梦"？苹果VR团队大裁员..."），html.parser 会在第二个
        #     引号处结束属性，只剩「告别」，后半截变成一个空值的伪属性；
        #   - 锚文本：站点自己用省略号截断成短标题（结尾 ... 或 …）。
        # 两种截断互不相关，取长者能互补，两者都为空才跳过该条。
        attr_title = (a_title.get("title") or "").strip()
        text_title = a_title.get_text(strip=True)
        title = attr_title if len(attr_title) >= len(text_title) else text_title
        url = (a_title.get("href") or "").strip()
        if not title or not url:
            continue

        parsed = parse_article_url(url)
        if not parsed:
            logger.warning("新闻条目 URL 不符合文章格式，跳过：%s", url)
            continue
        url_year, url_month, article_id = parsed

        summary_div = box.select_one(".lone_f_r_t")
        summary = summary_div.get_text(strip=True) if summary_div else ""

        # .lone_f_r_f 下第一个 span 是 MM-DD 日期，第二个是「小编：xxx」
        spans = box.select(".lone_f_r_f span")
        date_text = spans[0].get_text(strip=True) if spans else ""
        author = spans[1].get_text(strip=True) if len(spans) > 1 else ""
        # 去掉「小编：」前缀，只留作者名，与其它数据源的 author 字段口径一致
        author = re.sub(r"^小编[:：]\s*", "", author)



        pub_date = resolve_published_date(url_year, url_month, date_text, url)
        if pub_date is None:
            continue

        items.append(
            {
                "title": title,
                "url": url,
                "published_at": pub_date.strftime("%Y-%m-%d 00:00:00"),
                "summary": summary,
                "author": author,
                "article_id": article_id,
                "pub_date": pub_date,
            }
        )
    return items


def crawl_news_channel(channel, window_start, max_pages, label, min_article_id=None):
    """翻页采集某个新闻类频道，返回 (条目列表, 原始解析条目数, 实际翻页数)。

    停止翻页的条件（任一满足）：
      - 本页所有条目都早于窗口起始日期（后续页只会更旧）
      - min_article_id 不为 None 且本页最小文章 id 已 <= 它（补充区场景：
        再往后翻只会拿到 game 频道已覆盖的旧稿）
    原始解析条目数用于区分"解析失效"和"窗口内没有内容"。
    """
    items = []
    raw_count = 0
    page = 1
    stopped_by_window = False
    while page <= max_pages:
        html = fetch_page(news_page_url(channel, page))
        if not html:
            logger.warning("%s 第 %d 页请求失败，停止翻页", label, page)
            break

        page_items = parse_news_page(html)
        if not page_items:
            logger.info("%s 第 %d 页解析到 0 条，停止翻页", label, page)
            break
        raw_count += len(page_items)

        oldest_on_page = min(item["pub_date"] for item in page_items)
        min_id_on_page = min(item["article_id"] for item in page_items)
        items.extend(item for item in page_items if item["pub_date"] >= window_start)
        logger.info(
            "%s 第 %d 页抓到 %d 条，本页最早日期 %s，最小文章 id %d",
            label, page, len(page_items), oldest_on_page.isoformat(), min_id_on_page,
        )

        if oldest_on_page < window_start:
            stopped_by_window = True
            break
        if min_article_id is not None and min_id_on_page <= min_article_id:
            logger.info("%s 第 %d 页已翻到主源覆盖范围内，停止翻页", label, page)
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


def parse_zl_article_ids(html):
    """只从 zl 频道列表页提取文章 id 集合（不要标题/日期）。

    zl 用订阅流模板，parse_news_page 的 .news_list .n_lone 在它上面是 0 条，也拿
    不到规范的 MM-DD 日期；而集合差只需要 id，所以单独写这个轻量分支。
    """
    soup = BeautifulSoup(html, "html.parser")
    ids = set()
    for a in soup.select(ZL_LIST_SELECTOR):
        parsed = parse_article_url(a.get("href"))
        if parsed:
            ids.add(parsed[2])
    return ids


def collect_sibling_ids():
    """抓取兄弟频道（娱乐/动漫/影视/科技/电竞/大侠号）前若干页，返回文章 id 集合。

    这些 id 用于从 /news/new/ 补充区里减掉非游戏资讯。抓取失败的频道会告警但
    不中断：少一个频道只会让补充区多混进一点非游戏内容，不该拖垮整次采集。
    """
    sibling_ids = set()
    for channel in SIBLING_CHANNELS:
        channel_ids = set()
        for page in range(1, SIBLING_PAGES + 1):
            html = fetch_page(news_page_url(channel, page))
            if not html:
                logger.warning("兄弟频道 %s 第 %d 页请求失败，跳过", channel, page)
                continue
            for item in parse_news_page(html):
                channel_ids.add(item["article_id"])
        logger.info("兄弟频道 %s 收集到 %d 个文章 id", channel, len(channel_ids))
        sibling_ids |= channel_ids

    # zl 模板不同且无分页，单独抓第 1 页并只提取文章链接
    zl_html = fetch_page(news_page_url(ZL_CHANNEL, 1))
    if zl_html:
        zl_ids = parse_zl_article_ids(zl_html)
        logger.info("兄弟频道 %s 收集到 %d 个文章 id", ZL_CHANNEL, len(zl_ids))
        sibling_ids |= zl_ids
    else:
        logger.warning("兄弟频道 %s 请求失败，跳过", ZL_CHANNEL)

    logger.info("兄弟频道合计收集到 %d 个非游戏文章 id", len(sibling_ids))
    return sibling_ids


def crawl_news(window_start):
    """采集新闻：game 频道为主源，/news/new/ 补充 game 频道滞后的那一段。

    返回 (条目列表, game 频道 url 集合, game 频道最小 id, game 频道最大 id)。
    后三项供 merge_news 判断历史补充条目是否为误收。
    """
    game_items, raw_count, pages = crawl_news_channel(
        GAME_CHANNEL, window_start, NEWS_MAX_PAGES, "游戏资讯（game 频道）",
    )
    if raw_count == 0:
        raise RuntimeError("game 频道列表页解析到 0 条原始条目，疑似选择器失效")
    logger.info("game 频道采集完成，共翻 %d 页，窗口内 %d 条", pages, len(game_items))

    for item in game_items:
        item["supplemented"] = False

    game_urls = {item["url"] for item in game_items}
    game_ids = [item["article_id"] for item in game_items]
    min_game_id, max_game_id = min(game_ids), max(game_ids)

    supplement_items = crawl_news_supplement(window_start, max_game_id)
    return game_items + supplement_items, game_urls, min_game_id, max_game_id


def crawl_news_supplement(window_start, max_game_id):
    """从 /news/new/ 补充 id 大于 game 频道最大 id 的那一段（当天新稿）。

    /news/new/ 含全站内容且拿不到分类，只能减掉兄弟频道的 id 做近似过滤，
    留下的条目打 supplemented: true，后续采集中由 merge_news 自愈。
    """
    latest_items, raw_count, pages = crawl_news_channel(
        LATEST_CHANNEL, window_start, SUPPLEMENT_MAX_PAGES, "补充区（new 频道）",
        min_article_id=max_game_id,
    )
    if raw_count == 0:
        logger.warning("new 频道列表页解析到 0 条原始条目，本次跳过补充区")
        return []

    fresh_items = [item for item in latest_items if item["article_id"] > max_game_id]
    if not fresh_items:
        logger.info("补充区没有比 game 频道更新的条目，无需补充")
        return []

    sibling_ids = collect_sibling_ids()
    supplement_items = []
    for item in fresh_items:
        if item["article_id"] in sibling_ids:
            continue
        item["supplemented"] = True
        supplement_items.append(item)
    logger.info(
        "补充区共翻 %d 页，窗口内比主源新的 %d 条，减掉兄弟频道后保留 %d 条",
        pages, len(fresh_items), len(supplement_items),
    )
    return supplement_items


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


def merge_news(old_items, new_items, window_start, game_urls, min_game_id, max_game_id):
    """合并新旧新闻条目，并剔除已证伪的历史补充条目。

    自愈逻辑：旧数据里 supplemented=true 的条目，如果它的文章 id 落在本次 game
    频道覆盖的 id 区间内（min < id < max）却没出现在 game 结果里，说明当初的集合差
    误收了非游戏资讯，直接丢弃；id 仍大于 max_game_id 的说明 game 频道还没收录，
    继续保留。已进入 game 结果的条目会被本次的 supplemented=false 覆盖掉。
    """
    kept_old = []
    dropped = 0
    for item in old_items:
        url = item.get("url")
        if not url:
            continue
        parsed = parse_article_url(url)
        if (
            item.get("supplemented")
            and parsed
            and min_game_id < parsed[2] < max_game_id
            and url not in game_urls
        ):
            dropped += 1
            continue
        kept_old.append(item)
    if dropped:
        logger.info("剔除 %d 条已证伪的历史补充条目（非游戏资讯）", dropped)
    return merge_and_filter(kept_old, new_items, window_start)


def parse_review_page(html):

    """解析评测列表页 ul.ListB，返回本页条目（不含日期/作者，需再取详情页）。

    只取 ul.ListB：同页 ul.ListA 的 div.time 是游戏时长、ul.ListC 的 div.time 是
    视频时长且链接指向站外，混进来会静默产生错数据。
    """
    soup = BeautifulSoup(html, "html.parser")
    list_box = soup.select_one("ul.ListB")
    if not list_box:
        logger.warning("评测列表页未找到 ul.ListB，疑似改版")
        return []

    items = []
    for li in list_box.find_all("li", recursive=False):
        a_title = li.select_one("a.title")
        if not a_title:
            continue
        title = a_title.get_text(strip=True)
        url = (a_title.get("href") or "").strip()
        if not title or not url:
            continue

        score = None
        score_div = li.select_one("div.GmScore")
        if score_div:
            score_text = score_div.get_text(strip=True)
            try:
                score = float(score_text)
            except ValueError:
                # 评测可能还没打分（显示"暂无"之类），不算异常
                logger.info("评测条目评分无法解析：%s（%s）", score_text, url)

        platforms = [a.get_text(strip=True) for a in li.select("div.Tags a")]
        platforms = [name for name in platforms if name]

        desc_div = li.select_one("div.desc")
        summary = re.sub(r"\s+", " ", desc_div.get_text()).strip() if desc_div else ""

        # 封面是懒加载，真实地址在 data-original，src 属性根本不存在
        img = li.select_one("a.imgbg img")
        cover = (img.get("data-original") or "").strip() if img else ""

        items.append(
            {
                "title": title,
                "url": url,
                "score": score,
                "comment_count": None,
                "summary": summary,
                "platforms": platforms,
                "cover": cover,
            }
        )
    return items


def fetch_review_detail(url):
    """取评测详情页里的发布时间与作者，返回 (published_at 字符串, 作者)。

    列表页只有标题/评分/简介，日期和作者只在详情页的 meta 里。
    """
    html = fetch_page(url)
    if not html:
        return None, ""
    time_match = PUBLISHED_TIME_RE.search(html)
    if not time_match:
        logger.warning("评测详情页未找到发布时间：%s", url)
        return None, ""
    published_at = time_match.group(1).strip()
    author_match = AUTHOR_RE.search(html)
    author = author_match.group(1).strip() if author_match else ""
    return published_at, author


def crawl_reviews(window_start):
    """采集评测，返回 (窗口内条目列表, 原始解析条目数)。

    详情页请求较贵，先用 URL 目录段的年月做粗筛：年月早于窗口起始月的直接跳过，
    不去取详情页。翻页在"整页都早于窗口年月"时停止，但至少翻 2 页，避免首页偶发
    只剩置顶旧稿时提前收摊。
    """
    window_ym = (window_start.year, window_start.month)
    items = []
    raw_count = 0
    page = 1
    stopped_by_window = False
    while page <= REVIEWS_MAX_PAGES:
        url = REVIEW_FIRST_PAGE_URL if page == 1 else REVIEW_PAGE_URL_TMPL.format(page=page)
        html = fetch_page(url)
        if not html:
            logger.warning("评测第 %d 页请求失败，停止翻页", page)
            break

        page_items = parse_review_page(html)
        if not page_items:
            logger.info("评测第 %d 页解析到 0 条，停止翻页", page)
            break
        raw_count += len(page_items)

        all_older = True
        for item in page_items:
            parsed = parse_article_url(item["url"])
            if not parsed:
                logger.warning("评测条目 URL 不符合文章格式，跳过：%s", item["url"])
                continue
            if (parsed[0], parsed[1]) < window_ym:
                continue
            all_older = False
            published_at, author = fetch_review_detail(item["url"])
            if not published_at:
                continue
            if published_at[:10] < window_start.isoformat():
                continue
            item["published_at"] = published_at
            item["author"] = author
            items.append(item)

        logger.info("评测第 %d 页解析 %d 条，窗口内累计 %d 条", page, len(page_items), len(items))
        if all_older and page >= 2:
            stopped_by_window = True
            break
        page += 1

    if not stopped_by_window and page > REVIEWS_MAX_PAGES:
        logger.warning(
            "评测翻页到上限 %d 页仍未翻出窗口起始日期 %s，本次可能缺少较早日期的数据",
            REVIEWS_MAX_PAGES, window_start.isoformat(),
        )
    logger.info("评测采集完成，原始解析 %d 条，窗口内 %d 条", raw_count, len(items))
    return items, raw_count


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


def strip_internal_fields(items):
    """去掉只在采集过程中用到的中间字段，避免写进输出文件。"""
    for item in items:
        item.pop("article_id", None)
        item.pop("pub_date", None)
    return items


def run_news(window_start):
    try:
        new_items, game_urls, min_game_id, max_game_id = crawl_news(window_start)
    except Exception:
        logger.exception("新闻采集异常，保留旧数据不写入")
        return 1

    old_items = load_existing_items(NEWS_OUTPUT_PATH)
    merged = merge_news(
        old_items, strip_internal_fields(new_items), window_start,
        game_urls, min_game_id, max_game_id,
    )
    supplemented = sum(1 for item in merged if item.get("supplemented"))
    logger.info("新闻合并后 %d 条，其中补充区 %d 条", len(merged), supplemented)
    write_output(NEWS_OUTPUT_PATH, merged, "新闻", NEWS_WINDOW_DAYS)
    return 0


def run_reviews(window_start):
    try:
        new_items, raw_count = crawl_reviews(window_start)
    except Exception:
        logger.exception("评测采集异常，保留旧数据不写入")
        return 1

    if raw_count == 0:
        logger.error("评测列表页解析到 0 条原始条目，疑似解析失效，终止写入以避免覆盖旧数据")
        return 1

    # 与 3DMGame 不同：窗口内 0 条是游侠网评测的常态，照常写入空 items
    old_items = load_existing_items(REVIEWS_OUTPUT_PATH)
    merged = merge_and_filter(old_items, new_items, window_start)
    write_output(REVIEWS_OUTPUT_PATH, merged, "评测", REVIEWS_WINDOW_DAYS)

    return 0


def main():
    today = date.today()
    # 新闻与评测窗口长度不同，各自单独算窗口起始日期
    news_window_start = today - timedelta(days=NEWS_WINDOW_DAYS - 1)
    reviews_window_start = today - timedelta(days=REVIEWS_WINDOW_DAYS - 1)
    logger.info(
        "开始抓取游侠网新闻与评测，新闻窗口 %s ~ %s（%d 天），评测窗口 %s ~ %s（%d 天）",
        news_window_start.isoformat(), today.isoformat(), NEWS_WINDOW_DAYS,
        reviews_window_start.isoformat(), today.isoformat(), REVIEWS_WINDOW_DAYS,
    )
    news_result = run_news(news_window_start)
    reviews_result = run_reviews(reviews_window_start)
    return 0 if news_result == 0 and reviews_result == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
