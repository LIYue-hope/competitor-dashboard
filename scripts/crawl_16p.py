"""游资网（16p.com）新游开测表「上线」新游采集脚本。

数据源（站点自有 JSON 接口，不抓 HTML；16p.com 与 gameres.com 同一家后端）：
  https://www.gameres.com/api/public/v1/gamecenter/test_game?date=<YYYY-MM-DD>&type_range=2&p=<页号>

接口行为（均为实测结论）：
  1. 响应信封 {"code":200,"msg":"ok","data":{...}}，data 结构为
     {"next_end":0,"first_date":"2026-08-26","last_date":"2026-08-27",
      "dates":{"2026-08-26":[item,...],"2026-08-27":[...]}}。
     注意 data.dates 是 **dict**（key 为 YYYY-MM-DD）而不是数组。
  2. date 是**起始日期**，接口朝未来方向返回（date=2026-08-01 返回 08-01 起若干天）；
     p 从 1 递增翻页，next_end == 1 表示没有下一页。相邻两页的边界日期会重叠
     （p=1 的 last_date 与 p=2 的 first_date 是同一天），所以必须按日期合并、按游戏去重。
  3. 反爬同 gameres：带浏览器 UA（utils.DEFAULT_HEADERS）即可，全站 UTF-8。

筛选口径（每一条都踩过坑，改之前先看理由）：
  1. **必须显式传 type_range=2**（对应页面上的「国内游戏」tab）。实测不传 / 传 0 /
     传 4 都会静默退化成"不筛选"，混进大量 Steam 条目。
  2. 只保留 testtype.strip() == "上线" 的条目，**精确等于，不能用 startswith**：
     testtype 是自由文本不是枚举（实测 type_range=2 下有 20+ 种取值：限量删档测试 /
     删档测试 / 上线试玩 / 首测 / 公测 / 首发 …），且服务端没有 testtype 筛选参数
     （ps / page_size / limit 全被忽略）。用 startswith 会把「上线试玩」（试玩版，
     不是正式上线）带进来；部分取值带前导空格，所以必须 .strip() 后再比。
  3. **不要再叠加 game.area == "CN"**：实测 type_range=2 里存在 area == "STEAM" 的
     记录，但它在页面「国内游戏」tab 里就是显示的；反过来 type_range=1（海外）里
     有大量 area == "CN"。用 area 二次筛会和页面结果不一致。
  4. game.status 全样本恒为 1、artificial_weight 恒为 0，与是否上线无关，不要用。

详情接口（补分类与评分，列表接口这两个字段都没有）：
  https://www.gameres.com/api/public/v1/gamecenter/game?gameid=<gameid>
  实测参数名只认 gameid，写 id 会返回 {"status":0,"code":"404"}。
  取 data.game.gameplay（数组）→ categories、data.game.review_rate（10 分制）→ score。
  单个详情失败只降级这两个字段，不影响主流程。

采集窗口：
  [today, today + 6]（共 7 天，朝未来），与 scripts/crawl_haoyoukuaibao.py 一致。

输出：
  data/16p_upcoming.json
  {
    "crawled_at": "...",
    "days": [
      { "date": "2026-08-26", "date_label": "08月26日 今天", "games": [ ... ] }
    ]
  }
"""
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import DEFAULT_HEADERS, has_afk_grinding_tag, is_major_publisher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawl_16p")

LIST_URL = "https://www.gameres.com/api/public/v1/gamecenter/test_game"
DETAIL_URL = "https://www.gameres.com/api/public/v1/gamecenter/game"

# 游戏详情页在 16p.com 上，形如 https://www.16p.com/1953349.html
SITE_BASE = "https://www.16p.com"

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "data",
    "16p_upcoming.json",
)

# 采集窗口：当前日期 ~ 当前日期 + 6 天（共 7 天）
WINDOW_DAYS = 7

# 页面上的「国内游戏」tab，必须显式传（见模块 docstring 筛选口径 1）
TYPE_RANGE = 2

# 兜底翻页上限，避免接口异常（next_end 一直为 0）导致死循环
MAX_PAGES = 20

# 只采集 testtype 精确等于「上线」的条目
TARGET_TESTTYPE = "上线"

# 列表接口每次请求前的间隔（秒），避免给站点造成压力
REQUEST_INTERVAL = 0.8

# 详情接口串行请求之间的间隔（秒）
DETAIL_REQUEST_INTERVAL = 0.5

# companys 里的角色：2 = 发行商，1 = 研发商
PUBLISHER_ROLE_ID = 2
DEVELOPER_ROLE_ID = 1

# 偏移 → 展示用相对描述（与好游快爆 date_label 口径一致）
OFFSET_LABELS = {0: "今天", 1: "明天", 2: "后天"}

# 星期名（索引与 date.weekday() 一致，周一为 0）
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def fetch_json(session, url, params, interval=REQUEST_INTERVAL, retries=2, backoff=1.5):
    """请求接口并返回 data 对象，重试若干次后仍失败返回 None。

    信封里 code != 200 属业务层失败，同样计入重试（json.JSONDecodeError 是
    ValueError 的子类，与这里手工抛的 ValueError 一并捕获）。
    """
    for attempt in range(1, retries + 2):
        time.sleep(interval)
        try:
            resp = session.get(url, params=params, headers=DEFAULT_HEADERS, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 200:
                raise ValueError(
                    f"接口返回业务错误 code={payload.get('code')} msg={payload.get('msg')}"
                )
            return payload.get("data") or {}
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                "请求失败（第 %d 次）：%s params=%s，原因：%s", attempt, url, params, exc
            )
            if attempt <= retries:
                time.sleep(backoff * attempt)
    logger.error("请求彻底失败，放弃：%s params=%s", url, params)
    return None


def build_date_label(full_date, today):
    """生成展示用日期标签，口径与好游快爆/九游逐字一致。

    好游快爆的 date_label 直接取自页面分组标题，实测形如「08月19日 今天」
    「08月22日 周六」「08月25日 下周二」，即：今天/明天/后天用相对词，再往后
    用星期，跨到下一个自然周加「下」前缀。本接口只给 YYYY-MM-DD，没有 label，
    所以照 crawl_9game.py 的规则自己拼，保证几个面板的日期按钮观感统一。
    """
    label = "%02d月%02d日" % (full_date.month, full_date.day)

    offset = full_date.toordinal() - today.toordinal()
    if offset in OFFSET_LABELS:
        return label + " " + OFFSET_LABELS[offset]

    # 以周一为一周起点，比较目标日期所在自然周与本周的距离：
    # 同周 → 周X；下一周 → 下周X。7 天窗口内不会出现更远的情况，
    # 真出现了就只保留日期不加星期（加「下」已不准确）。
    week_delta = (
        (full_date.toordinal() - full_date.weekday())
        - (today.toordinal() - today.weekday())
    ) // 7
    weekday = WEEKDAY_LABELS[full_date.weekday()]
    if week_delta == 0:
        return label + " " + weekday
    if week_delta == 1:
        return label + " 下" + weekday
    return label


def pick_publisher(companys):
    """从 companys 里挑出展示用的公司名，取不到返回 None。

    优先发行商（company_role_id == 2），没有发行商才退回研发商（== 1）。
    同一家公司会因 data_source 不同重复出现，所以先按 name 去重。
    实测部分条目 companys 是空数组（约 37/858），此时返回 None。
    """
    names_by_role = {}
    for company in companys or []:
        if not isinstance(company, dict):
            continue
        name = (company.get("name") or "").strip()
        if not name:
            continue
        names = names_by_role.setdefault(company.get("company_role_id"), [])
        if name not in names:
            names.append(name)

    for role_id in (PUBLISHER_ROLE_ID, DEVELOPER_ROLE_ID):
        if names_by_role.get(role_id):
            return names_by_role[role_id][0]
    return None


def parse_item(item):
    """把列表接口的单个条目转成输出条目；非「上线」或关键字段缺失返回 None。

    categories / score 列表接口都没有，先留空，随后由 enrich_with_detail 补。
    gameid 是内部字段（详情接口要用），写文件前由 strip_internal_fields 剔除。
    """
    status_tag = (item.get("testtype") or "").strip()
    if status_tag != TARGET_TESTTYPE:
        return None

    game = item.get("game") or {}
    game_name = (game.get("gamename") or "").strip()
    gameid = item.get("gameid") or game.get("gameid")
    if not game_name or not gameid:
        logger.warning("条目关键字段缺失，跳过：gameid=%s gamename=%s", gameid, game_name)
        return None

    publisher = pick_publisher(game.get("companys"))
    return {
        "game_name": game_name,
        "categories": [],
        "score": None,
        "release_date": (item.get("testdate") or "").strip() or None,
        "status_tag": status_tag,
        "detail_url": f"{SITE_BASE}/{gameid}.html",
        "publisher": publisher,
        "is_major_publisher": is_major_publisher(publisher),
        "has_afk_grinding_tag": False,
        "gameid": gameid,
    }


def crawl(today):
    """按 p 翻页抓列表接口，返回窗口内的日期分组列表（按日期升序）。

    停止翻页条件：next_end == 1（没有下一页）、本页 last_date 已超出窗口末日
    （接口按日期升序朝未来返回，后面只会更晚）、或触到 MAX_PAGES 兜底上限。
    """
    window_end = date.fromordinal(today.toordinal() + WINDOW_DAYS - 1)
    session = requests.Session()
    grouped = {}
    raw_count = 0
    page = 1

    while page <= MAX_PAGES:
        data = fetch_json(
            session,
            LIST_URL,
            {"date": today.isoformat(), "type_range": TYPE_RANGE, "p": page},
        )
        if data is None:
            logger.warning("列表第 %d 页请求失败，停止翻页", page)
            break
        dates = data.get("dates")
        if not isinstance(dates, dict):
            logger.warning(
                "列表第 %d 页返回结构异常（data.dates 不是 dict），停止翻页", page
            )
            break
        if not dates:
            logger.info("列表第 %d 页没有日期分组，停止翻页", page)
            break

        page_raw = 0
        for iso_date in sorted(dates):
            items = dates[iso_date] or []
            page_raw += len(items)
            try:
                full_date = date.fromisoformat(iso_date)
            except ValueError:
                logger.warning("跳过无法解析的日期分组 key：%s", iso_date)
                continue
            # 窗口外的日期整块丢弃（接口一次会返回到几个月后）
            if full_date < today or full_date > window_end:
                continue
            day = grouped.setdefault(
                iso_date,
                {
                    "date": iso_date,
                    "date_label": build_date_label(full_date, today),
                    "games": [],
                },
            )
            for item in items:
                game = parse_item(item)
                if game:
                    day["games"].append(game)
        raw_count += page_raw

        last_date = (data.get("last_date") or "").strip()
        logger.info(
            "列表第 %d 页原始 %d 条，日期 %s ~ %s，窗口内累计 %d 条",
            page,
            page_raw,
            data.get("first_date") or "?",
            last_date or "?",
            sum(len(d["games"]) for d in grouped.values()),
        )

        if data.get("next_end") == 1:
            logger.info("列表第 %d 页 next_end=1，已到最后一页", page)
            break
        # 相邻两页边界日期会重叠，所以这里用 > 而不是 >=，避免漏掉窗口末日的条目
        if last_date and last_date > window_end.isoformat():
            logger.info(
                "列表第 %d 页最晚日期 %s 已越过窗口末日 %s，停止翻页",
                page, last_date, window_end.isoformat(),
            )
            break
        page += 1
    else:
        # 触到翻页上限而非正常退出：接口可能异常（next_end 一直为 0），显式告警
        logger.warning("列表翻页到上限 %d 页仍未结束，本次可能未覆盖完整窗口", MAX_PAGES)

    days = []
    for iso_date in sorted(grouped):
        day = grouped[iso_date]
        # 相邻页的边界日期重复下发，同一日期分组内按游戏名去重（只保留首次出现）
        deduped = {}
        for game in day["games"]:
            deduped.setdefault(game["game_name"], game)
        day["games"] = list(deduped.values())
        # 该日期下没有「上线」条目（全是各种测试）时不输出空分组
        if day["games"]:
            days.append(day)

    logger.info("列表采集完成，原始 %d 条，窗口内 %d 个日期分组", raw_count, len(days))
    return days


def enrich_with_detail(session, game):
    """访问详情接口，补全分类、评分与挂机/搬砖玩法判定。

    列表接口既没有分类也没有评分，只能逐款查详情：
      - categories ← data.game.gameplay（数组）；
      - score      ← data.game.review_rate（10 分制）。实测无人评分时为 0.0，
        此时保持 None，避免卡片上显示一个"0.0 分"；
      - 挂机/搬砖 ← data.game.gamedescription（简介）+ 分类一起送关键词匹配。
    单个详情失败只让上述字段降级，不中断整体采集。
    """
    gameid = game.get("gameid")
    if not gameid:
        return

    data = fetch_json(
        session, DETAIL_URL, {"gameid": gameid}, interval=DETAIL_REQUEST_INTERVAL
    )
    if not data:
        logger.warning("详情接口失败，分类/评分降级：gameid=%s", gameid)
        return

    detail = data.get("game") or {}

    gameplay = detail.get("gameplay")
    if isinstance(gameplay, list):
        game["categories"] = [str(c).strip() for c in gameplay if str(c).strip()]

    try:
        rate = float(detail.get("review_rate") or 0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate > 0:
        game["score"] = "%.1f" % rate

    game["has_afk_grinding_tag"] = has_afk_grinding_tag(
        detail.get("gamedescription") or "", " ".join(game["categories"])
    )


def strip_internal_fields(days):
    """去掉只在采集过程中用到的中间字段，避免写进输出文件。"""
    for day in days:
        for game in day["games"]:
            game.pop("gameid", None)
    return days


def build_output(days):
    return {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
    }


def main():
    today = date.today()
    window_end = date.fromordinal(today.toordinal() + WINDOW_DAYS - 1)
    logger.info(
        "开始抓取 游资网 新游开测表「%s」新游，窗口 %s ~ %s（%d 天）：%s",
        TARGET_TESTTYPE,
        today.isoformat(),
        window_end.isoformat(),
        WINDOW_DAYS,
        LIST_URL,
    )

    days = crawl(today)
    total_games = sum(len(d["games"]) for d in days)
    logger.info("解析完成，共 %d 个日期分组、%d 款上线新游", len(days), total_games)

    # 健全性检查：0 个日期分组通常意味着接口改版或筛选参数失效，而不是"未来 7 天
    # 真的一款都不上线"。直接终止写入，避免用空数据覆盖之前采集到的正常数据。
    if not days:
        logger.error("采集结果为空（0 个日期分组），疑似接口失效，终止写入以避免覆盖旧数据")
        return 1

    # 逐款游戏串行访问详情接口补全分类、评分与挂机/搬砖判定
    session = requests.Session()
    for day in days:
        for game in day["games"]:
            enrich_with_detail(session, game)

    output = build_output(strip_internal_fields(days))
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("写入 %s", OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())



