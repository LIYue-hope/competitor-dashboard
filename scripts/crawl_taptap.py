"""TapTap 新游监测采集脚本。

数据源：
  - 新游列表：webapiv2 日历接口
    GET https://www.taptap.cn/webapiv2/calendar/v1/upcoming?type=1&limit=10
    响应形如 {"success":true,"now":..,"data":{"list":[{"day":<北京当日0点unix秒>,
    "list":[<event>...]}...],"prev_page":"","next_page":""}}；每个 event 的
    app_card_info 自带标题、评分、类型标签、发行商、关注/评价/讨论量级等完整卡片字段。
  - 详情页 https://www.taptap.cn/app/{id} （用于补充发行商、预约量级等字段）

改版说明（2026-09-02 前后）：
  原 SSR 列表页 https://www.taptap.cn/upcoming 已重做为 Nuxt SPA（今日游戏 /
  app-calendar），旧容器 class="app-upcoming__list" 已不存在，SSR HTML 里只剩
  SPA 壳 + __NUXT_DATA__（devalue 扁平图，不值得解析），导致旧解析链路持续拿到
  0 条。因此本脚本改用与 crawl_taptap_rank.py 同款的 webapiv2 JSON 接口，
  不再解析 HTML 列表页。

已知坑：
  - 接口必须带 X-UA 请求头（不带直接 400 INVALID_XUA），并带上常规 UA/Referer；
  - limit 上限 10（传 20+ 直接 400），type=1 才有数据（0/2..7 为空）；
  - day 按北京时区当日 0 点给出，转日期必须用 +8 时区；
  - 预约量级等统计只在游戏详情页展示，因此本脚本仍会对每个游戏 ID 额外请求一次详情页；
  - next_page 为空表示没有更多页（实测如此）；万一非空需继续拉（相对路径前面补
    https://www.taptap.cn，最多翻 3 页保险）。

输出：
  data/taptap_upcoming.json，游戏对象扁平数组（schema 与旧 SSR 版保持一致）。
"""
import json
import logging
import os
import re
import sys
import time

from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import fetch_html, fetch_json, is_major_publisher, has_afk_grinding_tag  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawl_taptap")

DETAIL_URL_TMPL = "https://www.taptap.cn/app/{app_id}"
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "taptap_upcoming.json"
)

# webapiv2 日历接口（与 crawl_taptap_rank.py 同款调用方式）。
# type=1 才有数据（0/2..7 为空）；limit 上限 10（传 20+ 直接 400）。
UPCOMING_API_URL = "https://www.taptap.cn/webapiv2/calendar/v1/upcoming"
UPCOMING_TYPE = "1"
PAGE_LIMIT = 10
# 保险上限：实测 next_page 为空，翻页逻辑仅为接口行为变化时兜底
MAX_PAGES = 3

# 接口要求的客户端标记，不带 X-UA 会直接 400 INVALID_XUA（照抄 crawl_taptap_rank.py）
X_UA = (
    "V=1&PN=WebApp&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=PC"
    "&DS=Android&UID=0&OS=Windows&CH=website"
)

# 北京时区（固定 +8，无夏令时）：接口的 day 是北京当日 0 点的 unix 秒
BEIJING_TZ = timezone(timedelta(hours=8))


def _fetch_upcoming_page(url):
    """GET 一页 upcoming JSON。成功返回 payload dict，失败返回 None。

    utils.fetch_json 已合并 DEFAULT_HEADERS（常规 UA / Accept-Language），
    这里再补 X-UA 与 Referer 两个 webapiv2 必需的请求头。
    """
    headers = {"X-UA": X_UA, "Referer": "https://www.taptap.cn/"}
    try:
        payload = fetch_json(url, headers=headers).json()
    except Exception:
        logger.exception("upcoming 接口请求失败：%s", url)
        return None
    if not isinstance(payload, dict) or payload.get("success") is not True:
        logger.warning("upcoming 接口返回异常结构，url=%s", url)
        return None
    return payload


def _fetch_day_groups():
    """按 next_page 翻页拉取 upcoming 接口，返回所有 day 分组原始列表。

    任一页请求失败/结构异常时返回 None，与"正常返回但分组为空"的 [] 区分，
    便于外层把两种情况分别按"抓取失败"与"解析到 0 款"记日志。
    """
    url = "%s?type=%s&limit=%d" % (UPCOMING_API_URL, UPCOMING_TYPE, PAGE_LIMIT)
    groups = []
    for _ in range(MAX_PAGES):
        payload = _fetch_upcoming_page(url)
        if payload is None:
            return None
        data = payload.get("data") or {}
        page_groups = data.get("list") or []
        groups.extend(page_groups)
        next_page = data.get("next_page") or ""
        if not next_page:
            break
        if next_page.startswith("/"):
            url = "https://www.taptap.cn" + next_page
        elif next_page.startswith("http"):
            url = next_page
        else:
            logger.warning("无法识别的 next_page，停止翻页：%r", next_page)
            break
    return groups


def _day_to_iso(day):
    """day 是北京时区当日 0 点的 unix 秒，转成 YYYY-MM-DD；解析失败返回 None。"""
    try:
        return datetime.fromtimestamp(int(day), tz=BEIJING_TZ).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _event_to_game(event, day_iso):
    """把单个 event 摊平成一张基础游戏 dict，字段缺失到无法构成记录时返回 None。

    返回 dict 的 key 与旧 SSR 版 parse_list_page 的产物保持一致：
    app_id / name / score / status_tag / tags / release_date / detail_url。
    """
    app = event.get("app_card_info") or {}
    if not isinstance(app, dict):
        return None

    game_id = event.get("game_id")
    if not game_id:
        return None

    title = app.get("title") or ""
    if isinstance(title, dict):
        title = title.get("text") or ""
    name = str(title).strip()
    if not name:
        return None

    # 评分：有 rating.score 时取字符串（如"7.4"），没有评分的新游保持 None，
    # 前端按 v-if="game.score" 自行决定展示与否。
    stat = app.get("stat") or {}
    rating = stat.get("rating") if isinstance(stat, dict) else None
    score = None
    if isinstance(rating, dict) and rating.get("score") is not None:
        score = str(rating.get("score")).strip() or None

    tags = [
        str(tag.get("value")).strip()
        for tag in app.get("tags") or []
        if isinstance(tag, dict) and tag.get("value")
    ]
    tags = [t for t in tags if t]

    return {
        "app_id": str(game_id),
        "name": name,
        "score": score,
        "status_tag": event.get("sub_event_type_title"),
        "tags": tags,
        "release_date": day_iso,
        "detail_url": DETAIL_URL_TMPL.format(app_id=game_id),
    }


def parse_day_groups(day_groups):
    """把接口的 day 分组列表摊平成基础游戏 dict 列表。

    同一款游戏在同一天可能有多个 event（如首发 + 预下载），不同日期分组间
    也可能重复出现，这里按 app_id 去重、保留第一次出现的记录。
    """
    games = []
    seen = set()
    for group in day_groups or []:
        if not isinstance(group, dict):
            continue
        day_iso = _day_to_iso(group.get("day"))
        for event in group.get("list") or []:
            if not isinstance(event, dict):
                continue
            game = _event_to_game(event, day_iso)
            if not game or game["app_id"] in seen:
                continue
            seen.add(game["app_id"])
            games.append(game)
    return games


def fetch_and_parse_list(attempts=3, wait_seconds=5):
    """抓取并解析 upcoming 接口，解析不到任何游戏时整体重试。

    utils.fetch_json 只在 requests 抛异常时重试，而 TapTap 偶发返回 HTTP 200
    但正文缺少预期结构（反爬/限流返回的降级响应），这种响应不会触发其重试。
    CI runner 的出口 IP 更容易命中该情况，因此这里在"抓取 + 解析"这一整层
    再加一次重试（语义与原 SSR 列表页版本一致）。
    """
    for attempt in range(1, attempts + 1):
        day_groups = _fetch_day_groups()
        if day_groups is None:
            logger.warning("第 %d/%d 次 upcoming 接口抓取失败", attempt, attempts)
        else:
            games = parse_day_groups(day_groups)
            if games:
                return games
            logger.warning("第 %d/%d 次接口解析到 0 款游戏", attempt, attempts)

        if attempt < attempts:
            logger.info("等待 %d 秒后重试", wait_seconds)
            time.sleep(wait_seconds)

    return []


def extract_metric(page_text, label):
    """从详情页纯文本里取「关注/评价/讨论」量级，解析失败返回 None。"""
    if not page_text or not label:
        return None
    match = re.search(
        r"%s\s*\n?\s*([\d.]+(?:[ \t]*万)?)" % re.escape(label),
        page_text,
    )
    if not match:
        return None
    return match.group(1).replace(" ", "").strip()


def enrich_with_detail(game):
    """请求详情页，补充发行商、预约量级、游戏简介等字段。"""
    html = fetch_html(game["detail_url"])
    if not html:
        logger.warning("详情页请求失败，跳过补充字段：%s", game["detail_url"])
        return game

    try:
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text(separator="\n", strip=True)

        # 预约量级：详情页原文格式不固定，可能是"预约\n2390"（纯数字，
        # 数字后紧跟换行/结束），也可能是"预约\n214 万"（数字与"万"字
        # 之间有一个空格）。正则捕获组用 [\d.]+(?:\s*万)? ——"万"字整体
        # 作为可选的非捕获分组，只有在紧跟"万"字（前面允许有限的单个空格）
        # 时才会被纳入结果，避免了两个历史问题：
        #   1) 把结尾 \s* 写在"万"字前会连着把后面的换行也吞进捕获组
        #      （出现"2390\n"这种脏数据）；
        #   2) 把"万"字前的空格完全禁止，会导致"214 万"这种真实存在空格
        #      的场景只匹配到"214"，丢掉"万"字（本次修复的问题）。
        # 最终统一在赋值时移除内部空格并 strip，得到"2390"或"214万"。
        reservation = None
        reservation_match = re.search(
            r"预约\s*\n?\s*([\d.]+(?:[ \t]*万)?)", page_text
        )
        if reservation_match:
            # strip() + 去除内部空格作为兜底，确保最终值不带任何空白字符。
            reservation = reservation_match.group(1).replace(" ", "").strip()

        # 发行商：形如"供应商 杭州网易雷火科技有限公司"
        publisher = None
        publisher_match = re.search(r"供应商\s*([^\n]+)", page_text)
        if publisher_match:
            publisher = publisher_match.group(1).strip()

        # 上线日期：优先用详情页解析到的准确完整日期，覆盖基础记录里接口给的日期。
        # 详情页存在两种日期字面格式：
        #   1) "2026/08/21"（斜杠分隔，见诡秘之主/菜鸡梦想家）
        #   2) "2026-08-22"（连字符分隔，见江城创业记）
        # 二者都紧跟在"上线日期"文案之后（中间可能有冒号、空格、换行等分隔字符），
        # 因此这里用一条兼容正则匹配。捕获到日期后统一归一化为 YYYY-MM-DD。
        release_match = re.search(
            r"上线日期[^\d]{0,10}(20\d{2})[/\-](\d{1,2})[/\-](\d{1,2})", page_text
        )
        if release_match:
            y, m, d = release_match.groups()
            game["release_date"] = f"{y}-{int(m):02d}-{int(d):02d}"
        else:
            # 详情页没有完整日期（如"漫画群星：大集结"只标"限量测试"，无上线日期
            # 字段）时，保留基础记录给的日期。基础记录现在直接来自接口 day 字段、
            # 已经是完整 YYYY-MM-DD，不能再丢进 MM/DD 正则二次改写——
            # "2026-09-09"会被错切成 "26-09"。只有该字段还不是完整日期（旧 SSR
            # 版传入的"MM/DD 周几"分组标题等）时才走旧的回退逻辑：解析"月/日"，
            # 按当前月份推断年份（仅当前月为 12 月且目标月为 1 月时归为明年，
            # 其余情况默认今年），统一归一化为 YYYY-MM-DD。
            release_date = game.get("release_date") or ""
            if not re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", release_date):
                fallback_match = re.search(r"(\d{1,2})[/\-](\d{1,2})", release_date)
                if fallback_match:
                    m, d = int(fallback_match.group(1)), int(fallback_match.group(2))
                    today = datetime.now(timezone.utc) + timedelta(hours=8)
                    year = today.year + 1 if today.month == 12 and m == 1 else today.year
                    try:
                        game["release_date"] = f"{year}-{m:02d}-{d:02d}"
                    except ValueError:
                        pass

        # 挂机/搬砖玩法判定依据"游戏介绍"与"开发者的话"两段文本：
        #   - 游戏介绍：class="app-intro__summary"（简介摘要），退化到 app-intro__item；
        #   - 开发者的话：class="text-modal__content"（详情页仅此一处存放开发者寄语）。
        # 二者文本 + 类型标签一起送入关键词匹配，命中则前端在卡片右上角标注黄色五角星。
        intro_node = soup.find(class_="app-intro__summary") or soup.find(
            class_="app-intro__item"
        )
        intro_text = intro_node.get_text(" ", strip=True) if intro_node else ""
        dev_node = soup.find(class_="text-modal__content")
        dev_text = dev_node.get_text(" ", strip=True) if dev_node else ""

        game["publisher"] = publisher
        game["reservation_count"] = reservation
        game["follow_count"] = extract_metric(page_text, "关注")
        game["review_count"] = extract_metric(page_text, "评价")
        discussion = extract_metric(page_text, "讨论")
        if discussion is None:
            discussion = extract_metric(page_text, "帖子")
        game["discussion_count"] = discussion
        game["is_major_publisher"] = is_major_publisher(publisher)
        game["has_afk_grinding_tag"] = has_afk_grinding_tag(
            intro_text, dev_text, " ".join(game.get("tags", []))
        )
    except Exception:
        logger.exception("解析详情页结构失败，跳过字段补充：%s", game["detail_url"])

    return game


def build_output(games):
    """组装最终输出 schema。"""
    now = datetime.now(timezone.utc).isoformat()
    records = []
    for game in games:
        records.append(
            {
                "game_name": game.get("name"),
                "publisher": game.get("publisher"),
                "release_date": game.get("release_date"),
                "categories": game.get("tags", []),
                "reservation_count": game.get("reservation_count"),
                "follow_count": game.get("follow_count"),
                "review_count": game.get("review_count"),
                "discussion_count": game.get("discussion_count"),
                "is_major_publisher": bool(game.get("is_major_publisher")),
                "has_afk_grinding_tag": bool(game.get("has_afk_grinding_tag")),
                "score": game.get("score"),
                "status_tag": game.get("status_tag"),
                "source_url": game.get("detail_url"),
                "crawled_at": now,
            }
        )
    return records


def main():
    logger.info(
        "开始抓取 TapTap 新游列表接口：%s?type=%s&limit=%d",
        UPCOMING_API_URL,
        UPCOMING_TYPE,
        PAGE_LIMIT,
    )
    games = fetch_and_parse_list()
    logger.info("接口解析到 %d 款游戏", len(games))

    enriched = []
    for game in games:
        enriched.append(enrich_with_detail(game))

    records = build_output(enriched)

    # 健全性检查：解析到 0 条记录基本只有两种可能——接口改版导致字段失效，
    # 或者本次请求被限流/返回异常响应。两种情况都不应该用空列表覆盖掉之前
    # 采集到的正常数据，直接终止本次写入。
    if not records:
        logger.error("采集结果为空（0 条记录），疑似解析失效，终止写入以避免覆盖旧数据")
        return 1

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    logger.info("采集完成，共写入 %d 条记录到 %s", len(records), OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
