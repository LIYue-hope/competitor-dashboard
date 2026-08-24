"""TapTap 新游监测采集脚本。

数据源：
  - 列表页 https://www.taptap.cn/upcoming （新游预约列表，服务端渲染）
  - 详情页 https://www.taptap.cn/app/{id} （用于补充预约量级字段）

选型说明：
  列表页经核查为服务端渲染的静态 HTML（非异步 JS 渲染），未发现可直接调用的
  公开 JSON API（未找到类似 /webapiv2/... 的稳定接口返回新游列表数据），因此
  采用 requests + BeautifulSoup 直接解析 HTML，不引入 playwright。

注意：
  列表页本身不包含"预约量级"，该数据只在游戏详情页展示，因此本脚本会对每个
  游戏 ID 额外请求一次详情页。

已知限制：
  页面 CSS class 命名可能随 TapTap 前端版本更新而变化，下方选择器基于当前
  观察到的页面结构编写，如解析持续失败（大量条目被跳过），需要用浏览器
  开发者工具重新核对真实 DOM 结构后调整。
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
from utils import fetch_html, is_major_publisher, has_afk_grinding_tag  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawl_taptap")

LIST_URL = "https://www.taptap.cn/upcoming"
DETAIL_URL_TMPL = "https://www.taptap.cn/app/{app_id}"
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "taptap_upcoming.json"
)

APP_LINK_RE = re.compile(r"^/app/(\d+)")


def parse_list_page(html):
    """解析列表页，返回每个游戏的基础信息（名称、上线日期、类型标签、详情页链接等）。"""
    soup = BeautifulSoup(html, "html.parser")
    games = []

    # 页面除新游预约列表外，还有一个侧边栏"热门游戏"推荐区块
    # （class="web-aside-wrap"，如原神、我的世界、蛋仔派对等常驻热门游戏），
    # 该区块与本采集目标无关，必须排除，否则会把热门游戏误当成新游列表条目。
    # 新游预约列表真实容器为 class="app-upcoming__list"，内部按日期分组为
    # 多个 class="upcoming-item"，每个分组含日期标题（upcoming-item__title）
    # 和该日期下的游戏卡片列表（upcoming-item__event-list 下的 <a>）。
    upcoming_list = soup.find(class_="app-upcoming__list")
    if not upcoming_list:
        logger.warning(
            "未找到新游列表容器（class=app-upcoming__list），页面结构可能已变化，"
            "本次不解析出任何数据"
        )
        return games

    for item in upcoming_list.find_all(class_="upcoming-item"):
        title_node = item.find(class_="upcoming-item__title")
        date_text = title_node.get_text(strip=True) if title_node else None

        for anchor in item.find_all("a", href=APP_LINK_RE):
            href = anchor.get("href", "")
            match = APP_LINK_RE.match(href)
            if not match:
                continue

            try:
                game = _parse_game_card(anchor, match.group(1), date_text)
                if game:
                    games.append(game)
            except Exception:
                logger.exception("解析游戏卡片失败，跳过该条目，href=%s", href)

    # 去重（同一个 app_id 可能因图片/标题分别形成多个 <a> 而重复，或因带
    # 查询参数如 ?os=android 而 URL 不同但指向同一款游戏）
    deduped = {}
    for game in games:
        deduped[game["app_id"]] = game
    return list(deduped.values())


def _parse_game_card(anchor, app_id, upcoming_date):
    """从单个 <a href="/app/{id}"> 节点解析出一张游戏卡片的基础字段。

    实测真实 DOM 结构（见浏览器/requests 抓取样例）如下（简化）：
        <a href="/app/862677">
          <div class="event-type-label__title">首发</div>          <!-- 状态角标，可能没有 -->
          <div class="daily-event-app-info__title">魔幻砖域</div>   <!-- 游戏名称 -->
          <div class="tap-rating__less-rating-font">暂无评分</div>  <!-- 或 tap-rating__number 存具体分数 -->
          <div class="tap-label-tag">卡牌</div>...                 <!-- 类型标签，可能没有 -->
        </a>
    游戏名称固定在 class="daily-event-app-info__title" 的节点里，不再依赖
    文本片段顺序猜测，避免与日期分组文本、状态角标混淆导致错位。
    上线日期由调用方从所属 upcoming-item__title 传入（如"08/14 周五"）。
    """
    name_node = anchor.find(class_="daily-event-app-info__title")
    name = name_node.get_text(strip=True) if name_node else None
    if not name:
        return None

    status_node = anchor.find(class_="event-type-label__title")
    status_tag = status_node.get_text(strip=True) if status_node else None

    # 评分：有具体分数时在 tap-rating__number 节点里存数字；没有评分时
    # （新游预约期常见，属于正常情况，不是解析 bug）该位置直接展示
    # "暂无评分"四个字（class="tap-rating__less-rating-font"），
    # 实测列表卡片原文顺序就是"首发 → 魔幻砖域 → 暂无评分 → 卡牌..."。
    # 这里直接存该文案字符串（而不是 None），这样前端 v-if="game.score"
    # 对非空字符串判断为真，能正常展示"暂无评分"，无需改动前端逻辑。
    score_node = anchor.find(class_="tap-rating__number")
    if score_node:
        score = score_node.get_text(strip=True)
    else:
        less_rating_node = anchor.find(class_="tap-rating__less-rating-font")
        score = less_rating_node.get_text(strip=True) if less_rating_node else None

    tags = [
        tag_node.get_text(strip=True)
        for tag_node in anchor.find_all(class_="tap-label-tag")
        if tag_node.get_text(strip=True)
    ]

    return {
        "app_id": app_id,
        "name": name,
        "score": score,
        "status_tag": status_tag,
        "tags": tags,
        "release_date": upcoming_date,
        "detail_url": DETAIL_URL_TMPL.format(app_id=app_id),
    }



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

        # 上线日期：从详情页解析准确完整日期，覆盖列表页分组标题（如"08/14 周五"）。
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
            # 字段）时，回退用列表页分组标题里的"月/日"（如"08/19 周三"），
            # 按当前月份推断年份：仅当前月为 12 月且目标月为 1 月时归为明年，
            # 其余情况默认今年。统一归一化为 YYYY-MM-DD，与详情页格式一致。
            fallback_match = re.search(r"(\d{1,2})[/\-](\d{1,2})", game.get("release_date") or "")
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


def fetch_and_parse_list(attempts=3, wait_seconds=5):
    """抓取并解析列表页，解析不到任何游戏时整体重试。

    utils.fetch_html 只在 requests 抛异常时重试，而 TapTap 偶发返回 HTTP 200
    但正文缺少新游列表容器（反爬/限流返回的降级页面），这种响应不会触发
    fetch_html 的重试。CI runner 的出口 IP 更容易命中该情况，因此这里在
    "抓取 + 解析" 这一整层再加一次重试。
    """
    for attempt in range(1, attempts + 1):
        list_html = fetch_html(LIST_URL)
        if list_html:
            games = parse_list_page(list_html)
            if games:
                return games
            logger.warning("第 %d/%d 次解析到 0 款游戏", attempt, attempts)
        else:
            logger.warning("第 %d/%d 次列表页抓取失败", attempt, attempts)

        if attempt < attempts:
            logger.info("等待 %d 秒后重试", wait_seconds)
            time.sleep(wait_seconds)

    return []


def main():
    logger.info("开始抓取 TapTap 新游列表：%s", LIST_URL)
    games = fetch_and_parse_list()
    logger.info("列表页解析到 %d 款游戏", len(games))


    enriched = []
    for game in games:
        enriched.append(enrich_with_detail(game))

    records = build_output(enriched)

    # 健全性检查：列表页解析到 0 条记录基本只有两种可能——页面结构变化导致
    # 选择器失效，或者本次请求被限流/返回异常页面。两种情况都不应该用空
    # 列表覆盖掉之前采集到的正常数据，直接终止本次写入。
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
