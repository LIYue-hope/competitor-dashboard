"""热门游戏动态监测采集脚本。

按发行商（腾讯 / 网易 / 米哈游 / 其他）归类若干热门游戏，抓取各游戏官方
公告/新闻页近 7 天内的版本前瞻、更新公告与新活动信息，输出到
data/hot_games_dynamics.json 供展示层渲染。

数据源策略（详见每个游戏配置的 source 字段）：
- mihoyo：米哈游公告 JSON API（原神 hk4e、崩坏：星穹铁道 hkrpg），
  getAnnList 拿列表 + getAnnContent 拿正文，按 ann_id 关联。
- netease：网易系 SSR HTML 新闻列表页（第五人格/蛋仔派对/燕云十六声），按各站点
  DOM 结构声明选择器解析标题/日期/摘要。
- wjsj：王者荣耀世界内容中心聚合接口（腾讯 apps.game.qq.com/cmc/cross），
  按 newslist.js 还原签名算法（md5(token+source+biz+timestamp)）请求 JSON。
- pending：官方来源尚未确认稳定可抓取（部分腾讯 JS 渲染页 / 域名未确认），
  仅展示官网直达链接，不做自动摘要，等来源确认后再补采集逻辑。

所有条目统一过滤"近 7 天"窗口；对标题+摘要做挂机/搬砖玩法关键词标记。
"""
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from utils import DEFAULT_HEADERS, fetch_json, has_afk_grinding_tag

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("competitor_dashboard")

# 输出文件路径（相对仓库根目录 data/）。
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "hot_games_dynamics.json",
)

# 近 N 天窗口。用户需求为"近七天"。
WINDOW_DAYS = 7

# 摘要正文截断长度（字符）。
SUMMARY_MAX_LEN = 140

# 发行商 Tab 顺序与展示名。
PUBLISHERS = [
    {"key": "tencent", "label": "腾讯"},
    {"key": "netease", "label": "网易"},
    {"key": "mihoyo", "label": "米哈游"},
    {"key": "other", "label": "其他"},
]

# ---------------------------------------------------------------------------
# 游戏配置
# source 取值：
#   "mihoyo"  -> 使用 mihoyo 配置（list_url，content_url 自动由 list_url 推导）
#   "netease" -> 使用 netease 配置（list_url，article_re）
#   "pending" -> 仅展示官网链接，不自动采集
# ---------------------------------------------------------------------------
GAMES = [
    # ---------------- 米哈游 ----------------
    {
        "game_name": "原神",
        "publisher": "米哈游",
        "publisher_key": "mihoyo",
        "official_url": "https://ys.mihoyo.com/",
        "source": "mihoyo",
        "list_url": (
            "https://hk4e-ann-api.mihoyo.com/common/hk4e_cn/announcement/api/getAnnList"
            "?game=hk4e&game_biz=hk4e_cn&lang=zh-cn&bundle_id=hk4e_cn&channel_id=1"
            "&level=60&platform=pc&region=cn_gf01&uid=100000000"
        ),
    },
    {
        "game_name": "崩坏：星穹铁道",
        "publisher": "米哈游",
        "publisher_key": "mihoyo",
        "official_url": "https://sr.mihoyo.com/",
        "source": "mihoyo",
        "list_url": (
            "https://hkrpg-ann-api.mihoyo.com/common/hkrpg_cn/announcement/api/getAnnList"
            "?game=hkrpg&game_biz=hkrpg_cn&lang=zh-cn&bundle_id=hkrpg_cn&channel_id=1"
            "&level=70&platform=pc&region=prod_gf_cn&uid=100000000"
        ),
    },
    # ---------------- 网易 ----------------
    {
        "game_name": "第五人格",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://id5.163.com/",
        "source": "netease",
        "list_url": "https://id5.163.com/news/update/",
        # 列表项 DOM：<a class="item"><p><i>公告</i> 标题</p><span>2026-07-22</span></a>
        "dom": {
            "item": "a.item",
            "date_sel": "span",
            "date_fmt": "%Y-%m-%d",
            "title_sel": "p",
            "title_strip": "i",  # <i> 内是类型标签，取标题时剔除
            "summary_sel": None,
        },
    },
    {
        "game_name": "蛋仔派对",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://party.163.com/",
        "source": "netease",
        "list_url": "https://party.163.com/news/update/",
        # 列表项 DOM：<a class="item-inner" title="标题" href="...">
        #   <p class="p-tit">标题</p><p class="p-mess">正文</p>
        #   <div class="time-box"><p>08-13</p></div></a>
        "dom": {
            "item": "a.item-inner",
            "date_sel": ".time-box p",
            "date_fmt": "%m-%d",
            "title_attr": "title",
            "summary_sel": ".p-mess",
        },
    },
    {
        "game_name": "燕云十六声",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://www.yysls.cn/",
        "source": "netease",
        "list_url": "https://www.yysls.cn/news/",
        # 列表项 DOM：<li><div class="news-container"><a class="news" href="..." title="标题">
        #   <div class="mess"><p class="news-tit"><i class="news-label">公告</i>标题</p>
        #   <p class="news-text">摘要</p></div>
        #   <div class="date"><p class="date-day">08/15</p></div></a></div></li>
        "dom": {
            "item": "li .news-container a.news",
            "date_sel": ".date-day",
            "date_fmt": "%m/%d",
            "title_attr": "title",
            "summary_sel": ".news-text",
        },
    },
    # ---------------- 腾讯 ----------------
    # 腾讯系官网多为 JS 渲染 / GBK 编码 / 无稳定公开列表接口，
    # 现阶段先占位展示官网直达，待来源确认后再补采集逻辑。
    {
        "game_name": "三角洲行动",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://df.qq.com/",
        "source": "pending",
    },
    {
        "game_name": "和平精英",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://gp.qq.com/",
        "source": "pending",
    },
    {
        "game_name": "洛克王国世界",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://lkwg.qq.com/",
        "source": "pending",
    },
    {
        "game_name": "王者荣耀世界",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://world.qq.com/",
        "source": "wjsj",
        # 内容中心聚合频道（新闻+公告+活动等）："最新" tab 对应 chanid=7091
        "chanid": "7091",
    },
]


def _cutoff_date():
    """返回近 N 天窗口的起始日期（date），含当天。"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date() - timedelta(
        days=WINDOW_DAYS - 1
    )


def _clean_summary(html_or_text):
    """把 HTML/富文本压成单行纯文本并截断，作为卡片摘要。"""
    if not html_or_text:
        return ""
    text = BeautifulSoup(html_or_text, "html.parser").get_text(" ", strip=True)
    # 米哈游公告正文是"实体转义的 HTML"（如 &lt;t class="t_lc"&gt;...&lt;/t&gt;），
    # 首次 get_text 会把实体解码成字面标签文本，需再解析一次才能真正剥离标签。
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > SUMMARY_MAX_LEN:
        text = text[:SUMMARY_MAX_LEN].rstrip() + "…"
    return text


def _parse_netease_date(raw, fmt):
    """解析网易列表项日期。fmt='%Y-%m-%d' 为完整日期；'%m-%d' 只有月日，
    按"不晚于今天"推断年份（如 12-30 出现在 1 月，则归为去年）。
    分隔符兼容 '-' 与 '/'（如燕云十六声用 08/15）。"""
    if not raw:
        return None
    raw = raw.strip()
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    if fmt in ("%m-%d", "%m/%d"):
        m = re.search(r"(\d{1,2})[-/](\d{1,2})", raw)
        if not m:
            return None
        month, day = int(m.group(1)), int(m.group(2))
        try:
            dt = datetime(today.year, month, day).date()
        except ValueError:
            return None
        if dt > today:  # 月日晚于今天 -> 属于去年
            try:
                dt = datetime(today.year - 1, month, day).date()
            except ValueError:
                return None
        return dt
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", raw)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


def _classify_type(label, title):
    """根据公告标签/标题粗分类型：版本前瞻 / 更新公告 / 新活动 / 公告。"""
    text = f"{label or ''} {title or ''}"
    if re.search(r"前瞻|版本预告|版本前瞻|直播", text):
        return "版本前瞻"
    if re.search(r"活动|限时|福利|礼包", text):
        return "新活动"
    if re.search(r"更新|维护|版本|上线|开服", text):
        return "更新公告"
    return "公告"


# ---------------------------------------------------------------------------
# 米哈游公告 API
# ---------------------------------------------------------------------------
def fetch_mihoyo_updates(game):
    """抓取米哈游系游戏近 7 天公告，返回 update 列表。"""
    list_url = game["list_url"]
    # 正文接口：把 -ann-api 主机换成 -ann-static，getAnnList 换成 getAnnContent。
    content_url = list_url.replace("-ann-api.", "-ann-static.").replace(
        "getAnnList", "getAnnContent"
    )

    list_data = fetch_json(list_url, timeout=12).json()
    if list_data.get("retcode") != 0:
        raise RuntimeError(f"getAnnList retcode={list_data.get('retcode')}")

    # 正文映射：ann_id -> content(HTML)。正文接口偶发异常时降级为只用标题/副标题。
    content_map = {}
    try:
        content_data = fetch_json(content_url, timeout=12).json()
        for item in content_data.get("data", {}).get("list", []):
            content_map[item.get("ann_id")] = item.get("content", "")
    except (requests.RequestException, ValueError) as exc:
        logger.warning("%s 正文接口获取失败，降级用标题摘要：%s", game["game_name"], exc)

    cutoff = _cutoff_date()
    updates = []
    for group in list_data.get("data", {}).get("list", []):
        for ann in group.get("list", []):
            start_time = ann.get("start_time", "")  # 如 "2026-08-14 11:00:00"
            try:
                ann_date = datetime.strptime(start_time[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            if ann_date < cutoff:
                continue

            title = ann.get("title", "").strip()
            subtitle = ann.get("subtitle", "").strip()
            type_label = ann.get("type_label", "")
            summary = _clean_summary(content_map.get(ann.get("ann_id"), "")) or subtitle

            updates.append(
                {
                    "title": title or subtitle or "（无标题）",
                    "type": _classify_type(type_label, title),
                    "date": ann_date.isoformat(),
                    "summary": summary,
                    "url": game["official_url"],
                }
            )
    return updates


# ---------------------------------------------------------------------------
# 网易 SSR 新闻列表
# ---------------------------------------------------------------------------
def fetch_netease_updates(game):
    """抓取网易系游戏新闻列表页近 7 天条目，返回 update 列表。

    各游戏站点 DOM 结构不同，用 game["dom"] 声明选择器：
      item        列表项选择器（CSS）
      date_sel    日期文本选择器（相对 item）
      date_fmt    日期格式：'%Y-%m-%d' 完整日期 / '%m-%d' 仅月日
      title_attr  标题取自 item 的该属性（如 title）；与 title_sel 二选一
      title_sel   标题文本选择器（相对 item）
      title_strip 取标题前先移除的子元素选择器（如类型标签 <i>）
      summary_sel 摘要文本选择器（相对 item），None 表示无摘要
    """
    dom = game["dom"]
    resp = fetch_json(game["list_url"], timeout=12)
    soup = BeautifulSoup(resp.text, "html.parser")

    cutoff = _cutoff_date()
    updates = []
    seen = set()
    for item in soup.select(dom["item"]):
        # 日期
        date_node = item.select_one(dom["date_sel"]) if dom.get("date_sel") else None
        raw_date = date_node.get_text(" ", strip=True) if date_node else ""
        ann_date = _parse_netease_date(raw_date, dom.get("date_fmt", "%Y-%m-%d"))
        if not ann_date or ann_date < cutoff:
            continue

        # 标题
        if dom.get("title_attr"):
            title = (item.get(dom["title_attr"]) or "").strip()
        elif dom.get("title_sel"):
            tnode = item.select_one(dom["title_sel"])
            if tnode and dom.get("title_strip"):
                for junk in tnode.select(dom["title_strip"]):
                    junk.extract()  # 移除类型标签等，仅留标题正文
            title = tnode.get_text(" ", strip=True) if tnode else ""
        else:
            title = item.get_text(" ", strip=True)
        title = re.sub(r"\s+", " ", title).strip()

        # 链接
        href = item.get("href", "") or ""
        url = href if href.startswith("http") else ("https:" + href if href else game["official_url"])
        if url in seen:
            continue
        seen.add(url)

        # 摘要
        summary = ""
        if dom.get("summary_sel"):
            snode = item.select_one(dom["summary_sel"])
            if snode:
                summary = _clean_summary(snode.get_text(" ", strip=True))

        updates.append(
            {
                "title": title or "（无标题）",
                "type": _classify_type("", title),
                "date": ann_date.isoformat(),
                "summary": summary,
                "url": url,
            }
        )
    return updates


# ---------------------------------------------------------------------------
# 王者荣耀世界（腾讯 cmc/cross 内容中心接口）
# ---------------------------------------------------------------------------
_WJSJ_TOKEN = "497c3715198057b62870a1c53159bbd1"  # web_pc 渠道签名 token，来自 newslist.js
_WJSJ_BIZ = 387
_WJSJ_EXCLUSIVE_CHANNEL = 42


def _wjsj_sign():
    """腾讯 gicp 接口签名：md5(token + source + biz + timestamp)。"""
    ts = int(datetime.now(timezone.utc).timestamp())
    source = "web_pc"
    raw = f"{_WJSJ_TOKEN}{source}{_WJSJ_BIZ}{ts}"
    return source, ts, hashlib.md5(raw.encode()).hexdigest()


def fetch_wjsj_updates(game):
    """抓取王者荣耀世界内容中心近 7 天条目（新闻/公告/活动聚合频道）。"""
    source, ts, sign = _wjsj_sign()
    url = (
        "https://apps.game.qq.com/cmc/cross?serviceId=" + str(_WJSJ_BIZ)
        + "&source=" + source
        + "&filter=channel&sortby=sIdxTime&withtop=yes&limit=30&r0=script&r1=userobj"
        + "&chanid=" + game.get("chanid", "7091")
        + "&typeids=1,2&start=0"
        + "&exclusiveChannel=" + str(_WJSJ_EXCLUSIVE_CHANNEL)
        + "&exclusiveChannelSign=" + sign
        + "&time=" + str(ts)
    )
    headers = {"Referer": "https://world.qq.com/"}
    resp = fetch_json(url, timeout=12, headers=headers)
    text = resp.text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError("cmc/cross 返回内容不含 JSON")
    data = json.loads(text[start : end + 1])
    if data.get("status") != 0:
        raise RuntimeError(f"cmc/cross status={data.get('status')}：{data.get('msg')}")

    cutoff = _cutoff_date()
    updates = []
    for item in data.get("data", {}).get("items", []):
        created = item.get("sCreated", "")  # 如 "2026-08-12 16:21:00"
        try:
            ann_date = datetime.strptime(created[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if ann_date < cutoff:
            continue

        title = (item.get("sTitle") or "").strip()
        summary = _clean_summary(item.get("sDesc") or "")
        news_id = item.get("iId")
        detail_url = (
            f"https://world.qq.com/web202603/newsDetail.html?newsid={news_id}"
            if news_id
            else game["official_url"]
        )

        # sChannelInfo 形如 "7301|更新,7091|最新"，含 7301 归为更新频道。
        channel_info = item.get("sChannelInfo", "")
        type_label = "更新" if "7301" in channel_info else ""

        updates.append(
            {
                "title": title or "（无标题）",
                "type": _classify_type(type_label, title),
                "date": ann_date.isoformat(),
                "summary": summary,
                "url": detail_url,
            }
        )
    return updates


SOURCE_FETCHERS = {
    "mihoyo": fetch_mihoyo_updates,
    "netease": fetch_netease_updates,
    "wjsj": fetch_wjsj_updates,
}


def build_game_record(game):
    """采集单个游戏动态，返回可序列化记录。失败不抛出，降级为空动态。"""
    source = game.get("source", "pending")
    record = {
        "game_name": game["game_name"],
        "publisher": game["publisher"],
        "publisher_key": game["publisher_key"],
        "official_url": game["official_url"],
        "source_status": "ok" if source in SOURCE_FETCHERS else "pending",
        "updates": [],
        "has_afk_grinding_tag": False,
    }

    if source not in SOURCE_FETCHERS:
        return record

    try:
        updates = SOURCE_FETCHERS[source](game)
    except Exception as exc:  # noqa: BLE001 - 单游戏失败不影响整体
        logger.warning("采集失败：%s（%s）：%s", game["game_name"], source, exc)
        record["source_status"] = "error"
        return record

    # 按日期倒序（新在前）。
    updates.sort(key=lambda u: u["date"], reverse=True)
    record["updates"] = updates

    # 挂机/搬砖标记：对全部标题+摘要合并判断。
    combined = " ".join(f"{u['title']} {u['summary']}" for u in updates)
    record["has_afk_grinding_tag"] = has_afk_grinding_tag(combined)
    logger.info("%s：近%d天动态 %d 条", game["game_name"], WINDOW_DAYS, len(updates))
    return record


def build_output():
    """按发行商分组构建最终输出结构。"""
    records = [build_game_record(g) for g in GAMES]

    groups = []
    for pub in PUBLISHERS:
        games = [r for r in records if r["publisher_key"] == pub["key"]]
        groups.append({"key": pub["key"], "label": pub["label"], "games": games})

    return {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "window_days": WINDOW_DAYS,
        "publishers": groups,
    }


def main():
    output = build_output()

    # 健全性检查：防止网络异常/接口大范围失效时，用几乎全空的结果覆盖掉
    # 昨天采集到的正常数据。只要"至少一款游戏成功采集到 >=1 条动态"就
    # 认为本次采集有效；全部游戏都 pending/error/空更新才判定为异常。
    total_updates = sum(
        len(g["updates"])
        for pub in output["publishers"]
        for g in pub["games"]
    )
    if total_updates == 0:
        raise RuntimeError(
            "热门游戏动态采集结果异常：全部游戏 0 条动态，"
            "疑似接口大范围失效，终止写入以避免覆盖旧数据"
        )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(g["games"]) for g in output["publishers"])
    logger.info("已写入 %s（%d 款游戏，%d 条动态）", OUTPUT_PATH, total, total_updates)


if __name__ == "__main__":
    main()
