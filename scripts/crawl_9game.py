"""九游 开测表「首发」新游采集脚本。

数据源：
  https://www.9game.cn/kc/ （开测表，服务端渲染）

选型说明：
  列表页与详情页均为服务端渲染的静态 HTML（requests 直接抓到即可拿到日期分组、
  游戏行、评分与简介），无需 JS 渲染，因此复用 utils.fetch_html（带重试）解析，
  不引入 playwright。站点响应头已声明 UTF-8，无需覆盖编码。

页面结构（简化）：
  <div class="des-table">
    <div class="des-table1">            <!-- 每块 = 一个日期分组 -->
      <div class="day">明天</div>        <!-- 也可能是 今天/后天/8-25/8月 -->
      <table><tbody>
        <tr>
          <td class="timetr"><span class="time">首发</span></td>   <!-- 注意：不是日期 -->
          <td class="nametr">
            <a class="img" title="点点英雄"><img></a>
            <a class="name" href="https://www.9game.cn/diandianyingxiong/"
               title="点点英雄（西游送十万抽）">点点英雄（西游送十万抽）</a>
          </td>
          <td class="stattr">首发</td>                             <!-- 测试状态 -->
          <td class="typetr">卡牌</td>                              <!-- 游戏分类 -->
          <td class="btntr">
            <a class="sbtn icon-down JS_REALNAME_DOWNLOAD" data-gameid="3132949"
               data-params='{"gameId":3132949,"name":"点点英雄",...}'>下载</a>
          </td>
        </tr>
      </tbody></table>
    </div>
  </div>

  「今日开测」板块与上面的 des-table 系列结构完全不同（无 table/td.stattr，
  状态与类型是「状态：/类型：」纯文本 + .na 值节点，且「类型」的值节点实测是
  写在 span 里的 <td class="na">，属于源站标签错乱，选择器不能限定标签名）：
  <div class="box today-new-server">
    <div class="box-title" id="todayOpen"><h2>今日开测</h2></div>
    <div class="box-text">
      <ul class="today-server-list">
        <li>
          <div class="pic" href="https://www.9game.cn/ynza/" title="一念长安">…</div>
          <div class="right-text">
            <p class="tit">
              <a class="name" href="https://www.9game.cn/ynza/" title="一念长安"
                 >一念长安（进长安城送VIP）</a>
            </p>
            <div class="type">
              <span class="type-con">状态：<span class="na">计费删档内测</span></span>
              <span class="type-con">类型：<td class="na">回合</td></span>
            </div>
          </div>
          <div class="other-btn">
            <td class="btntr">
              <a class="btn green JS_REALNAME_DOWNLOAD"
                 data-params='{"gameId":3122708,"name":"一念长安",...}'>游戏下载</a>
            </td>
          </div>
        </li>
      </ul>
    </div>
  </div>

  详情页（如 https://www.9game.cn/diandianyingxiong/）：
    <h2 class="score"><span class="score-detail">7.1</span></h2>   <!-- 九游评分 -->
    <div class="ngame-desc">游戏简介……</div>                        <!-- 简介，用于挂机/搬砖判定 -->

采集范围：
  - 「即将开测」（div.des-table1）：只保留 td.stattr 文本为「首发」的行，其余测试
    状态（计费删档内测、删档内测、赛季上线等）一律丢弃；无法解析成具体日期的分组
    标签（如「8月」）整块跳过。
  - 「今日开测」（div.box.today-new-server）：同样只保留状态为「首发」的条目，
    日期固定为今天，与「即将开测」中今天的分组按游戏名合并去重。
  - 「火爆开测」（div.des-table2）：日期全是已过去的开测日，不采集。

输出：
  data/9game_upcoming.json
  {
    "crawled_at": "...",
    "days": [
      { "date": "2026-08-20", "date_label": "08月20日 明天", "games": [ ... ] }
    ]
  }
"""
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import fetch_html, has_afk_grinding_tag  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawl_9game")

LIST_URL = "https://www.9game.cn/kc/"
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "data",
    "9game_upcoming.json",
)

# 只采集「首发」状态的游戏行
TARGET_STATUS = "首发"

# 详情页串行请求之间的间隔（秒），降低源站压力
DETAIL_REQUEST_INTERVAL = 0.5

# 日期分组标签形如 8-22 / 9-1（M-D，无年份）
MONTH_DAY_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")

# 相对日期标签 → 相对今天的天数偏移
RELATIVE_DAY_OFFSETS = {"今天": 0, "明天": 1, "后天": 2}

# 偏移 → 展示用相对描述（与好游快爆 date_label 口径一致）
OFFSET_LABELS = {0: "今天", 1: "明天", 2: "后天"}

# 星期名（索引与 date.weekday() 一致，周一为 0）
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 「今日开测」板块容器与条目
TODAY_BLOCK_SELECTOR = "div.box.today-new-server"
TODAY_ITEM_SELECTOR = "ul.today-server-list > li"

# 「今日开测」条目里「状态：xxx」「类型：xxx」的字段名前缀
TODAY_FIELD_LABEL_RE = re.compile(r"^(状态|类型)[：:]")


# 展示名末尾被括号包住的促销/事件后缀，如「点点英雄（西游送十万抽）」
EVENT_SUFFIX_RE = re.compile(r"[（(]([^（()）]+)[)）]\s*$")

# 游戏分类分隔符：/ 、 空格 等
CATEGORY_SPLIT_RE = re.compile(r"[/、,，\s]+")


def resolve_full_date(month, day, today):
    """把页面标签里的 M-D 转成完整日期。

    页面不含年份，规则：默认为今年；若月份小于当前月份，视为跨年到明年。
    这样保证"12月 → 1月"跨年过渡时不会错误退回上一年。
    """
    year = today.year
    if month < today.month:
        year += 1
    return date(year, month, day)


def build_date_label(full_date, today):
    """生成展示用日期标签，口径与好游快爆逐字一致。

    好游快爆的 date_label 直接取自页面分组标题，实测形如
    「08月19日 今天」「08月22日 周六」「08月25日 下周二」，
    即：今天/明天/后天用相对词，再往后用星期，跨到下一个自然周加「下」前缀。
    九游页面只给出「明天」或「8-25」这类标签，星期提示需要自己补，
    这里复刻上述规则，保证两个面板的日期按钮观感统一。
    """
    label = "%02d月%02d日" % (full_date.month, full_date.day)

    offset = full_date.toordinal() - today.toordinal()
    if offset in OFFSET_LABELS:
        return label + " " + OFFSET_LABELS[offset]

    # 以周一为一周起点，比较目标日期所在自然周与本周的距离：
    # 同周 → 周X；下一周 → 下周X；更远（九游偶尔出现「9-1」这类跨两周以上的
    # 标签）加「下」已不准确，此时只保留日期不加星期。
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


def parse_day_label(label, today):
    """解析日期分组标签，返回 (date, date_label)；无法解析时返回 (None, None)。

    标签实测有三种形态：
      - 今天/明天/后天 → 相对今天 +0/+1/+2 天；
      - M-D（如 8-25/9-1）→ 补年份，跨年顺延到下一年；
      - 只有月份没有日（如「8月」）→ 无法定位到具体日期，交由调用方跳过。
    """
    if label in RELATIVE_DAY_OFFSETS:
        full_date = date.fromordinal(today.toordinal() + RELATIVE_DAY_OFFSETS[label])
    else:
        m = MONTH_DAY_RE.match(label)
        if not m:
            return None, None
        full_date = resolve_full_date(int(m.group(1)), int(m.group(2)), today)

    return full_date, build_date_label(full_date, today)



def parse_kaice_table(html, today):
    """解析开测表页面，返回「首发」游戏的日期分组列表。"""
    soup = BeautifulSoup(html, "html.parser")

    blocks = soup.select("div.des-table > div.des-table1")
    if not blocks:
        logger.warning(
            "未找到日期分组容器（div.des-table > div.des-table1），页面结构可能已变化，"
            "本次不解析出任何数据"
        )
        return []

    # 同一日期可能被拆到多块，这里按日期合并（games 追加到同一分组）
    grouped = {}

    for block in blocks:
        day_node = block.find(class_="day")
        if not day_node:
            continue
        label = day_node.get_text(strip=True)

        full_date, date_label = parse_day_label(label, today)
        if not full_date:
            logger.warning("跳过无法解析成具体日期的分组标签：%s", label)
            continue

        iso_date = full_date.isoformat()
        day = grouped.setdefault(
            iso_date,
            {"date": iso_date, "date_label": date_label, "games": []},
        )

        for tr in block.select("table tbody tr"):
            game = _parse_game_row(tr)
            if game:
                day["games"].append(game)

    # 「今日开测」板块单独解析后并入今天的分组。该板块只是补充数据源，
    # 结构变更/解析异常时降级为空列表，不影响主数据源「即将开测」。
    try:
        today_games = _parse_today_block(soup)
    except Exception as exc:  # noqa: BLE001 - 补充数据源，异常一律降级
        logger.warning("「今日开测」板块解析失败，本次跳过该板块：%s", exc)
        today_games = []
    if today_games:

        iso_today = today.isoformat()
        day = grouped.setdefault(
            iso_today,
            {
                "date": iso_today,
                "date_label": build_date_label(today, today),
                "games": [],
            },
        )
        day["games"].extend(today_games)

    days = []

    for iso_date in sorted(grouped):
        day = grouped[iso_date]
        # 同一日期分组内按游戏名去重（只保留首次出现）
        deduped = {}
        for g in day["games"]:
            deduped.setdefault(g["game_name"], g)
        day["games"] = list(deduped.values())
        # 该日期下没有首发游戏（全是删档内测/赛季上线等）时不输出空分组
        if day["games"]:
            days.append(day)

    return days


def _extract_name_and_event(name_link, params_btn):
    """从名称链接 + 下载按钮提取 (game_name, event_desc, display_name)。

    「即将开测」与「今日开测」两个板块的名称口径完全一致，都是
    「干净名（促销/活动后缀）」的展示文本 + 带 data-params 的下载按钮，
    因此这段提取逻辑两处共用。
    """
    # 展示名（节点文本）可能带促销后缀，如「点点英雄（西游送十万抽）」；
    # title 属性实测是不带后缀的干净名，作为 game_name 的回退来源。
    display_name = name_link.get_text(strip=True)
    title_name = (name_link.get("title") or "").strip()

    # 干净游戏名优先取下载按钮 data-params 里的 name 字段，
    # 解析失败时退回 title 属性，再退回展示名文本。
    game_name = None
    if params_btn:
        try:
            game_name = (
                json.loads(params_btn["data-params"]).get("name") or ""
            ).strip() or None
        except (ValueError, TypeError) as exc:
            logger.warning("解析 data-params 失败（%s），回退到展示名：%s", exc, display_name)
    if not game_name:
        game_name = title_name or display_name

    # 事件描述：展示名末尾括号内的促销/事件文案（全角/半角括号都处理）
    event_desc = None
    m_event = EVENT_SUFFIX_RE.search(display_name)
    if m_event:
        event_desc = m_event.group(1).strip() or None

    return game_name, event_desc


def _parse_game_row(tr):
    """解析「即将开测」单条游戏 tr 节点，非「首发」行返回 None。"""
    stat_node = tr.find("td", class_="stattr")
    status_tag = stat_node.get_text(strip=True) if stat_node else ""
    if status_tag != TARGET_STATUS:
        return None

    name_link = tr.select_one("td.nametr a.name")
    if not name_link:
        return None

    game_name, event_desc = _extract_name_and_event(
        name_link, tr.select_one("td.btntr a[data-params]")
    )
    if not game_name:
        return None

    type_node = tr.find("td", class_="typetr")
    categories = []
    if type_node:
        categories = [
            c for c in CATEGORY_SPLIT_RE.split(type_node.get_text(strip=True)) if c
        ]

    href = (name_link.get("href") or "").strip()
    detail_url = href if href.startswith("http") else None

    return {
        "game_name": game_name,
        "categories": categories,
        "score": None,
        "event_desc": event_desc,
        "status_tag": status_tag,
        "detail_url": detail_url,
        "has_afk_grinding_tag": False,
    }


def _parse_today_block(soup):
    """解析「今日开测」板块，返回「首发」游戏列表（结构异常时返回空列表）。

    该板块（div.box.today-new-server）没有 table/td.stattr，状态与类型是
    div.type 下两个 span.type-con 内的「状态：xxx」「类型：xxx」文本，值节点
    统一带 class="na"（「类型」的值节点实测是错写在 span 里的 <td class="na">，
    所以按 class 取值、不限定标签名）。

    这里是补充数据源，任何解析异常只记 warning 并降级为空，
    不影响主数据源「即将开测」。
    """
    block = soup.select_one(TODAY_BLOCK_SELECTOR)
    if not block:
        logger.warning(
            "未找到「今日开测」板块容器（%s），跳过该板块", TODAY_BLOCK_SELECTOR
        )
        return []

    items = block.select(TODAY_ITEM_SELECTOR)
    if not items:
        logger.warning(
            "「今日开测」板块内未找到游戏条目（%s），跳过该板块", TODAY_ITEM_SELECTOR
        )
        return []

    games = []
    for li in items:
        try:
            game = _parse_today_item(li)
        except Exception as exc:  # noqa: BLE001 - 补充数据源，异常一律降级
            logger.warning("「今日开测」条目解析异常，已跳过：%s", exc)
            continue
        if game:
            games.append(game)

    logger.info(
        "「今日开测」板块共 %d 条，其中「%s」%d 条",
        len(items),
        TARGET_STATUS,
        len(games),
    )
    return games


def _parse_today_item(li):
    """解析「今日开测」单条 li 节点，非「首发」条目返回 None。"""
    fields = _parse_today_fields(li)
    status_tag = fields.get("状态", "")
    if status_tag != TARGET_STATUS:
        return None

    name_link = li.select_one("p.tit a.name")
    if not name_link:
        return None

    game_name, event_desc = _extract_name_and_event(
        name_link, li.select_one("a[data-params]")
    )
    if not game_name:
        return None

    categories = [c for c in CATEGORY_SPLIT_RE.split(fields.get("类型", "")) if c]

    href = (name_link.get("href") or "").strip()
    detail_url = href if href.startswith("http") else None

    return {
        "game_name": game_name,
        "categories": categories,
        "score": None,
        "event_desc": event_desc,
        "status_tag": status_tag,
        "detail_url": detail_url,
        "has_afk_grinding_tag": False,
    }


def _parse_today_fields(li):
    """把「今日开测」条目里的 span.type-con 解析成 {"状态": "...", "类型": "..."}。"""
    fields = {}
    for con in li.select("div.type span.type-con"):
        text = con.get_text(" ", strip=True)
        m = TODAY_FIELD_LABEL_RE.match(text)
        if not m:
            continue
        value_node = con.find(class_="na")
        value = (
            value_node.get_text(" ", strip=True)
            if value_node
            else text[m.end():].strip()
        )
        fields[m.group(1)] = value
    return fields



def enrich_with_detail(game):
    """访问游戏详情页，补全九游评分与挂机/搬砖玩法判定。

    - 评分：h2.score span.score-detail 文本（取不到保持 None）；
    - 挂机/搬砖：只把 div.ngame-desc 的简介文本送入关键词匹配，
      避免整页文本（导航、推荐位等）造成误判。
    单个详情页失败只记 warning 并让上述字段降级，不中断整体采集。
    """
    url = game.get("detail_url")
    if not url:
        return

    html = fetch_html(url)
    if not html:
        logger.warning("详情页抓取失败，评分与挂机判定降级：%s", url)
        return

    soup = BeautifulSoup(html, "html.parser")

    score_node = soup.select_one("h2.score span.score-detail")
    if score_node:
        game["score"] = score_node.get_text(strip=True) or None

    desc_node = soup.find(class_="ngame-desc")
    if desc_node:
        game["has_afk_grinding_tag"] = has_afk_grinding_tag(
            desc_node.get_text(" ", strip=True)
        )


def build_output(days):
    return {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
    }


def main():
    logger.info("开始抓取 九游 开测表首发新游：%s", LIST_URL)
    html = fetch_html(LIST_URL, timeout=15)
    if not html:
        logger.error("开测表页面抓取失败，终止本次采集")
        return 1

    today = date.today()
    days = parse_kaice_table(html, today)
    total_games = sum(len(d["games"]) for d in days)
    logger.info(
        "解析完成，共 %d 个日期分组、%d 款首发游戏", len(days), total_games
    )

    # 健全性检查：0 个日期分组通常意味着开测表选择器已失效（页面结构变化），
    # 而不是"真的一款首发都没有"。直接终止写入，避免用空数据覆盖旧数据。
    if not days:
        logger.error("采集结果为空（0 个日期分组），疑似解析失效，终止写入以避免覆盖旧数据")
        return 1

    # 逐款游戏串行访问详情页补全评分与挂机/搬砖判定（当前量级约 10 余款）
    for day in days:
        for game in day["games"]:
            enrich_with_detail(game)
            time.sleep(DETAIL_REQUEST_INTERVAL)

    output = build_output(days)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("写入 %s", OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
