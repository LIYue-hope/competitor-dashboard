"""热门游戏动态监测采集脚本。

按发行商（腾讯 / 网易 / 米哈游 / 其他）归类若干热门游戏，抓取各游戏官方
公告/新闻页近 7 天内的版本前瞻、更新公告与新活动信息，输出到
data/hot_games_dynamics.json 供展示层渲染。

数据源策略（详见每个游戏配置的 source 字段）：
- mihoyo_cms：米哈游官网新闻 CMS 接口（act-api-takumi-static 的
  content_v2_user/getContentList，无签名无鉴权），抓官网「最新」父栏目
  （原神 iChanId=719、星铁 iChanId=255），覆盖资讯+公告+活动，比游戏内
  公告接口全。appSn / iChanId 为官网前端 JS 里的硬编码值，官网改版会失效，
  故请求失败时降级回 mihoyo 公告接口（game["fallback_url"]）。
- mihoyo：米哈游公告 JSON API（原神 hk4e、崩坏：星穹铁道 hkrpg），
  getAnnList 拿列表 + getAnnContent 拿正文，按 ann_id 关联。
  现仅作 mihoyo_cms 的降级退路，不再直接配给游戏。
- netease：网易系 SSR HTML 新闻列表页（第五人格/蛋仔派对/燕云十六声），按各站点
  DOM 结构声明选择器解析标题/日期/摘要。
- wjsj：王者荣耀世界内容中心聚合接口（腾讯 apps.game.qq.com/cmc/cross），
  按 newslist.js 还原签名算法（md5(token+source+biz+timestamp)）请求 JSON。
- df / gp / rocom：三角洲行动 / 和平精英 / 洛克王国世界，同为腾讯内容中心
  cmc/cross 接口，但无需签名（source=web_pc 即可）。df、gp 按 chanid 过滤频道，
  rocom 按 tagids 过滤标签；返回体可能带 `var userobj=` 前缀，统一用
  _load_cmc_json 截取解析，类型判定各自按频道 id / 标签名映射。
- pending：官方来源尚未确认稳定可抓取时的占位状态，仅展示官网直达链接，
  不做自动摘要（当前无游戏使用）。

所有条目统一过滤"近 7 天"窗口；对标题+摘要做挂机/搬砖玩法关键词标记。
"""
import hashlib
import json
import logging
import os
import re
import time
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

# 详情正文喂给 BeautifulSoup 前的粗截断长度（字符）。腾讯 gicp 单条正文实测
# 可达数百 KB（洛克王国世界内嵌大段中奖名单表格），全量解析很慢；这里远大于
# SUMMARY_MAX_LEN，足够截出摘要。
CONTENT_PARSE_MAX_LEN = 4000

# 正文只有长图、没有任何文字时的摘要占位文案。
IMAGE_ONLY_SUMMARY = "（本条为图片公告，正文无文字内容，点击查看原文）"


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
#   "mihoyo_cms" -> 米哈游官网新闻 CMS getContentList（list_url），
#                   失败时自动降级到 fallback_url 指向的公告接口
#   "mihoyo"  -> 使用 mihoyo 配置（list_url，content_url 自动由 list_url 推导）
#   "netease" -> 使用 netease 配置（list_url，dom 选择器）
#   "wjsj"    -> 王者荣耀世界 cmc/cross（需签名，chanid）
#   "df"      -> 三角洲行动 cmc/cross（serviceId + chanid）
#   "gp"      -> 和平精英 cmc/cross（serviceId + chanid）
#   "rocom"   -> 洛克王国世界 cmc/cross（serviceId + tagids）
#   "pending" -> 仅展示官网链接，不自动采集
# ---------------------------------------------------------------------------
GAMES = [
    # ---------------- 米哈游 ----------------
    {
        "game_name": "原神",
        "publisher": "米哈游",
        "publisher_key": "mihoyo",
        "official_url": "https://ys.mihoyo.com/",
        "source": "mihoyo_cms",
        # 官网「最新」父栏目 iChanId=719（子栏目 720 新闻 / 721 公告 /
        # 722 活动，722 已废弃，最新条目停在 2022 年）。iAppId=43 必传。
        # iPageSize 用 50：实测 30 条只能回溯到 cutoff 前 2 天，版本上线周
        # 日更 5~8 条时有截断风险（接口至少支持 100）。
        "list_url": (
            "https://act-api-takumi-static.mihoyo.com/content_v2_user/app/"
            "16471662a82d418a/getContentList?iAppId=43&iChanId=719"
            "&iPageSize=50&iPage=1&sLangKey=zh-cn"
        ),
        "detail_url_prefix": "https://ys.mihoyo.com/main/news/detail/",
        # sCategoryName 恒为空串，类型只能靠 sChanId 反查；条目常同时挂
        # 720+721，故把更具体的 721 公告排在 720 新闻前面。
        "chan_types": {"721": "公告", "720": "新闻", "722": "活动"},
        # CMS 接口失效时的降级退路：游戏内公告接口（原 source="mihoyo"）。
        "fallback_url": (
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
        "source": "mihoyo_cms",
        # 官网「最新」聚合父栏目 iChanId=255（含 256 资讯 / 257 公告 /
        # 258 活动）。该站不能带 iAppId。sCategoryName 有值，无需 chan_types。
        # iPageSize=30 实测可回溯 40+ 天，足够覆盖 7 天窗口。
        "list_url": (
            "https://act-api-takumi-static.mihoyo.com/content_v2_user/app/"
            "1963de8dc19e461c/getContentList?iPage=1&iPageSize=30"
            "&sLangKey=zh-cn&isPreview=0&iChanId=255"
        ),
        "detail_url_prefix": "https://sr.mihoyo.com/news/",
        "fallback_url": (
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
        "list_url": "https://id5.163.com/news/official/",
        # 列表项 DOM：<a class="item"><p><i>新闻</i> 标题</p><span>2026-08-13</span></a>
        # （/news/update/ 只有违规名单类公告且更新极慢，改用 /news/official/）
        "dom": {
            "item": "a.item",
            "date_sel": "span",
            "date_fmt": "%Y-%m-%d",
            "title_sel": "p",
            "title_strip": "i",  # <i> 内是类型标签，取标题时剔除
            "label_sel": "p i",  # 类型标签（新闻/公告），用于类型判定
            "summary_sel": None,
            # 列表页确实没有摘要元素，回退请求详情页取正文（服务端渲染，utf-8）。
            "detail_summary_sel": ".cont-box .artText",
        },
    },
    {
        "game_name": "蛋仔派对",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://party.163.com/",
        "source": "netease",
        "list_url": "https://party.163.com/news/",
        # /news/ 聚合了 update（公告）+ official（新闻/活动），覆盖面比 /news/update/ 广。
        # 列表项 DOM：<a class="item-inner" title="标题" href="...">

        #   <p class="p-tit">标题</p><p class="p-mess">正文</p>
        #   <div class="time-box"><p>08-13</p></div></a>
        "dom": {
            "item": "a.item-inner",
            "date_sel": ".time-box p",
            "date_fmt": "%m-%d",
            "title_attr": "title",
            "label_sel": None,  # 该站列表项无类型标签元素
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
            "label_sel": ".news-label",  # 类型标签（公告/新闻等），用于类型判定
            "summary_sel": ".news-text",
        },
    },
    # ---------------- 腾讯 ----------------
    # 腾讯系官网页面多为 JS 渲染，但内容都来自 apps.game.qq.com/cmc/cross
    # 内容中心接口，直接请求 JSON（王者荣耀世界需签名，其余三款不需要）。
    {
        "game_name": "三角洲行动",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://df.qq.com/",
        "source": "df",
        # list_url 仅作来源标注/人工核对用，实际抓取走 cmc/cross。
        "list_url": "https://df.qq.com/cp/a20240906main/newslist.html",
        "serviceId": "423",
        # 频道：6895 最新（聚合）、6896 公告、6898 新闻、7037 赛事、6914 头条新闻
        "chanid": "6895",
    },
    {
        "game_name": "和平精英",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://gp.qq.com/",
        "source": "gp",
        "list_url": "https://gp.qq.com/gicp/news/1135/0/3996/1.html",
        # serviceId 是 182（页面 URL 里的 1135 是模板 ID，用它会返回 status=-97）
        "serviceId": "182",
        "chanid": "3996",  # 资讯专区（聚合公告/新闻/活动）
    },
    {
        "game_name": "洛克王国世界",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://rocom.qq.com/",
        "source": "rocom",
        "list_url": "https://rocom.qq.com/web202507/sub/index.html",
        "serviceId": "467",
        # 该站按 tag 而非 channel 组织：135110 最新、135111 公告、135112 资讯、135113 活动
        "tagids": "135110,135111,135112,135113",
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


def _clean_summary(html_or_text, is_html=True):
    """把 HTML/富文本压成单行纯文本并截断，作为卡片摘要。

    is_html=False 用于调用方已经 get_text 过的纯文本：此时绝不能再当 HTML 解析，
    否则正文里字面出现的尖括号内容（如蛋仔派对摘要中的 <少盟主-沈昭>）会被
    当成未知标签整段吞掉。
    """
    if not html_or_text:
        return ""
    raw = html_or_text if isinstance(html_or_text, str) else str(html_or_text)
    if is_html:
        text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
        # 米哈游公告正文是"实体转义的 HTML"（如 &lt;t class="t_lc"&gt;...&lt;/t&gt;），
        # 首次 get_text 会把实体解码成字面标签文本，需再解析一次才能真正剥离标签。
        # 判定看**输入**里有没有 &lt;/&gt; 实体，避免误伤正文里的字面尖括号。
        if "&lt;" in raw and "&gt;" in raw:
            text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    else:
        text = raw
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
    """根据公告标签/标题粗分类型：版本前瞻 / 更新公告 / 新活动 / 新闻 / 公告。

    label 是数据源自带的类型标注（如网易列表页 <i> 里的「新闻」/「公告」），
    比标题猜测更可信：标为「新闻」的条目即使标题里有"上线/版本"也不该被
    判成更新公告，故 新闻/资讯 标签优先于标题关键词。
    """
    label = label or ""
    text = f"{label} {title or ''}"
    if re.search(r"前瞻|版本预告|版本前瞻|直播", text):
        return "版本前瞻"
    if re.search(r"活动|限时|福利|礼包", text):
        return "新活动"
    if re.search(r"新闻|资讯", label):
        return "新闻"
    if re.search(r"更新|维护|版本|上线|开服", text):
        return "更新公告"
    return "公告"


# ---------------------------------------------------------------------------
# 米哈游公告 API
# ---------------------------------------------------------------------------
def fetch_mihoyo_updates(game):
    """抓取米哈游系游戏近 7 天公告，返回 update 列表。

    现作为 fetch_mihoyo_cms_updates 的降级退路调用（list_url 由调用方替换成
    game["fallback_url"]），也可直接配 source="mihoyo" 使用。
    """

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
                    # 公告接口是游戏客户端公告栏数据源，条目只有 ann_id，
                    # 没有对应的官网详情页 URL，只能退回官网首页。
                    "url": game["official_url"],
                }
            )
    return updates


# ---------------------------------------------------------------------------
# 米哈游官网新闻 CMS API（content_v2_user/getContentList）
# ---------------------------------------------------------------------------
def _mihoyo_cms_ext(item):
    """解析条目的 sExt（JSON 字符串，含 news-date / news-self-path 等），
    解析失败或结构异常时返回空 dict。"""
    try:
        ext = json.loads(item.get("sExt") or "{}")
    except (TypeError, ValueError):
        return {}
    return ext if isinstance(ext, dict) else {}


def _mihoyo_cms_date(item, ext):
    """取条目发布日期（date）。

    官网优先展示 sExt["news-date"]（人工填写，星铁近期条目为空串/空格），
    取不到再回落 dtStartTime。不用 dtCreateTime —— 它可能比生效日期早一天
    （实测 iInfoId=165722 创建 08-13 / 生效 08-14）。
    """
    for raw in (str(ext.get("news-date") or ""), item.get("dtStartTime") or ""):
        m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", raw)
        if not m:
            continue
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            continue
    return None


def _mihoyo_cms_label(game, item):
    """取条目栏目名，作为 _classify_type 的 label。

    星铁 sCategoryName 直接有值（公告/新闻/活动）；原神该字段恒为空串，
    只能用 game["chan_types"] 按 sChanId 里的栏目 id 反查。
    """
    label = (item.get("sCategoryName") or "").strip()
    if label:
        return label
    chan_ids = {str(c) for c in (item.get("sChanId") or [])}
    for chan_id, chan_label in (game.get("chan_types") or {}).items():
        if chan_id in chan_ids:
            return chan_label
    return ""


def _mihoyo_cms_detail_url(game, item, ext):
    """拼条目详情链接。

    星铁形如 https://sr.mihoyo.com/news/{news-self-path 或 iInfoId}，
    原神形如 https://ys.mihoyo.com/main/news/detail/{iInfoId}（其 sExt
    无 news-self-path 字段，自然落到 iInfoId 分支）。
    """
    slug = str(ext.get("news-self-path") or "").strip() or str(item.get("iInfoId") or "")
    return game["detail_url_prefix"] + slug if slug else game["official_url"]


def fetch_mihoyo_cms_updates(game):
    """抓取米哈游官网新闻 CMS 近 7 天条目（资讯+公告+活动聚合栏目）。

    接口无签名、无鉴权、不需要自定义 header。appSn / iChanId 是从官网前端
    JS 里挖的硬编码值，官网改版即失效，故请求异常 / retcode!=0 / 列表为空时
    降级回 fetch_mihoyo_updates（game["fallback_url"] 指向的公告接口）。
    """
    try:
        data = fetch_json(game["list_url"], timeout=12).json()
        if data.get("retcode") != 0:
            raise RuntimeError(f"getContentList retcode={data.get('retcode')}")
        payload = data.get("data") or {}
        items = payload.get("list") or []
        if not items:
            raise RuntimeError("getContentList 返回空列表")
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        logger.warning(
            "%s：官网 CMS 接口不可用，已降级到公告接口：%s", game["game_name"], exc
        )
        return fetch_mihoyo_updates(dict(game, list_url=game["fallback_url"]))

    logger.info(
        "%s：接口返回 %d 条（total=%s）",
        game["game_name"], len(items), payload.get("iTotal"),
    )

    cutoff = _cutoff_date()
    updates = []
    for item in items:
        ext = _mihoyo_cms_ext(item)
        # 返回顺序不是纯日期倒序（置顶稿排最前，如星铁 iInfoId=112426 /
        # 2023-07-26），只能逐条按日期过滤，不能靠遇到旧条目就 break。
        ann_date = _mihoyo_cms_date(item, ext)
        if not ann_date or ann_date < cutoff:
            continue

        title = (item.get("sTitle") or "").strip()
        updates.append(
            {
                "title": title or "（无标题）",
                "type": _classify_type(_mihoyo_cms_label(game, item), title),
                "date": ann_date.isoformat(),
                # sIntro 是列表接口自带的摘要，无需再请求详情接口。但部分游戏
                # （如原神）所有条目的 sIntro 都是空串，此时回退到 sContent
                # （正文 HTML），_clean_summary 会去标签并截断到 SUMMARY_MAX_LEN。
                "summary": (
                    _clean_summary(item.get("sIntro") or "")
                    or _clean_summary(item.get("sContent") or "")
                ),
                "url": _mihoyo_cms_detail_url(game, item, ext),
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
      label_sel   类型标签文本选择器（相对 item），None/取不到时退回空串
      summary_sel 摘要文本选择器（相对 item），None 表示无摘要
      detail_summary_sel  列表页无摘要时，回退请求详情页用该选择器取正文（相对详情页文档）
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

        # 类型标签（列表页 <i> 里的「新闻」/「公告」等）。必须在取标题之前读，
        # 因为 title_strip 会把标签节点从 DOM 里摘掉；取不到则退回空串。
        label = ""
        if dom.get("label_sel"):
            lnode = item.select_one(dom["label_sel"])
            if lnode:
                label = lnode.get_text(" ", strip=True)

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
                summary = _clean_summary(snode.get_text(" ", strip=True), is_html=False)
        # 列表页无摘要元素（如第五人格）时，回退请求详情页取正文首段。
        # 只对配了 detail_summary_sel 的游戏生效；单条失败不影响其它条目。
        if not summary and dom.get("detail_summary_sel") and url.startswith("http"):
            try:
                dresp = fetch_json(url, timeout=10)
                dresp.encoding = dresp.apparent_encoding or "utf-8"
                dnode = BeautifulSoup(dresp.text, "html.parser").select_one(
                    dom["detail_summary_sel"]
                )
                if dnode:
                    summary = _clean_summary(dnode.get_text(" ", strip=True), is_html=False)
            except Exception as exc:  # 网络/解析异常都降级为空摘要
                logger.warning("%s 详情页摘要获取失败：%s（%s）", game["game_name"], url, exc)


        updates.append(
            {
                "title": title or "（无标题）",
                "type": _classify_type(label, title),
                "date": ann_date.isoformat(),
                "summary": summary,
                "url": url,
            }
        )
    return updates


# ---------------------------------------------------------------------------
# 腾讯内容中心（apps.game.qq.com/cmc/cross）公共解析
# ---------------------------------------------------------------------------
def _load_cmc_json(text):
    """解析 cmc/cross 返回体为 dict。

    返回体形态不稳定：传 r0/r1 时是 `var userobj={...};`，不传时是纯 JSON，
    同一接口还可能因请求头/CDN 而变化，统一按首尾花括号截取后解析。
    """
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError("cmc/cross 返回内容不含 JSON")
    return json.loads(text[start : end + 1])


def _cmc_date(item):
    """取条目的北京时间日期。用 sIdxTime（列表排序时间），
    不用 sCreated —— 重发/置顶稿的 sCreated 可能是一年前。"""
    idx_time = item.get("sIdxTime") or ""
    try:
        return datetime.strptime(idx_time[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _fetch_gicp_summary(service_id, news_id):
    """按 iNewsId 拉腾讯 gicp 图文正文，截成卡片摘要。失败返回空串。

    df / gp / rocom 的 cmc/cross 列表项没有可用摘要（sDesc 恒为空或等于
    sTitle），只能逐条请求正文接口。接口无签名、无需登录、无需 Referer，
    id 必须传 iNewsId（传 iDocID 会返回"没有查询到相关数据"），返回体是
    JSONP 形态 `var searchObj={...};`，用 _load_cmc_json 解析。
    单条摘要拿不到不应影响整个游戏的抓取，故所有异常都吞掉只记日志。
    """
    if not news_id:
        return ""
    url = (
        "https://apps.game.qq.com/wmp/v3.1/public/searchNews.php?p0="
        + str(service_id)
        + "&source=web_pc&id=" + str(news_id)
    )
    try:
        data = _load_cmc_json(fetch_json(url, timeout=10).text)
        if data.get("status") != 0:
            logger.debug(
                "searchNews status=%s（p0=%s id=%s）", data.get("status"), service_id, news_id
            )
            return ""
        # 正文在**顶层** msg 里；data 字段实测是字符串（不是对象），别从里面取。
        msg = data.get("msg")
        content = (msg.get("sContent") or "") if isinstance(msg, dict) else ""
        # 正文可能极长（洛克王国世界单条实测 690KB），先粗截断再交给解析器。
        summary = _clean_summary(content[:CONTENT_PARSE_MAX_LEN])
        # 部分公告正文只有一张长图（如三角洲 iNewsId=18837554/18834460，sContent
        # 仅 <img> + &nbsp;），源站本身没有文字。给个占位说明，避免卡片摘要空白。
        if not summary and "<img" in content.lower():
            return IMAGE_ONLY_SUMMARY
        return summary
    except Exception as exc:  # 网络/解析/结构异常都只降级为空摘要
        logger.warning("gicp 正文获取失败（p0=%s id=%s）：%s", service_id, news_id, exc)
        return ""


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
    data = _load_cmc_json(resp.text)
    if data.get("status") != 0:
        raise RuntimeError(f"cmc/cross status={data.get('status')}：{data.get('msg')}")


    cutoff = _cutoff_date()
    updates = []
    for item in data.get("data", {}).get("items", []):
        ann_date = _cmc_date(item)
        if not ann_date or ann_date < cutoff:
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


# ---------------------------------------------------------------------------
# 三角洲行动（腾讯 cmc/cross，无签名，按 chanid 过滤频道）
# ---------------------------------------------------------------------------
def _df_classify(item):
    """三角洲行动类型判定：先看安全公告标签，再按频道 id 细分。

    频道：6895 最新、6896 公告、6898 新闻、7037 赛事、6914 头条新闻
    """
    tag_names = " ".join(
        t.get("name") or "" for t in (item.get("sTagInfoList") or [])
    )
    channels = item.get("sChannel") or []
    title = item.get("sTitle") or ""

    if "安全公告" in tag_names:
        return "安全公告"
    if 7037 in channels:
        return "赛事"
    if 6896 in channels:
        if "更新公告" in title:
            return "更新公告"
        if re.search(r"赛季|前瞻|版本", title):
            return "版本前瞻"
        if re.search(r"活动|开启|上线|限时", title):
            return "新活动"
        return "公告"
    if 6898 in channels:
        return "新闻"
    return "其他"


def fetch_df_updates(game):
    """抓取三角洲行动内容中心「最新」聚合频道近 7 天条目。"""
    url = (
        "https://apps.game.qq.com/cmc/cross?serviceId=" + game["serviceId"]
        + "&source=web_pc&filter=channel&sortby=sIdxTime&withtop=no"
        # limit 服务端硬上限 50；withtop=yes 会把很老的置顶稿顶到首位，故用 no
        + "&limit=50&start=0&r0=script&r1=userobj"
        + "&chanid=" + game["chanid"]
        + "&typeids=1"
    )
    resp = fetch_json(url, timeout=12)
    data = _load_cmc_json(resp.text)
    # 正常返回 status=0；被拒绝时（如缺 source / 非法 serviceId）status=-97
    # 且 data 字段退化为字符串，必须先判 status 再取 items。
    if data.get("status") != 0:
        raise RuntimeError(f"cmc/cross status={data.get('status')}：{data.get('msg')}")
    payload = data.get("data")
    payload = payload if isinstance(payload, dict) else {}
    items = payload.get("items") or []
    logger.info(
        "%s：接口返回 %d 条（total=%s）",
        game["game_name"], len(items), payload.get("total"),
    )

    cutoff = _cutoff_date()
    updates = []
    for item in items:
        ann_date = _cmc_date(item)
        if not ann_date or ann_date < cutoff:
            continue

        title = (item.get("sTitle") or "").strip()
        doc_id = item.get("iDocID")
        detail_url = (
            f"https://df.qq.com/cp/a20240906main/newsdetail.html?id={doc_id}"
            if doc_id
            else game["official_url"]
        )
        # 详情页链接用 iDocID，但正文接口只认 iNewsId（等价于 iId）。
        news_id = item.get("iNewsId") or item.get("iId")

        updates.append(
            {
                "title": title or "（无标题）",
                "type": _df_classify(item),
                "date": ann_date.isoformat(),
                # sDesc 实测恒为空字符串，摘要改走 gicp 图文正文接口。
                "summary": _fetch_gicp_summary(game["serviceId"], news_id),
                "url": detail_url,
            }
        )
    return updates


# ---------------------------------------------------------------------------
# 和平精英（腾讯 cmc/cross，无签名但 source=web_pc 必需）
# ---------------------------------------------------------------------------
# 频道 id -> 类型。按此顺序取第一个命中（越具体的频道优先，
# 如 6948 版本前瞻 优先于 4001 公告）。
_GP_CHANNEL_TYPES = [
    ("6967", "安全公告"),
    ("6968", "安全公告"),
    ("6969", "安全公告"),
    ("6948", "版本前瞻"),
    ("4467", "赛事"),
    ("4003", "新活动"),
    ("4001", "公告"),
    ("4000", "新闻"),
]


def _gp_classify(item):
    """和平精英类型判定：解析 sChannelInfoJson 里的频道 id 映射。"""
    channel_ids = {
        str(c.get("sChannelId"))
        for c in (item.get("sChannelInfoJson") or [])
        if isinstance(c, dict)
    }
    for chan_id, type_name in _GP_CHANNEL_TYPES:
        if chan_id in channel_ids:
            return type_name
    if "更新公告" in (item.get("sTitle") or ""):
        return "更新公告"
    return "资讯"


def fetch_gp_updates(game):
    """抓取和平精英资讯专区近 7 天条目。"""
    url = (
        # serviceId 必须是 182；缺 source=web_pc 会返回 status=-97 非法请求来源。
        "https://apps.game.qq.com/cmc/cross?serviceId=" + game["serviceId"]
        + "&source=web_pc&filter=channel&sortby=sIdxTime&withtop=no"
        + "&limit=30&start=0"
        + "&chanid=" + game["chanid"]
        + "&typeids=1,2"
    )
    resp = fetch_json(url, timeout=12)
    data = _load_cmc_json(resp.text)
    if data.get("status") != 0:
        raise RuntimeError(f"cmc/cross status={data.get('status')}：{data.get('msg')}")
    items = data.get("data", {}).get("items") or []
    logger.info(
        "%s：接口返回 %d 条（total=%s）",
        game["game_name"], len(items), data.get("data", {}).get("total"),
    )

    cutoff = _cutoff_date()
    updates = []
    for item in items:
        ann_date = _cmc_date(item)
        if not ann_date or ann_date < cutoff:
            continue

        title = (item.get("sTitle") or "").strip()
        redirect_url = (item.get("sRedirectURL") or "").strip()
        news_id = item.get("iNewsId") or item.get("iId")
        if redirect_url:
            detail_url = redirect_url
        elif news_id:
            detail_url = f"https://gp.qq.com/gicp/news/1134/{news_id}.html"
        else:
            detail_url = game["official_url"]

        # sDesc 实测等于 sTitle，不是真摘要，改走 gicp 图文正文接口。
        summary = _fetch_gicp_summary(game["serviceId"], news_id)

        updates.append(
            {
                "title": title or "（无标题）",
                "type": _gp_classify(item),
                "date": ann_date.isoformat(),
                "summary": summary,
                "url": detail_url,
            }
        )
    return updates


# ---------------------------------------------------------------------------
# 洛克王国世界（腾讯 cmc/cross，无签名，按 tagids 过滤标签）
# ---------------------------------------------------------------------------
def _rocom_classify(item):
    """洛克王国世界类型判定：按 sTagInfoList 的标签名映射。

    标签：135110 最新、135111 公告、135112 资讯、135113 活动、
          136358 置顶资讯、136359 图片轮播
    """
    tag_names = {t.get("name") for t in (item.get("sTagInfoList") or [])}
    title = item.get("sTitle") or ""

    if "官网-活动" in tag_names:
        return "新活动"
    if "官网-公告" in tag_names:
        if "版本更新公告" in title:
            return "更新公告"
        if "处罚公告" in title:
            return "处罚公告"
        return "公告"
    if tag_names & {"官网-资讯", "官网-置顶资讯"}:
        return "资讯"
    return "资讯"


def fetch_rocom_updates(game):
    """抓取洛克王国世界官网（最新/公告/资讯/活动标签）近 7 天条目。"""
    url = (
        "https://apps.game.qq.com/cmc/cross?serviceId=" + game["serviceId"]
        + "&filter=tag&tagids=" + game["tagids"]
        + "&typeids=1,2&source=web_pc&logic=or&sortby=sIdxTime"
        + "&limit=30&start=0&r0=script&r1=userobj"
    )
    resp = fetch_json(url, timeout=12)
    data = _load_cmc_json(resp.text)
    if data.get("status") != 0:
        raise RuntimeError(f"cmc/cross status={data.get('status')}：{data.get('msg')}")
    # start 越界时 items 为 null，必须判空。
    items = data.get("data", {}).get("items") or []
    logger.info(
        "%s：接口返回 %d 条（total=%s）",
        game["game_name"], len(items), data.get("data", {}).get("total"),
    )

    cutoff = _cutoff_date()
    updates = []
    for item in items:
        ann_date = _cmc_date(item)
        if not ann_date or ann_date < cutoff:
            continue

        title = (item.get("sTitle") or "").strip()
        redirect_url = (item.get("sRedirectURL") or "").strip()
        news_id = item.get("iNewsId")
        if str(item.get("iIsRedirect")) == "1" and redirect_url:
            detail_url = redirect_url
        elif news_id:
            detail_url = (
                f"https://rocom.qq.com/web202507/sub/detail.html?newsid={news_id}"
            )
        else:
            detail_url = game["official_url"]

        updates.append(
            {
                "title": title or "（无标题）",
                "type": _rocom_classify(item),
                "date": ann_date.isoformat(),
                # sDesc 恒为空，摘要改走 gicp 图文正文接口。
                "summary": _fetch_gicp_summary(game["serviceId"], news_id),
                "url": detail_url,
            }
        )
    return updates


SOURCE_FETCHERS = {

    "mihoyo_cms": fetch_mihoyo_cms_updates,
    "mihoyo": fetch_mihoyo_updates,
    "netease": fetch_netease_updates,
    "wjsj": fetch_wjsj_updates,
    "df": fetch_df_updates,
    "gp": fetch_gp_updates,
    "rocom": fetch_rocom_updates,
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


def count_updates(output):
    return sum(
        len(g["updates"])
        for pub in output["publishers"]
        for g in pub["games"]
    )


def main():
    # 健全性检查：防止网络异常/接口大范围失效时，用几乎全空的结果覆盖掉
    # 昨天采集到的正常数据。只要"至少一款游戏成功采集到 >=1 条动态"就
    # 认为本次采集有效；全部游戏都 pending/error/空更新才判定为异常。
    #
    # 全空时整体重试：单个源的失败已经在 build_game_record 里降级为
    # source_status="error"，走到这里说明所有源同时失效，多半是 CI 出口 IP
    # 被限流这类瞬时问题。前端「数据更新」按钮会按需触发采集，命中频率远高于
    # 每天一次的定时任务，因此这里再补一层整体重试。
    attempts = 3
    for attempt in range(1, attempts + 1):
        output = build_output()
        total_updates = count_updates(output)
        if total_updates > 0:
            break
        logger.warning("第 %d/%d 次采集到 0 条动态", attempt, attempts)
        if attempt < attempts:
            logger.info("等待 10 秒后重试")
            time.sleep(10)

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
