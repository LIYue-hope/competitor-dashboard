"""好游快爆 新游时间线采集脚本。

数据源：
  https://www.3839.com/timeline.html （即将上线/预下载/测试时间线，服务端渲染）

选型说明：
  页面为服务端渲染的静态 HTML（requests 直接抓到即可看到所有日期分组与游戏列表，
  无需 JS 渲染），因此采用 requests + BeautifulSoup 直接解析，不引入 playwright。

注意：
  好游快爆响应头 Content-Type 未声明字符集，requests 会默认按 ISO-8859-1 解码，
  导致中文乱码，必须显式使用 apparent_encoding（本站实际为 UTF-8）。

页面结构（简化）：
  <ul>  <!-- 顶部 tab 控件 -->
    <li rel="0" class="on">全部</li>
    <li rel="1">即将上线</li>
    <li rel="2">即将测试</li>
    <li rel="3">即将更新</li>
    <li rel="4">独家</li>
  </ul>
  <div class="panelList" rel="0">  <!-- "全部"面板，含所有类型的时间线 foreCard -->
    <div class="foreCard">...</div>
  </div>
  <div class="panelList" rel="1" style="display:none">  <!-- "即将上线"面板 -->
    <div class="foreCard">
      <div class="foreCard-hd">08月17日 今天</div>   <!-- 日期分组标题；也可能是"抢先爆料"（无日期，需跳过）-->
      <div class="foreCard-bd">
        <ul class="foreList">
          <li>
            <a>
              <div class="con">
                <div class="name"><em>游戏名</em><span class="g-type-pc">PC/主机</span></div>
                                            <!-- 角标类名带后缀（g-type-xx），也可能是无文本图标 <i class="it-ico ghot"> -->
                <p class="tags"><span class="it">类型标签</span>...</p>
                <div class="info">
                  <span class="score">9.6</span>       <!-- 可能无 -->
                  <span>10:00 删档测试</span>            <!-- 事件文案 -->
                </div>
              </div>
            </a>
          </li>
        </ul>
      </div>
    </div>
  </div>
  <div class="panelList" rel="2" style="display:none">...</div>  <!-- 即将测试等 Tab -->

采集范围：
  只解析 rel="1"（"即将上线"）面板下的 foreCard，避免"即将测试""即将更新""独家"
  等其他 Tab 的时间线数据混入。所有 Tab 面板都随初始 HTML 一次性下发，
  切换 Tab 只是前端 CSS display 显隐，不需要额外请求。

输出：
  data/haoyoukuaibao_upcoming.json
  {
    "crawled_at": "...",
    "days": [
      { "date": "2026-08-17", "date_label": "08月17日 今天", "games": [ ... ] }
    ]
  }
"""
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timezone

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import DEFAULT_HEADERS, has_afk_grinding_tag  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawl_haoyoukuaibao")

LIST_URL = "https://www.3839.com/timeline.html"
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "data",
    "haoyoukuaibao_upcoming.json",
)

# 采集窗口：当前日期 ~ 当前日期 + 6 天（共 7 天）
WINDOW_DAYS = 7

DATE_HEAD_RE = re.compile(r"^(\d{1,2})月(\d{1,2})日")


def fetch_page(url):
    """请求 3839 页面并按 apparent_encoding 解码，返回文本。

    好游快爆响应头未声明字符集，requests 会默认按 ISO-8859-1 解码导致中文乱码，
    时间线页与详情页均需覆盖为实际编码（UTF-8）后再解析。
    """
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
        # 站点未在响应头声明字符集，需要覆盖为实际编码（UTF-8）
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except requests.RequestException as exc:
        logger.error("请求 3839 页面失败：%s，原因：%s", url, exc)
        return None


def resolve_full_date(month, day, today):
    """把页面标题里的 MM月DD日 转成完整日期。

    页面不含年份，规则：默认为今年；若月份小于当前月份，视为跨年到明年。
    这样保证"12月 → 1月"跨年过渡时不会错误退回上一年。
    """
    year = today.year
    if month < today.month:
        year += 1
    return date(year, month, day)


def parse_timeline(html, today):
    """解析时间线页面，返回筛选到窗口范围内的日期分组列表。

    页面初始 HTML 一次性下发 5 个 tab 面板 `<div class="panelList" rel="X">`
    （0=全部/1=即将上线/2=即将测试/3=即将更新/4=独家），业务只关心"即将上线"，
    因此这里只解析 rel="1" 面板内的 foreCard，避免其他 Tab 的时间线数据混入。
    """
    soup = BeautifulSoup(html, "html.parser")
    window_end = date.fromordinal(today.toordinal() + WINDOW_DAYS - 1)

    upcoming_panel = soup.find("div", class_="panelList", attrs={"rel": "1"})
    if not upcoming_panel:
        logger.warning(
            '未找到"即将上线"面板容器（div.panelList[rel="1"]），页面结构可能已变化，'
            "本次不解析出任何数据"
        )
        return []

    # 同一 rel="1" 面板内不同 tab 组合（如"过去7天/今日推荐"）也会重复渲染同一日期，
    # 这里按日期去重（只取第一次出现的分组）。
    seen_dates = set()
    days = []

    for card in upcoming_panel.find_all(class_="foreCard"):
        head = card.find(class_="foreCard-hd")
        if not head:
            continue
        head_text = head.get_text(strip=True)

        # 跳过非日期分组（如"抢先爆料"）
        m = DATE_HEAD_RE.match(head_text)
        if not m:
            logger.debug("跳过非日期分组：%s", head_text)
            continue

        full_date = resolve_full_date(int(m.group(1)), int(m.group(2)), today)
        if full_date < today or full_date > window_end:
            continue

        iso_date = full_date.isoformat()
        if iso_date in seen_dates:
            continue
        seen_dates.add(iso_date)

        games = []
        for li in card.select("ul.foreList > li"):
            game = _parse_game_row(li)
            if game:
                games.append(game)

        # 同一 foreCard 内偶尔也会有重复项，按游戏名去重
        deduped = {}
        for g in games:
            deduped.setdefault(g["game_name"], g)

        days.append(
            {
                "date": iso_date,
                "date_label": head_text,
                "games": list(deduped.values()),
            }
        )

    # 按日期升序排列，保证前端渲染顺序稳定
    days.sort(key=lambda d: d["date"])
    return days


def _parse_game_row(li):
    """解析单条游戏 li 节点。"""
    con = li.find(class_="con")
    if not con:
        return None

    name_node = con.find(class_="name")
    if not name_node:
        return None
    name_em = name_node.find("em")
    game_name = name_em.get_text(strip=True) if name_em else name_node.get_text(strip=True)
    if not game_name:
        return None

    # 状态角标的实际类名带后缀（如 <span class="g-type-pc">PC/主机</span>），
    # BeautifulSoup 的 class_= 按 class token 精确匹配，写 "g-type" 匹配不到
    # "g-type-pc"，必须按前缀匹配。同级还有纯图标角标（<i class="it-ico ghot">
    # 表示热门），本身无文本，取到空串时按"无角标"处理。
    status_node = name_node.find(
        lambda tag: any(c.startswith("g-type") for c in (tag.get("class") or []))
    )
    status_tag = (status_node.get_text(strip=True) or None) if status_node else None

    categories = [
        it.get_text(strip=True)
        for it in con.select("p.tags span.it")
        if it.get_text(strip=True)
    ]

    info = con.find(class_="info")
    score = None
    event_desc = None
    if info:
        score_node = info.find(class_="score")
        if score_node:
            # 评分节点内含 <i class="it-ico star"></i> 图标，get_text 后只剩数字
            score = score_node.get_text(strip=True) or None
        # 事件描述：info 内除 .score 之外的第一个 <span>
        for span in info.find_all("span", recursive=False):
            if score_node is not None and span is score_node:
                continue
            text = span.get_text(strip=True)
            if text:
                event_desc = text
                break

    # 游戏详情页链接：li 内首个 <a href>，用于后续抓取预约人数、简介、开发者的话。
    # 站点链接常为协议相对形式（//www.3839.com/...），需补全为 https。
    detail_url = None
    link = li.find("a", href=True)
    if link:
        href = link["href"].strip()
        if href.startswith("//"):
            detail_url = "https:" + href
        elif href.startswith("http"):
            detail_url = href
        elif href.startswith("/"):
            detail_url = "https://www.3839.com" + href

    return {
        "game_name": game_name,
        "categories": categories,
        "score": score,
        "event_desc": event_desc,
        "status_tag": status_tag,
        "detail_url": detail_url,
        "publisher": None,
        "reservation_count": None,
        "has_afk_grinding_tag": False,
    }


def build_output(days):
    return {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
    }


# 详情页发行商形如 <p class="sp-info"><span>发行：</span><a class="lk">Erabit CN</a></p>
PUBLISHER_RE = re.compile(r"发行[：:]\s*(.+)$")

# 详情页预约人数形如 <p class="sp-info"><span class="score">9.2</span> 53.9万预约人数</p>，
# 并非所有游戏都有；取 "数字[万] 预约人数" 里的量级文本。
RESERVATION_RE = re.compile(r"([\d.]+\s*万?)\s*预约人数")


def enrich_with_detail(game):
    """访问游戏详情页，补全发行商、预约人数与挂机/搬砖玩法判定。

    - 发行商：详情页 p.sp-info 内"发行： xxx"（部分游戏无，保持 None）；
    - 预约人数：详情页 p.sp-info 内 "xx万预约人数"（部分游戏无，保持 None）；
    - 挂机/搬砖：依据"游戏介绍"（div.game-intro）与"开发者的话"（div.game-dev）
      两段文本 + 类型标签一起送入关键词匹配，命中则前端标注黄色五角星。
    """
    url = game.get("detail_url")
    if not url:
        return

    html = fetch_page(url)
    if not html:
        return

    soup = BeautifulSoup(html, "html.parser")

    # 详情页存在多个 p.sp-info（如"官方已入驻 发行：xxx"与"评分 xx万预约人数"），
    # 需遍历全部节点分别匹配"发行："与"预约人数"，不能只取第一个。
    for sp_info in soup.find_all(class_="sp-info"):
        text = sp_info.get_text(" ", strip=True)
        m_pub = PUBLISHER_RE.search(text)
        if m_pub and not game.get("publisher"):
            game["publisher"] = m_pub.group(1).strip()
        m_res = RESERVATION_RE.search(text)
        if m_res:
            game["reservation_count"] = m_res.group(1).replace(" ", "")

    intro_node = soup.find(class_="game-intro")
    intro_text = intro_node.get_text(" ", strip=True) if intro_node else ""
    dev_node = soup.find(class_="game-dev")
    dev_text = dev_node.get_text(" ", strip=True) if dev_node else ""

    game["has_afk_grinding_tag"] = has_afk_grinding_tag(
        intro_text, dev_text, " ".join(game.get("categories", []))
    )


def main():
    logger.info("开始抓取 好游快爆 新游时间线：%s", LIST_URL)
    html = fetch_page(LIST_URL)
    if not html:
        logger.error("时间线页面抓取失败，终止本次采集")
        return 1

    today = date.today()
    days = parse_timeline(html, today)
    total_games = sum(len(d["games"]) for d in days)
    logger.info(
        "解析完成，窗口 %s ~ %s（%d 天），共 %d 个日期分组、%d 款游戏",
        today.isoformat(),
        date.fromordinal(today.toordinal() + WINDOW_DAYS - 1).isoformat(),
        WINDOW_DAYS,
        len(days),
        total_games,
    )

    # 健全性检查：0 个日期分组通常意味着"即将上线"面板容器选择器已失效
    # （页面结构变化），而不是"近 7 天恰好真的没有任何新游"这种正常业务
    # 情况——好游快爆这类平台几乎不会出现连续 7 天空窗。直接终止写入，
    # 避免用空数据覆盖之前采集到的正常数据。
    if not days:
        logger.error("采集结果为空（0 个日期分组），疑似解析失效，终止写入以避免覆盖旧数据")
        return 1

    # 逐款游戏访问详情页补全预约人数与挂机/搬砖判定
    for day in days:
        for game in day["games"]:
            enrich_with_detail(game)

    output = build_output(days)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("写入 %s", OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
