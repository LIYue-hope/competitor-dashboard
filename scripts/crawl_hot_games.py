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
- netease：网易系 SSR HTML 新闻列表页（第五人格/蛋仔派对/燕云十六声/阴阳师/
  永劫无间/我的世界/光遇/遗忘之海/梦幻西游手游/巅峰极速），按各站点 DOM 结构
  声明选择器解析标题/日期/摘要；响应头普遍不带 charset，故各站显式配
  encoding（梦幻西游是唯一的 gb18030 站），日期/标题可从属性取（date_attr /
  title_attr），一个游戏可配多个栏目页（list_urls）。
- nsh：逆水寒官网新闻列表（n.163.com）。DOM 与 netease 系同构，但日期被拆成
  「日」与「两位年.月」两个节点，get_text 拼接会得到错年份，故独立成一个 source。
- wjsj：王者荣耀世界内容中心聚合接口（腾讯 apps.game.qq.com/cmc/cross），
  按 newslist.js 还原签名算法（md5(token+source+biz+timestamp)）请求 JSON。
- df / gp / rocom：三角洲行动 / 和平精英 / 洛克王国世界，同为腾讯内容中心
  cmc/cross 接口，但无需签名（source=web_pc 即可）。df、gp 按 chanid 过滤频道，
  rocom 按 tagids 过滤标签；返回体可能带 `var userobj=` 前缀，统一用
  _load_cmc_json 截取解析，类型判定各自按频道 id / 标签名映射。
- cmc：配置驱动的腾讯内容中心通用采集（王者荣耀 / 金铲铲之战 / 暗区突围 /
  穿越火线-枪战王者）。同一个 cmc/cross 接口，差异（serviceId、query 串、
  频道或标签、排除规则、详情页模板、类型映射）全部收进游戏配置的 cmc 字段。
- codm：使命召唤手游。cmc/cross 对 codm 返回 status=-97 非法请求来源，改解析
  gicp 服务端渲染列表页（GBK 编码），页面无分类字段，类型只能按标题兜底。
- hyrz：火影忍者。用老 wmp 接口（不是 cmc/cross），列表在 msg.result，只收
  公告 + 新闻两类。
- hypergryph：鹰角官网新闻接口（明日方舟 ak.hypergryph.com/api/news、终末地
  web-news.hypergryph.com/api/bulletin），字段完全一致，差异（域名/分页上限/
  tab 取值）收在游戏配置里。displayTime 是 unix 秒 UTC，需转北京时间。
- papegames：叠纸系官网新闻接口（无限暖暖 / 闪耀暖暖 / 恋与制作人），同一套
  后端，publish_time 是 ISO-8601 UTC，必须转北京时间。
- kuro：库洛静态 JSON CMS（鸣潮 / 战双帕弥什 ArticleMenu.json），返回体是
  数组，startTime 已是北京时间。
- wanmei：完美世界异环官网新闻列表（SSR HTML，第 N 页为 index{N-1}.html），
  响应无 charset 声明，必须显式 utf-8 解码；严格倒序，遇窗口外条目即停翻页。
- preternatural：超自然行动组（巨人网络）官网列表接口 sphinx.preternatural.cc，
  按 category 分类各请求一次；部分老条目 publishAt 被写成请求时刻附近的时间戳，
  必须取 min(publishAt, updateAt) 作为发布时间。
- biligame：B 站发行游戏新闻接口 api.biligame.com/news/list.action（命运-冠位
  指定 / 三国：谋定天下），以 gameExtensionId 为键，positionId=2 必填，日期取
  createTime（modifyTime 会把旧公告顶到今天）；列表头部有置顶条目。
- silverpalace：白银之城（乐元素）官网列表接口 news_list，size 被服务端压到
  10/页需按 total_page 翻页；列表是 id 倒序不是日期倒序，必须逐条比窗口。
- pending：官方来源尚未确认稳定可抓取时的占位状态，仅展示官网直达链接，
  不做自动摘要（当前无游戏使用）。

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
    {"key": "hg_kuro_pape", "label": "鹰角、库洛、叠纸"},
    {"key": "other", "label": "其他"},
]

# ---------------------------------------------------------------------------
# 游戏配置
# source 取值：
#   "mihoyo_cms" -> 米哈游官网新闻 CMS getContentList（list_url），
#                   失败时自动降级到 fallback_url 指向的公告接口
#   "mihoyo"  -> 使用 mihoyo 配置（list_url，content_url 自动由 list_url 推导）
#   "netease" -> 使用 netease 配置（list_url 或 list_urls，dom 选择器，
#                可选 encoding 显式指定响应编码）
#   "nsh"     -> 逆水寒官网新闻列表（list_url + dom，日期拆成两节点单独解析）
#   "wjsj"    -> 王者荣耀世界 cmc/cross（需签名，chanid）
#   "df"      -> 三角洲行动 cmc/cross（serviceId + chanid）
#   "gp"      -> 和平精英 cmc/cross（serviceId + chanid）
#   "rocom"   -> 洛克王国世界 cmc/cross（serviceId + tagids）
#   "cmc"     -> 腾讯内容中心通用采集（serviceId + cmc 配置字段）
#   "codm"    -> 使命召唤手游 gicp SSR 列表页（list_url）
#   "hyrz"    -> 火影忍者 wmp 接口（无需额外配置）
#   "hypergryph" -> 鹰角官网新闻接口（list_url + tab_types + max_pages）
#   "papegames"  -> 叠纸系官网新闻接口（list_url + 可选 section_types）
#   "kuro"       -> 库洛静态 JSON CMS（list_url + article_types）
#   "wanmei"     -> 异环官网新闻列表 SSR（list_url + page_url + max_pages）
#   "preternatural" -> 超自然行动组官网列表接口（list_url + category_types）
#   "biligame"   -> B 站发行游戏新闻接口（list_url + type_names + detail_url_tpl）
#   "silverpalace"  -> 白银之城官网列表接口（list_url + category_types + max_pages）
#   "pending" -> 仅展示官网链接，不自动采集
#
# 可选字段 company：该发行商 tab 下多家公司混排时（鹰角/库洛/叠纸），前端在
# 游戏名后以括号展示公司名；game_name 保持干净（它同时是前端卡片的 key）。
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
    {
        "game_name": "绝区零",
        "publisher": "米哈游",
        "publisher_key": "mihoyo",
        "official_url": "https://zzz.mihoyo.com/",
        "source": "mihoyo_cms",
        # 官网「最新」父栏目 iChanId=273（子栏目 278 新闻 / 279 公告 / 280 活动，
        # 280 已废弃，最新条目停在 2024-12-18）。278+279+280=1552=273 的 iTotal，
        # 说明 273 是三者无重复并集，抓一次即可。该站不能/不需带 iAppId。
        "list_url": (
            "https://api-takumi-static.mihoyo.com/content_v2_user/app/"
            "706fd13a87294881/getContentList?iPage=1&iPageSize=50"
            "&iChanId=273&sLangKey=zh-cn"
        ),
        "detail_url_prefix": "https://zzz.mihoyo.com/news/",
        # sCategoryName 恒为空串，类型只能靠 sChanId 反查；sExt 里没有
        # news-date，日期走 _mihoyo_cms_date 对 dtStartTime 的回落分支。
        "chan_types": {"279": "公告", "278": "新闻", "280": "活动"},
        "fallback_url": (
            "https://announcement-api.mihoyo.com/common/nap_cn/announcement/api/getAnnList"
            "?game=nap&game_biz=nap_cn&lang=zh-cn&bundle_id=nap_cn&channel_id=1"
            "&level=60&platform=pc&region=prod_gf_cn&uid=100000000"
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
    {
        "game_name": "阴阳师",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://yys.163.com/",
        "source": "netease",
        # 「最新」页已聚合 公告 + 新闻 + 活动，无需再分别抓三个栏目页。
        "list_url": "https://yys.163.com/news/index.html",
        "encoding": "utf-8",
        # 列表项 DOM：<a class="link" title="标题"><p class="p-tit">08-19 标题</p>
        #   <p class="p-mess">正文</p><span class="category">公告</span></a>
        # 日期与标题同在 .p-tit 里，标题另有 title 属性可直接取。
        "dom": {
            "item": ".news-list a.link",
            "date_sel": ".p-tit",
            "date_fmt": "%m-%d",
            "title_attr": "title",
            "label_sel": ".category",
            "summary_sel": ".p-mess",
            "detail_summary_sel": ".artText",
        },
    },
    {
        "game_name": "逆水寒",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://n.163.com/",
        "source": "nsh",
        "list_url": "https://n.163.com/news/",
        "encoding": "utf-8",
        # 列表项 DOM：<a title="标题"><div class="news-time"><strong>20</strong>
        #   <span>26.08</span></div><div class="type">公告</div>
        #   <div class="title">标题</div><div class="desc">摘要</div></a>
        # 日期拆成「日」+「两位年.月」两个节点，故用 day_sel / year_month_sel。
        "dom": {
            "item": "ul.news-list li a",
            "day_sel": ".news-time strong",
            "year_month_sel": ".news-time span",
            "title_attr": "title",
            "label_sel": ".type",
            "summary_sel": ".desc",
            "detail_summary_sel": ".artText",
        },
    },
    {
        "game_name": "永劫无间",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://www.yjwujian.cn/news/",
        "source": "netease",
        "list_url": "https://www.yjwujian.cn/news/",
        "encoding": "utf-8",
        # 列表项 DOM：<a class="news-itme" href="..."><span class="title">标题</span>
        #   <span class="date">[08-14]</span></a>（class 拼写是站点原样）
        "dom": {
            "item": "a.news-itme",
            "date_sel": ".date",
            "date_fmt": "%m-%d",
            "title_sel": ".title",
            "label_sel": None,  # 该站列表项无类型标签元素
            "summary_sel": None,
            # 不能用 .content：该站 .content 命中的是页脚版权信息。
            "detail_summary_sel": ".artText",
        },
    },
    {
        "game_name": "我的世界",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://mc.163.com/",
        "source": "netease",
        "list_url": "https://mc.163.com/news/",
        "encoding": "utf-8",
        # 列表项 DOM：<a title="标题"><i>新闻</i><p class="lside">
        #   <span class="title">标题</span><span class="comment">摘要</span></p>
        #   <span class="time">08-07</span></a>
        "dom": {
            "item": "ul.list li a",
            "date_sel": ".time",
            "date_fmt": "%m-%d",
            "title_attr": "title",
            "label_sel": "i",
            "summary_sel": ".comment",
            # 不配 detail_summary_sel：详情页 .artText 存在但文本长度为 0，
            # 摘要只能从列表 .comment 取。
        },
    },
    {
        "game_name": "光遇",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://sky.163.com/",
        "source": "netease",
        "list_url": "https://sky.163.com/news/",
        "encoding": "utf-8",
        # 列表项 DOM：<a href="..."><div><img/></div><div class="text">
        #   <div>2026-08-19</div><div>标题</div><div>摘要</div></div></a>
        # .text 下三个 div 全无 class，只能靠 :nth-of-type 定位；<a> 无 title 属性。
        "dom": {
            "item": "#list_show > a",
            "date_sel": ".text > div:nth-of-type(1)",
            "date_fmt": "%Y-%m-%d",
            "title_sel": ".text > div:nth-of-type(2)",
            "label_sel": None,  # 页面无类型标签元素，类型由标题推断
            "summary_sel": ".text > div:nth-of-type(3)",
            "detail_summary_sel": ".artText",
        },
    },
    {
        "game_name": "遗忘之海",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://sea.163.com/",
        "source": "netease",
        "list_url": "https://sea.163.com/news/",
        "encoding": "utf-8",
        # 列表项 DOM：<a class="item" href="https://..."><div class="text">
        #   <div class="title"><span>公告</span>标题</div>
        #   <div class="time">2026.08.19</div></div></a>
        # 日期用点号分隔；类型标签 <span> 嵌在 .title 内，取标题时要剥掉。
        "dom": {
            "item": "ul.news_list a.item",
            "date_sel": ".time",
            "date_fmt": "%Y.%m.%d",
            "title_sel": ".title",
            "title_strip": "span",
            "label_sel": ".title span",
            "summary_sel": None,
            "detail_summary_sel": ".artText",
        },
    },
    {
        "game_name": "梦幻西游手游",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://my.163.com/",
        "source": "netease",
        # 新闻 + 活动两个栏目页（/news/weihu/ 与新闻页同 artId 完全重复，不抓）。
        "list_urls": [
            "https://my.163.com/news/news/",
            "https://my.163.com/news/remen/",
        ],
        # 全站唯一非 utf-8 的站点：utf-8 会抛 UnicodeDecodeError，GB2312 会在
        # 生僻字上失败，必须 gb18030。
        "encoding": "gb18030",
        # 列表项 DOM：<a title="标题"><span class="news_time" data-date="08-18">
        #   日 月</span><span class="news_title">标题</span>
        #   <span class="news_desc">摘要</span></a>
        # 日期只存在于 data-date 属性里（元素文本恒为「日 月」），故用 date_attr。
        "dom": {
            "item": "._con li a",
            "date_sel": ".news_time",
            "date_attr": "data-date",
            "date_fmt": "%m-%d",
            "title_attr": "title",
            "summary_sel": ".news_desc",
            # 活动栏目的 href 是专题落地页，没有统一模板也没有 .artText，
            # 取不到时自动回退列表摘要。
            "detail_summary_sel": ".artText",
        },
    },
    {
        "game_name": "巅峰极速",
        "publisher": "网易",
        "publisher_key": "netease",
        "official_url": "https://speed.163.com/",
        "source": "netease",
        # 单栏目：/news/official/ 等子栏目全部 404。
        "list_url": "https://speed.163.com/news/",
        "encoding": "utf-8",
        # 列表项 DOM：<a title="标题"><h2 class="news-tit"><p>标题</p>
        #   <span>2026.07.24</span></h2><p class="news-desc">摘要</p></a>
        "dom": {
            "item": "ul.news-list li a",
            "date_sel": ".news-tit span",
            "date_fmt": "%Y.%m.%d",
            "title_attr": "title",
            "label_sel": None,  # 该站列表项无类型标签元素
            "summary_sel": ".news-desc",
            "detail_summary_sel": ".artText",
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
    # 以下 4 款走配置驱动的通用采集（source="cmc"）：同一个 cmc/cross 接口，
    # 只是 serviceId / query 串 / 频道或标签 / 详情页链接规则不同。均无需签名，
    # 也不需要 Referer。注意 chanid 只认单值：逗号分隔返回 "invalid chanid"，
    # 重复传参只生效第一个，故多频道写成 chanids 列表，由 handler 逐个请求后
    # 按条目 id 去重合并；tagids 则支持逗号多值（配 logic=or）。
    {
        "game_name": "王者荣耀",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://pvp.qq.com/",
        "source": "cmc",
        "list_url": "https://pvp.qq.com/web201706/newsindex.shtml",
        "serviceId": "18",
        "cmc": {
            # 传 exclusiveChannel/exclusiveChannelSign 反而报 empty time，不要加。
            "query": (
                "filter=channel&sortby=sIdxTime&source=web_pc&limit=50"
                "&logic=or&typeids=1,2&start=0&withtop=yes"
            ),
            # 频道：1760 热门、1761 新闻、1762 公告、1763 活动、1764 赛事（不收）
            "chanids": ["1761", "1762", "1763"],
            # 一条内容可同时挂多个频道，赛事稿会混进新闻/活动，需二次剔除。
            "exclude_chanids": ["1764"],
            "type_map": [("1762", "公告"), ("1763", "活动"), ("1761", "新闻")],
            "id_field": "iId",
            "detail_url": "https://pvp.qq.com/web201706/newsdetail.shtml?tid={id}",
            # sVID 非空是视频稿，详情页走视频模板。
            "video_url": "https://pvp.qq.com/web201706/v/detail.shtml?G_Biz=18&tid={id}",
        },
    },
    {
        "game_name": "金铲铲之战",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://jcc.qq.com/",
        "source": "cmc",
        "list_url": "https://jcc.qq.com/#/news",
        "serviceId": "283",
        "cmc": {
            # source 必须是 JK_gw（web_pc 会被拒）；该站无 filter 参数，按 tag 组织。
            "query": "source=JK_gw&typeids=1&logic=or&start=0&limit=20",
            # 标签：116054 公告、118283 新闻、116025 社区（不收）
            "tagids": "116054,118283",
            # 116025 在页面上叫「社区」，但接口 sTagInfo 里名字是「教学」，
            # 按名字过滤会漏，必须按 id 排除。sChannelInfo 该站恒为空串。
            "exclude_tagids": ["116025"],
            "type_map": [("116054", "公告"), ("118283", "新闻")],
            # 详情页用 iDocID（长数字串），不是 iNewsId。
            "id_field": "iDocID",
            "detail_url": "https://jcc.qq.com/#/news/{id}",
        },
    },
    {
        "game_name": "暗区突围",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://aqtwwx.qq.com/",
        "source": "cmc",
        "list_url": "https://aqtwwx.qq.com/web202501/news.html",
        "serviceId": "463",
        "cmc": {
            "query": (
                "source=web_pc&typeids=1&limit=20&start=0&filter=channel"
                "&withtop=yes&topMode=new"
            ),
            # 6858 最新即全量入口（覆盖公告 6887 / 更新 6888 / 新闻 7020 / 活动），
            # 7107 攻略不收。注意 6858 频道名在 sChannelInfo 里是 "6858|web_pc"，
            # 别按名字匹配；sTagIds 常为空串，分类主判据必须是 sChannelInfo。
            "chanids": ["6858"],
            "exclude_chanids": ["7107"],
            "exclude_tagids": ["139946"],  # 攻略标签，辅助判据
            "type_map": [
                ("6887", "公告"),
                ("6888", "更新"),
                ("7020", "新闻"),
                ("138636", "新闻"),
            ],
            "id_field": "iNewsId",
            "detail_url": "https://aqtwwx.qq.com/web202501/newsdetail.html?newsid={id}",
        },
    },
    {
        "game_name": "穿越火线-枪战王者",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://cfm.qq.com/",
        "source": "cmc",
        "list_url": "https://cfm.qq.com/web201801/newlist.shtml",
        "serviceId": "34",
        "cmc": {
            "query": "source=web_pc&typeids=1,2&filter=channel&logic=or&start=0&limit=20",
            # 频道：3682 版本、706 活动、783 公告、640 赛事、713 更多(视频)。
            # 需求只要活动 + 公告两个 tab。
            "chanids": ["706", "783"],
            "exclude_chanids": ["640"],
            "type_map": [("783", "公告"), ("706", "活动")],
            # 详情页只认 iDocID（列表页模板即 detail.shtml?docid=...）；
            # 实测 newsdetail.shtml?id={iNewsId} 返回 404。
            "id_field": "iDocID",
            "detail_url": "https://cfm.qq.com/web201801/detail.shtml?docid={id}",
        },
    },
    {
        "game_name": "使命召唤手游",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://codm.qq.com/",
        "source": "codm",
        # gicp SSR 列表页：/gicp/news/886/2/{chanid}/{page}.html，每页 10 条。
        # chanid：19485 综合（全部混排）/ 112919 新闻 / 112918 公告 / 120840 日志。
        "list_url": "https://codm.qq.com/gicp/news/886/2/19485/1.html",
    },
    {
        "game_name": "火影忍者",
        "publisher": "腾讯",
        "publisher_key": "tencent",
        "official_url": "https://hyrz.qq.com/",
        "source": "hyrz",
        "list_url": "https://hyrz.qq.com/web202003/newsList.html",
    },
    # ---------------- 鹰角 / 库洛 / 叠纸 ----------------
    # 同一个 tab 下混排三家公司，故每款游戏带 company 字段供前端括号展示。
    # 7 个站点归为 3 个 source：鹰角两站字段一致（hypergryph）、叠纸三站同一套
    # 后端（papegames）、库洛两站同一套静态 CMS（kuro），差异全部写在配置里。
    {
        "game_name": "明日方舟",
        "publisher": "鹰角网络",
        "publisher_key": "hg_kuro_pape",
        "company": "鹰角",
        "official_url": "https://ak.hypergryph.com/",
        "source": "hypergryph",
        # LATEST 单页只回 6 条（total=12），需按 page 翻到 end:true。
        "list_url": "https://ak.hypergryph.com/api/news?category=LATEST&page={page}",
        "detail_url_prefix": "https://ak.hypergryph.com/news/",
        "tab_types": {"0": "公告", "1": "活动", "2": "新闻"},
        "max_pages": 5,
    },
    {
        "game_name": "明日方舟：终末地",
        "publisher": "鹰角网络",
        "publisher_key": "hg_kuro_pape",
        "company": "鹰角",
        "official_url": "https://endfield.hypergryph.com/",
        "source": "hypergryph",
        # 接口在独立域名，code=endfield_web 必填，pageSize 服务端上限 20
        # （20 条可回溯一个多月，7 天窗口无需翻页）。
        "list_url": (
            "https://web-news.hypergryph.com/api/bulletin?lang=zh-cn"
            "&code=endfield_web&page={page}&pageSize=20"
        ),
        "detail_url_prefix": "https://endfield.hypergryph.com/news/",
        # 该站 tab 是 slug，不是数字。
        "tab_types": {"notices": "公告", "news": "新闻", "events": "活动"},
    },
    {
        "game_name": "无限暖暖",
        "publisher": "叠纸游戏",
        "publisher_key": "hg_kuro_pape",
        "company": "叠纸",
        "official_url": "https://infinitynikki.nuanpaper.com/",
        "source": "papegames",
        "list_url": "https://infinitynikki.nuanpaper.com/api/news?offset=0&limit=20",
        "detail_url_prefix": "https://infinitynikki.nuanpaper.com/news/",
        "section_types": {"0": "新闻", "1": "公告", "2": "活动"},
    },
    {
        "game_name": "闪耀暖暖",
        "publisher": "叠纸游戏",
        "publisher_key": "hg_kuro_pape",
        "company": "叠纸",
        "official_url": "https://nikki4.papegames.cn/",
        "source": "papegames",
        # 该站路径带 v1/。limit=30：版本更新日单日可发 12 条以上。
        "list_url": "https://nikki4.papegames.cn/api/v1/news?offset=0&limit=30",
        "detail_url_prefix": "https://nikki4.papegames.cn/news/",
        # section 语义与无限暖暖不同，不能共用一张表。
        "section_types": {"0": "新闻", "1": "活动", "2": "公告", "3": "系统玩法"},
    },
    {
        "game_name": "恋与制作人",
        "publisher": "叠纸游戏",
        "publisher_key": "hg_kuro_pape",
        "company": "叠纸",
        # 官网是 SSG 站，/home#2 只是首页 hash 锚点，真实列表页是 /news/more。
        "official_url": "https://evol.papegames.cn/",
        "source": "papegames",
        # 该站没有 v1/（/api/v1/news 返回 404）。
        "list_url": "https://evol.papegames.cn/api/news?offset=0&limit=20",
        "detail_url_prefix": "https://evol.papegames.cn/news/",
        # 不配 section_types：该站 section 语义混乱（0 是公告/活动/资讯大杂烩、
        # 1 抽奖名单、2 同人征集），类型改由 _classify_type 按标题关键词判定。
    },
    {
        "game_name": "鸣潮",
        "publisher": "库洛游戏",
        "publisher_key": "hg_kuro_pape",
        "company": "库洛",
        "official_url": "https://mc.kurogames.com/",
        "source": "kuro",
        # 该站路径带 /zh。
        "list_url": (
            "https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/"
            "json/G152/zh/ArticleMenu.json"
        ),
        # 详情页带 /detail/。
        "detail_url_prefix": "https://mc.kurogames.com/main/news/detail/",
        "article_types": {"51": "新闻", "52": "公告", "53": "活动"},
    },
    {
        "game_name": "战双帕弥什",
        "publisher": "库洛游戏",
        "publisher_key": "hg_kuro_pape",
        "company": "库洛",
        "official_url": "https://pns.kurogames.com/",
        "source": "kuro",
        # 该站路径不带 /zh（带了 404）。
        "list_url": (
            "https://media-cdn-zspms.kurogame.com/pnswebsite/website2.0/"
            "json/G144/ArticleMenu.json"
        ),
        # 详情页不带 /detail/。
        "detail_url_prefix": "https://pns.kurogames.com/news/",
        # 数据里还有字典外的历史类型 35 / 54（2022-2023 的旧攻略文），
        # 由 fetcher 兜底成「公告」，不影响 7 天窗口。
        "article_types": {"4": "新闻", "5": "公告", "43": "活动"},
    },
    # ---------------- 其他 ----------------
    {
        "game_name": "异环",
        "publisher": "完美世界",
        "publisher_key": "other",
        "company": "完美世界",
        "official_url": "https://yh.wanmei.com/news/index.html",
        "source": "wanmei",
        "list_url": "https://yh.wanmei.com/news/index.html",
        # 第 N 页是 index{N-1}.html（共 24 页，每页 3 条）。严格倒序无置顶，
        # 遇到窗口外条目即停，max_pages 只是保险上限。
        "page_url": "https://yh.wanmei.com/news/index{index}.html",
        "max_pages": 5,
        "base_url": "https://yh.wanmei.com",
    },
    {
        "game_name": "超自然行动组",
        "publisher": "巨人网络",
        "publisher_key": "other",
        "company": "巨人网络",
        # 官网是 Nuxt SPA，HTML 里没有数据，实际抓 sphinx 列表接口。
        "official_url": "https://www.chaoziran.com/news",
        "source": "preternatural",
        "list_url": (
            "https://sphinx.preternatural.cc/api/official/article/list"
            "?gametag=preternatural&page=1&pageSize=999&category={category}"
        ),
        "detail_url_prefix": "https://www.chaoziran.com/news/",
        # 分类值取自官网 JS chunk，需逐个分类请求一次。
        "category_types": {"2": "新闻", "6": "公告", "3": "活动"},
    },
    {
        "game_name": "命运-冠位指定",
        "publisher": "哔哩哔哩",
        "publisher_key": "other",
        "company": "B站",
        "official_url": "https://game.bilibili.com/fgo/news.html",
        "source": "biligame",
        # gameExtensionId=45 来自官网 news.js（不是 game_base_id=49）；
        # positionId=2 必填（1/3/4 返回 totalNum=0），typeId 留空即全部类型。
        "list_url": (
            "https://api.biligame.com/news/list.action?gameExtensionId=45"
            "&positionId=2&pageNum=1&pageSize=50&typeId="
        ),
        "detail_url_tpl": "https://game.bilibili.com/fgo/news.html#!news/0/1/{id}",
        # 「攻略」(5)、「评测」(3) 不在前端类型白名单里，归一化成「新闻」。
        "type_names": {"1": "公告", "2": "新闻", "3": "新闻", "4": "活动", "5": "新闻"},
    },
    {
        "game_name": "三国：谋定天下",
        "publisher": "哔哩哔哩",
        "publisher_key": "other",
        "company": "B站",
        "official_url": "https://game.bilibili.com/nslg/",
        "source": "biligame",
        # gameExtensionId=1039（由首页 newsId 反查 news/{id}.action 的 gameInfo）。
        "list_url": (
            "https://api.biligame.com/news/list.action?gameExtensionId=1039"
            "&positionId=2&pageNum=1&pageSize=50&typeId="
        ),
        # 该站无独立详情路由（/nslg/news* 全 404），详情走首页的 query 参数。
        "detail_url_tpl": "https://game.bilibili.com/nslg/?news_detail_id={id}",
        "type_names": {"1": "公告", "2": "新闻", "3": "新闻", "4": "活动", "5": "新闻"},
    },
    {
        "game_name": "白银之城",
        "publisher": "乐元素",
        "publisher_key": "other",
        "company": "乐元素",
        # 必须固定用 leyuansu 域名：镜像站 elementagames 同一篇文章 id 不同，
        # 混用会导致详情链接串号。
        "official_url": "https://silverpalace.leyuansu.com/zh-cn/news",
        "source": "silverpalace",
        # lang=zh-cn 必填；不传 type 即全部分类；size 被服务端压到 10/页，
        # 按响应里的 total_page 翻页（实测 total_page=5）。
        "list_url": (
            "https://silverpalace.leyuansu.com/server/index.php/home/news_list"
            "?lang=zh-cn&page={page}&size=10"
        ),
        "detail_url_prefix": "https://silverpalace.leyuansu.com/zh-cn/newsDetail?id=",
        "category_types": {
            "news": "新闻",
            "announcements": "公告",
            "events": "活动",
        },
        "max_pages": 10,
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
    分隔符兼容 '-'、'/'、'.'（燕云十六声用 08/15，遗忘之海/巅峰极速用
    2026.08.19）。"""
    if not raw:
        return None
    raw = raw.strip()
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    if fmt in ("%m-%d", "%m/%d"):
        m = re.search(r"(\d{1,2})[-/.](\d{1,2})", raw)
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
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
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
def _netease_soup(game, url, timeout=12):
    """请求网易系 SSR 页面并解析成 soup。

    配了 encoding 就显式钉死编码：这些站响应头普遍不带 charset，
    apparent_encoding 会误判（梦幻西游是 gb18030，按 utf-8 解码直接抛异常；
    光遇的 404 页又是 GB 编码，不能靠"能否 utf-8 解码"判断有效性）。
    """
    resp = fetch_json(url, timeout=timeout)
    if game.get("encoding"):
        resp.encoding = game["encoding"]
    return BeautifulSoup(resp.text, "html.parser")


def _netease_detail_summary(game, url, selector):
    """列表页无摘要时，回退请求详情页取正文首段。失败/取不到均返回空串。"""
    try:
        dnode = _netease_soup(game, url, timeout=10).select_one(selector)
        if dnode:
            return _clean_summary(dnode.get_text(" ", strip=True), is_html=False)
    except Exception as exc:  # 网络/解析异常都降级为空摘要
        logger.warning("%s 详情页摘要获取失败：%s（%s）", game["game_name"], url, exc)
    return ""


def _netease_update(game, item, ann_date):
    """把一个网易系列表项 <a> 组装成 update 记录（日期由调用方解析后传入）。

    逆水寒（source="nsh"）的日期解析方式不同，但标题/类型/摘要/链接的取法
    与 netease 系完全一致，故共用本函数。
    """
    dom = game["dom"]

    # 类型标签（列表页 <i>/<span> 里的「新闻」/「公告」等）。必须在取标题之前读，
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

    # 链接。href 有 '//' 协议相对与绝对 https 两种形态。
    href = item.get("href", "") or ""
    url = href if href.startswith("http") else ("https:" + href if href else game["official_url"])

    # 摘要
    summary = ""
    if dom.get("summary_sel"):
        snode = item.select_one(dom["summary_sel"])
        if snode:
            summary = _clean_summary(snode.get_text(" ", strip=True), is_html=False)
    # 列表页无摘要元素（如第五人格）时回退详情页正文；只对配了
    # detail_summary_sel 的游戏生效，单条失败不影响其它条目。
    if not summary and dom.get("detail_summary_sel") and url.startswith("http"):
        summary = _netease_detail_summary(game, url, dom["detail_summary_sel"])

    return {
        "title": title or "（无标题）",
        "type": _classify_type(label, title),
        "date": ann_date.isoformat(),
        "summary": summary,
        "url": url,
    }


def fetch_netease_updates(game):
    """抓取网易系游戏新闻列表页近 7 天条目，返回 update 列表。

    各游戏站点 DOM 结构不同，用 game["dom"] 声明选择器：
      item        列表项选择器（CSS）
      date_sel    日期节点选择器（相对 item）
      date_attr   日期取自该节点的属性（如梦幻西游的 data-date），
                  未配置时取节点文本
      date_fmt    日期格式：'%Y-%m-%d' 完整日期 / '%m-%d' 仅月日
                  （分隔符 - / . 都兼容，见 _parse_netease_date）
      title_attr  标题取自 item 的该属性（如 title）；与 title_sel 二选一
      title_sel   标题文本选择器（相对 item）
      title_strip 取标题前先移除的子元素选择器（如类型标签 <i>）
      label_sel   类型标签文本选择器（相对 item），None/取不到时退回空串
      summary_sel 摘要文本选择器（相对 item），None 表示无摘要
      detail_summary_sel  列表页无摘要时，回退请求详情页用该选择器取正文（相对详情页文档）

    游戏配置里 list_urls（列表）与 list_url（单个）二选一：梦幻西游要同时抓
    新闻与活动两个栏目页，两页 DOM 完全一致，故共用一份 dom。
    """
    dom = game["dom"]
    cutoff = _cutoff_date()
    updates = []
    seen = set()
    for list_url in game.get("list_urls") or [game["list_url"]]:
        soup = _netease_soup(game, list_url)
        for item in soup.select(dom["item"]):
            # 日期
            date_node = item.select_one(dom["date_sel"]) if dom.get("date_sel") else None
            if date_node is None:
                continue
            if dom.get("date_attr"):
                raw_date = (date_node.get(dom["date_attr"]) or "").strip()
            else:
                raw_date = date_node.get_text(" ", strip=True)
            ann_date = _parse_netease_date(raw_date, dom.get("date_fmt", "%Y-%m-%d"))
            if not ann_date or ann_date < cutoff:
                continue

            update = _netease_update(game, item, ann_date)
            if update["url"] in seen:
                continue
            seen.add(update["url"])
            updates.append(update)
    return updates


def fetch_nsh_updates(game):
    """抓取逆水寒官网新闻列表页近 7 天条目。

    与 netease 系的唯一差异是日期：该站把日期拆成两个节点
    <div class="news-time"><strong>20</strong><span>26.08</span></div>，
    strong 是「日」、span 是「两位年.月」，必须分别取值再组日期
    （get_text 拼接会得到 "2026.08" / "1926.08" 之类的错值）。
    href 里的 8 位数字与列表显示日期并不一致（显示 08-20 的那条 href 是
    20260819），以显示日期为准。
    """
    dom = game["dom"]
    soup = _netease_soup(game, game["list_url"])

    cutoff = _cutoff_date()
    updates = []
    seen = set()
    for item in soup.select(dom["item"]):
        day_node = item.select_one(dom["day_sel"])
        ym_node = item.select_one(dom["year_month_sel"])
        if not day_node or not ym_node:
            continue
        ym = ym_node.get_text(strip=True)  # 如 "26.08"
        m = re.match(r"(\d{2})\D(\d{1,2})$", ym)
        if not m:
            continue
        try:
            ann_date = datetime(
                2000 + int(m.group(1)), int(m.group(2)), int(day_node.get_text(strip=True))
            ).date()
        except ValueError:
            continue
        if ann_date < cutoff:
            continue

        update = _netease_update(game, item, ann_date)
        if update["url"] in seen:
            continue
        seen.add(update["url"])
        updates.append(update)
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


# ---------------------------------------------------------------------------
# 腾讯内容中心通用采集（配置驱动，见 GAMES 的 cmc 字段）
# 覆盖王者荣耀 / 金铲铲之战 / 暗区突围 / 穿越火线-枪战王者
# ---------------------------------------------------------------------------
def _cmc_id_names(info):
    """解析 "706|活动,828|最新攻略" 形态的频道/标签串为 {id: 名称}。"""
    result = {}
    for part in (info or "").split(","):
        cid, sep, name = part.partition("|")
        cid = cid.strip()
        if sep and cid:
            result[cid] = name.strip()
    return result


def _cmc_tag_ids(item):
    """条目的标签 id 集合。sTagInfo 带中文名，sTagIds 只有 id，两者取并集。"""
    ids = set(_cmc_id_names(item.get("sTagInfo")))
    ids |= {t.strip() for t in (item.get("sTagIds") or "").split(",") if t.strip()}
    return ids


def _cmc_excluded(item, cfg):
    """按频道 id / 标签 id 判断条目是否属于不采集的栏目（如赛事、攻略、社区）。

    分频道站与分标签站的 id 空间不同，故排除规则也分开配，避免 id 撞号误杀。
    """
    chan_ids = set(_cmc_id_names(item.get("sChannelInfo")))
    if chan_ids & set(cfg.get("exclude_chanids") or ()):
        return True
    return bool(_cmc_tag_ids(item) & set(cfg.get("exclude_tagids") or ()))


def _cmc_classify(item, cfg):
    """先按 type_map（频道/标签 id -> 中文标注）取标注，再交给 _classify_type 细分。

    type_map 是有序列表，取第一个命中的（越具体的排前面），一条内容常同时挂
    多个频道/标签。映射不到时 label 为空，退化为纯标题关键词判定。
    """
    ids = set(_cmc_id_names(item.get("sChannelInfo"))) | _cmc_tag_ids(item)
    label = ""
    for cid, name in cfg.get("type_map") or []:
        if cid in ids:
            label = name
            break
    return _classify_type(label, item.get("sTitle") or "")


def _cmc_fetch_items(game, cfg, key, value):
    """按单个 chanid / tagids 取一页条目。"""
    url = (
        "https://apps.game.qq.com/cmc/cross?serviceId=" + str(game["serviceId"])
        + "&" + cfg["query"]
        + "&" + key + "=" + value
    )
    data = _load_cmc_json(fetch_json(url, timeout=12).text)
    if data.get("status") != 0:
        raise RuntimeError(
            f"cmc/cross status={data.get('status')}：{data.get('msg')}（{key}={value}）"
        )
    payload = data.get("data")
    payload = payload if isinstance(payload, dict) else {}
    return payload.get("items") or []


def fetch_cmc_updates(game):
    """抓取腾讯内容中心近 7 天条目（配置驱动，适配多款游戏）。"""
    cfg = game["cmc"]
    # chanid 只认单值（逗号 -> invalid chanid，重复传参只生效第一个），
    # 多频道逐个请求后合并；tagids 支持逗号多值，一次请求即可。
    queries = [("chanid", c) for c in (cfg.get("chanids") or [])]
    if cfg.get("tagids"):
        queries.append(("tagids", cfg["tagids"]))

    items, seen = [], set()
    for key, value in queries:
        for item in _cmc_fetch_items(game, cfg, key, value):
            uid = str(item.get("iId") or item.get("iNewsId") or item.get("iDocID") or "")
            if uid and uid in seen:
                continue
            seen.add(uid)
            items.append(item)
    logger.info(
        "%s：接口返回 %d 条（%d 次请求去重后）", game["game_name"], len(items), len(queries)
    )

    cutoff = _cutoff_date()
    updates, dropped = [], []
    for item in items:
        ann_date = _cmc_date(item)
        if not ann_date or ann_date < cutoff:
            continue
        if _cmc_excluded(item, cfg):
            dropped.append(item.get("sTitle") or "")
            continue

        id_value = item.get(cfg["id_field"])
        if id_value:
            template = cfg["detail_url"]
            if cfg.get("video_url") and (item.get("sVID") or "").strip():
                template = cfg["video_url"]
            detail_url = template.format(id=id_value)
        else:
            detail_url = game["official_url"]

        updates.append(
            {
                "title": (item.get("sTitle") or "").strip() or "（无标题）",
                "type": _cmc_classify(item, cfg),
                "date": ann_date.isoformat(),
                # 这几个站列表接口的 sDesc 实测恒为空串；不为此逐条抓正文，
                # 否则 CI 请求量翻倍。有值时直接用。
                "summary": _clean_summary(item.get("sDesc") or ""),
                "url": detail_url,
            }
        )
    if dropped:
        logger.info(
            "%s：按排除频道/标签剔除 %d 条：%s",
            game["game_name"], len(dropped), " / ".join(dropped[:5]),
        )
    return updates


# ---------------------------------------------------------------------------
# 使命召唤手游（gicp 服务端渲染列表页）
# ---------------------------------------------------------------------------
def fetch_codm_updates(game):
    """抓取使命召唤手游官网资讯列表近 7 天条目。

    cmc/cross 对 codm 是封的（serviceId=886/887 各种 source 都返回
    status=-97 非法请求来源），只能解析 gicp SSR 页面。
    """
    resp = fetch_json(game["list_url"], timeout=12)
    # 页面是 GBK，apparent_encoding 会猜错导致中文乱码，必须强制 gb18030。
    resp.encoding = "gb18030"
    rows = BeautifulSoup(resp.text, "html.parser").select("#news-list a.txt-line-wrapper")
    if not rows:
        raise RuntimeError("codm 列表页未解析到条目，页面结构可能已变化")

    cutoff = _cutoff_date()
    updates = []
    for a in rows:
        tnode, dnode = a.select_one("span.title"), a.select_one("span.time")
        if not tnode or not dnode:
            continue
        # 列表时间形如 2026-08-19 10:23:39。
        ann_date = _parse_netease_date(dnode.get_text(strip=True), "%Y-%m-%d")
        if not ann_date or ann_date < cutoff:
            continue

        title = tnode.get_text(strip=True)
        href = a.get("href") or ""
        # href 是相对路径（列表在 886 目录，详情在 887 目录）。
        url = href if href.startswith("http") else "https://codm.qq.com" + href

        updates.append(
            {
                "title": title or "（无标题）",
                # 页面 HTML 没有任何分类字段，类型只能按标题关键词兜底。
                "type": _classify_type(None, title),
                "date": ann_date.isoformat(),
                # 列表页无摘要元素，留空（不额外请求详情页）。
                "summary": "",
                "url": url,
            }
        )
    return updates


# ---------------------------------------------------------------------------
# 火影忍者（腾讯老 wmp 接口，不是 cmc/cross）
# ---------------------------------------------------------------------------
# 该接口没有 sChannelInfo / sTagInfo，拿不到中文分类名，只能按 sTagIds 判类型。
# 注意：sTagIds 是无序多标签，赛事等标签常不在首位，必须对**全部** id 求交集，
# 不能只看第一个。命中以下任一标签即不算「新闻」，从「最新」列表里剔除：
_HYRZ_EXCLUDED_TAGS = {
    "18813": "赛事",
    "18808": "攻略",
    "18806": "视频",
    "138135": "体验服",
    "18812": "公告",  # 公告已由 18812 那次请求单独采集，避免重复
}

# 标签：18807 最新、18812 公告、18808 攻略、18813 赛事、18806 视频、138135 体验服。
# 需求只要公告 + 新闻：公告直取 18812，新闻从「最新」里剔掉上述排除标签。
_HYRZ_QUERIES = [("18812", "公告"), ("18807", "新闻")]


def fetch_hyrz_updates(game):
    """抓取火影忍者官网近 7 天公告与新闻。"""
    cutoff = _cutoff_date()
    headers = {"Referer": game["list_url"]}
    updates, seen = [], set()
    for tag_id, label in _HYRZ_QUERIES:
        url = (
            "https://apps.game.qq.com/wmp/v3.1/?p0=25&p1=searchNewsKeywordsList"
            "&page=1&pagesize=10&order=sIdxTime&r0=cors&r1=NewsObj&type=iTag"
            "&id=" + tag_id + "&source=web_ingame"
        )
        data = _load_cmc_json(fetch_json(url, timeout=12, headers=headers).text)
        if data.get("status") != 0:
            raise RuntimeError(f"wmp status={data.get('status')}：{data.get('msg')}")
        # 与 cmc/cross 不同：列表在 msg.result，分页信息也在 msg 里。
        msg = data.get("msg")
        items = (msg.get("result") or []) if isinstance(msg, dict) else []
        logger.info("%s：标签 %s 返回 %d 条", game["game_name"], tag_id, len(items))

        for item in items:
            ann_date = _cmc_date(item)
            if not ann_date or ann_date < cutoff:
                continue
            tag_ids = {t.strip() for t in (item.get("sTagIds") or "").split(",")}
            # 「最新」里只保留新闻：命中任一排除标签就跳过（多标签无序，取全集交集）。
            if label == "新闻" and tag_ids & _HYRZ_EXCLUDED_TAGS.keys():
                continue
            news_id = str(item.get("iNewsId") or "").strip()  # 该接口 iNewsId 是字符串
            if news_id and news_id in seen:
                continue
            seen.add(news_id)

            title = (item.get("sTitle") or "").strip()
            updates.append(
                {
                    "title": title or "（无标题）",
                    "type": _classify_type(label, title),
                    "date": ann_date.isoformat(),
                    "summary": _clean_summary(item.get("sDesc") or ""),
                    "url": (
                        f"https://hyrz.qq.com/web202003/newsDetails.html?aid={news_id}&pageType=0"
                        if news_id
                        else game["official_url"]
                    ),
                }
            )
    return updates


# ---------------------------------------------------------------------------
# 鹰角 / 叠纸 / 库洛（3 个 source 覆盖 7 个站点）
# ---------------------------------------------------------------------------
def _fetch_json_utf8(url, timeout=12):
    """请求并解析 JSON，强制按 utf-8 解码。

    utils.fetch_json 用 apparent_encoding 猜编码，对 Content-Type 不带 charset
    的接口（ak.hypergryph.com、库洛 CDN）会猜成 ISO-8859-1 导致中文乱码，故这里
    直接解 resp.content。返回体不是 JSON（如错误页 HTML）时 json.loads 抛
    ValueError，与网络异常一样交给 build_game_record 降级成 source_status=error。
    """
    return json.loads(fetch_json(url, timeout=timeout).content.decode("utf-8"))


def _bj_date_from_unix(raw):
    """unix 秒（UTC）-> 北京时间日期（date）。"""
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, timezone(timedelta(hours=8))).date()


def _bj_date_from_iso_utc(raw):
    """ISO-8601 UTC 字符串（如 2026-08-19T04:00:00.000Z）-> 北京时间日期。

    必须做时区转换：直接切 [:10] 会把 UTC 16:00 之后的条目算少一天。
    """
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=8))).date()


def fetch_hypergryph_updates(game):
    """抓取鹰角系游戏（明日方舟 / 明日方舟：终末地）近 7 天条目。

    两站字段完全一致（title / displayTime unix 秒 UTC / tab 分类 / cid /
    brief 现成摘要），差异全部放在游戏配置里：
      list_url          列表接口，含 {page} 占位（终末地在独立域名 web-news）
      tab_types         tab 值 -> 栏目名（方舟是 "0/1/2"，终末地是 slug）
      detail_url_prefix 详情页前缀，拼 cid
      max_pages         翻页上限，默认 1（方舟 LATEST 单页只回 6 条，需翻页）
    """
    tab_types = game.get("tab_types") or {}
    items = []
    for page in range(1, game.get("max_pages", 1) + 1):
        data = _fetch_json_utf8(game["list_url"].format(page=page))
        if data.get("code") != 0:
            raise RuntimeError(f"hypergryph code={data.get('code')}：{data.get('msg')}")
        payload = data.get("data")
        if not isinstance(payload, dict) or not isinstance(payload.get("list"), list):
            raise RuntimeError("hypergryph 返回缺少 data.list")
        items.extend(payload["list"])
        # end=True 即末页。列表混排 sticky 置顶条目，不能靠"遇到旧条目"提前收工，
        # 只能翻到 end 再逐条比 cutoff（LATEST total=12，实测第 2 页即 end）。
        if payload.get("end") or not payload["list"]:
            break
    logger.info("%s：接口返回 %d 条", game["game_name"], len(items))

    cutoff = _cutoff_date()
    updates = []
    for item in items:
        ann_date = _bj_date_from_unix(item.get("displayTime"))
        if not ann_date or ann_date < cutoff:
            continue

        title = (item.get("title") or "").strip()
        cid = str(item.get("cid") or "")
        updates.append(
            {
                "title": title or "（无标题）",
                "type": _classify_type(tab_types.get(str(item.get("tab"))), title),
                "date": ann_date.isoformat(),
                # brief 是列表接口自带的纯文本摘要，无需请求详情页。
                "summary": _clean_summary(item.get("brief") or "", is_html=False),
                "url": game["detail_url_prefix"] + cid if cid else game["official_url"],
            }
        )
    return updates


def fetch_papegames_updates(game):
    """抓取叠纸系游戏（无限暖暖 / 闪耀暖暖 / 恋与制作人）近 7 天条目。

    同一套后端，响应封装 {"data":{"total":N,"data":[...]},"ret":0,"msg":"ok"}。
    差异放在游戏配置里：
      list_url          列表接口（闪耀暖暖路径带 v1/，另两站不带）。不传
                        section 参数即全分类；传 section=-1 会返回 total:0。
      section_types     section 值 -> 栏目名；恋与制作人不配该字段，其 section
                        语义混乱，类型退回 _classify_type 按标题判定
      detail_url_prefix 详情页前缀，拼 id
    """
    data = _fetch_json_utf8(game["list_url"])
    if data.get("ret") != 0:
        raise RuntimeError(f"papegames ret={data.get('ret')}：{data.get('msg')}")
    payload = data.get("data")
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError("papegames 返回缺少 data.data")
    items = payload["data"]
    logger.info(
        "%s：接口返回 %d 条（total=%s）",
        game["game_name"], len(items), payload.get("total"),
    )

    # 闪耀暖暖不传 section 的全量列表不是时间倒序（首条是 2019 年的置顶稿），
    # 故先按 publish_time 倒序，且只能逐条比 cutoff，不能遇到旧条目就 break。
    items = sorted(items, key=lambda i: str(i.get("publish_time") or ""), reverse=True)

    section_types = game.get("section_types") or {}
    cutoff = _cutoff_date()
    updates = []
    for item in items:
        ann_date = _bj_date_from_iso_utc(item.get("publish_time"))
        if not ann_date or ann_date < cutoff:
            continue

        title = (item.get("title") or "").strip()
        item_id = str(item.get("id") or "")
        updates.append(
            {
                "title": title or "（无标题）",
                "type": _classify_type(section_types.get(str(item.get("section"))), title),
                "date": ann_date.isoformat(),
                # 列表接口没有摘要字段（无限暖暖有 abstract 但实测恒为 null），
                # 不为此逐条抓正文；有值时直接用。
                "summary": _clean_summary(item.get("abstract") or "", is_html=False),
                "url": (
                    game["detail_url_prefix"] + item_id if item_id else game["official_url"]
                ),
            }
        )
    return updates


def fetch_kuro_updates(game):
    """抓取库洛系游戏（鸣潮 / 战双帕弥什）近 7 天条目。

    静态 JSON CMS，返回体是数组不是对象。差异放在游戏配置里：
      list_url          ArticleMenu.json（鸣潮路径带 /zh，战双不带，带了 404）
      article_types     articleType -> 栏目名，字典外的历史类型兜底成「公告」
      detail_url_prefix 详情页前缀（鸣潮带 /detail/，战双不带）
    """
    items = _fetch_json_utf8(game["list_url"])
    if not isinstance(items, list) or not items:
        raise RuntimeError("kuro ArticleMenu 返回不是非空数组")
    logger.info("%s：接口返回 %d 条", game["game_name"], len(items))

    # 返回顺序是按分类分组的（组内倒序），且有 top 置顶稿，必须逐条比 cutoff。
    items = sorted(items, key=lambda i: str(i.get("startTime") or ""), reverse=True)

    article_types = game.get("article_types") or {}
    cutoff = _cutoff_date()
    updates = []
    for item in items:
        # startTime 形如 "2026-08-20 10:00:00"，已是北京时间，不再转时区。
        ann_date = _parse_netease_date(item.get("startTime") or "", "%Y-%m-%d")
        if not ann_date or ann_date < cutoff:
            continue

        title = (item.get("articleTitle") or "").strip()
        article_id = str(item.get("articleId") or "")
        label = article_types.get(str(item.get("articleType")), "公告")
        updates.append(
            {
                "title": title or "（无标题）",
                "type": _classify_type(label, title),
                "date": ann_date.isoformat(),
                # articleDesc 是列表自带摘要（实测多为空串）；articleContent 在
                # 列表里被截断到 ~20 字符，不能当摘要用。
                "summary": _clean_summary(item.get("articleDesc") or "", is_html=False),
                "url": (
                    game["detail_url_prefix"] + article_id
                    if article_id
                    else game["official_url"]
                ),
            }
        )
    return updates


# ---------------------------------------------------------------------------
# 其他发行（完美世界 / 巨人 / B 站 / 乐元素）
# ---------------------------------------------------------------------------
def fetch_wanmei_updates(game):
    """抓取异环官网新闻列表（yh.wanmei.com）近 7 天条目。

    SSR HTML，第 1 页是 index.html，第 N 页是 index{N-1}.html，每页 3 条。
    列表严格按日期倒序且无置顶，故遇到窗口外条目即可停止翻页。
    """
    cutoff = _cutoff_date()
    updates = []
    for page in range(1, game.get("max_pages", 1) + 1):
        url = game["list_url"] if page == 1 else game["page_url"].format(index=page - 1)
        # 响应头不带 charset，走 apparent_encoding 会猜错，直接按 utf-8 解。
        html = fetch_json(url, timeout=12).content.decode("utf-8")
        items = BeautifulSoup(html, "html.parser").select("div.listNews > a")
        if not items:
            break

        stop = False
        for item in items:
            date_node = item.select_one("p.date")
            if date_node is None:
                continue
            # p.date 形如 2026-08-19，已是北京时间，不做时区转换。
            ann_date = _parse_netease_date(
                date_node.get_text(" ", strip=True), "%Y-%m-%d"
            )
            if not ann_date or ann_date < cutoff:
                stop = True
                break

            title_node = item.select_one("h2.title")
            title = title_node.get_text(" ", strip=True) if title_node else ""
            label_node = item.select_one("p.type")
            summary_node = item.select_one("div.des")
            href = (item.get("href") or "").strip()
            updates.append(
                {
                    "title": title or "（无标题）",
                    # p.type 已是中文栏目名（公告 / 新闻 / 活动）。
                    "type": _classify_type(
                        label_node.get_text(strip=True) if label_node else "", title
                    ),
                    "date": ann_date.isoformat(),
                    "summary": _clean_summary(
                        summary_node.get_text(" ", strip=True) if summary_node else "",
                        is_html=False,
                    ),
                    "url": (
                        game["base_url"] + href
                        if href.startswith("/")
                        else href or game["official_url"]
                    ),
                }
            )
        if stop:
            break
    return updates


def fetch_preternatural_updates(game):
    """抓取超自然行动组官网列表接口（sphinx.preternatural.cc）近 7 天条目。

    官网是 Nuxt SPA，HTML 里没有数据。接口按分类查询，category_types 里的每个
    分类各请求一次（2 新闻 / 6 公告 / 3 活动）。
    """
    cutoff = _cutoff_date()
    updates = []
    for category, label in game["category_types"].items():
        data = _fetch_json_utf8(game["list_url"].format(category=category))
        if data.get("code") != 0:
            raise RuntimeError(
                f"preternatural code={data.get('code')}：{data.get('msg')}"
            )
        payload = data.get("data")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise RuntimeError("preternatural 返回缺少 data.data")
        items = payload["data"]
        logger.info("%s：分类 %s（%s）返回 %d 条", game["game_name"], category, label, len(items))

        for item in items:
            # 部分历史条目的 publishAt 被刷成"接近请求时刻"，会把旧稿误算进窗口；
            # 正常条目 publishAt == updateAt，故取两者较小值。
            pub_date = _bj_date_from_unix(item.get("publishAt"))
            upd_date = _bj_date_from_unix(item.get("updateAt"))
            candidates = [d for d in (pub_date, upd_date) if d]
            ann_date = min(candidates) if candidates else None
            # 新闻分类首条是置顶稿，只能 continue，不能 break。
            if not ann_date or ann_date < cutoff:
                continue

            title = (item.get("title") or "").strip()
            item_id = str(item.get("id") or "")
            updates.append(
                {
                    "title": title or "（无标题）",
                    "type": _classify_type(label, title),
                    "date": ann_date.isoformat(),
                    # abstract 实测多为空串，不为此逐条抓正文。
                    "summary": _clean_summary(item.get("abstract") or "", is_html=False),
                    "url": (
                        game["detail_url_prefix"] + item_id
                        if item_id
                        else game["official_url"]
                    ),
                }
            )
    return updates


def fetch_biligame_updates(game):
    """抓取 B 站发行游戏（命运-冠位指定 / 三国：谋定天下）近 7 天条目。

    同一个 news/list.action 接口，两站只差 gameExtensionId。差异放在游戏配置里：
      list_url        列表接口（含 gameExtensionId / positionId=2）
      type_names      typeId -> 栏目名，攻略/评测归一化成「新闻」
      detail_url_tpl  详情页模板，拼 {id}
    """
    data = _fetch_json_utf8(game["list_url"])
    if data.get("code") != 0:
        raise RuntimeError(f"biligame code={data.get('code')}：{data.get('msg')}")
    items = data.get("data")
    if not isinstance(items, list):
        raise RuntimeError("biligame 返回缺少 data 数组")
    logger.info(
        "%s：接口返回 %d 条（totalNum=%s）",
        game["game_name"], len(items), data.get("totalNum"),
    )

    type_names = game.get("type_names") or {}
    cutoff = _cutoff_date()
    updates = []
    for item in items:
        # createTime 形如 "2026-08-14 17:00:00"，已是北京时间，不再转时区。
        ann_date = _parse_netease_date(item.get("createTime") or "", "%Y-%m-%d")
        # 列表头部有置顶稿（日期可能很旧），必须逐条比 cutoff，不能 break。
        if not ann_date or ann_date < cutoff:
            continue

        title = (item.get("title") or "").strip()
        item_id = str(item.get("id") or "")
        updates.append(
            {
                "title": title or "（无标题）",
                "type": _classify_type(type_names.get(str(item.get("typeId"))), title),
                "date": ann_date.isoformat(),
                # 列表接口没有摘要字段。
                "summary": "",
                "url": (
                    game["detail_url_tpl"].format(id=item_id)
                    if item_id
                    else game["official_url"]
                ),
            }
        )
    return updates


def fetch_silverpalace_updates(game):
    """抓取白银之城官网列表接口（silverpalace.leyuansu.com）近 7 天条目。

    不传 type 即全部分类，按响应里的 total_page 翻页；category 字段
    （news / announcements / events）映射成中文栏目名。
    """
    items = []
    total_page = 1
    for page in range(1, game.get("max_pages", 1) + 1):
        data = _fetch_json_utf8(game["list_url"].format(page=page))
        if data.get("code") != 0:
            raise RuntimeError(f"silverpalace code={data.get('code')}：{data.get('msg')}")
        payload = data.get("data")
        if not isinstance(payload, dict) or not isinstance(payload.get("list"), list):
            raise RuntimeError("silverpalace 返回缺少 data.list")
        items.extend(payload["list"])
        total_page = int(payload.get("total_page") or 1)
        if page >= total_page or not payload["list"]:
            break
    logger.info(
        "%s：接口返回 %d 条（total_page=%s）", game["game_name"], len(items), total_page
    )

    category_types = game.get("category_types") or {}
    cutoff = _cutoff_date()
    updates = []
    for item in items:
        # 列表是 id 倒序而非日期倒序，只能逐条比 cutoff，不能 break。
        # publish_date 形如 2026-07-23，已是北京时间。
        ann_date = _parse_netease_date(item.get("publish_date") or "", "%Y-%m-%d")
        if not ann_date or ann_date < cutoff:
            continue

        title = (item.get("title") or "").strip()
        item_id = str(item.get("id") or "")
        updates.append(
            {
                "title": title or "（无标题）",
                "type": _classify_type(category_types.get(item.get("category")), title),
                "date": ann_date.isoformat(),
                "summary": _clean_summary(item.get("desc") or "", is_html=False),
                "url": (
                    game["detail_url_prefix"] + item_id
                    if item_id
                    else game["official_url"]
                ),
            }
        )
    return sorted(updates, key=lambda u: u["date"], reverse=True)


SOURCE_FETCHERS = {

    "mihoyo_cms": fetch_mihoyo_cms_updates,
    "mihoyo": fetch_mihoyo_updates,
    "netease": fetch_netease_updates,
    "nsh": fetch_nsh_updates,
    "wjsj": fetch_wjsj_updates,
    "df": fetch_df_updates,
    "gp": fetch_gp_updates,
    "rocom": fetch_rocom_updates,
    "cmc": fetch_cmc_updates,
    "codm": fetch_codm_updates,
    "hyrz": fetch_hyrz_updates,
    "hypergryph": fetch_hypergryph_updates,
    "papegames": fetch_papegames_updates,
    "kuro": fetch_kuro_updates,
    "wanmei": fetch_wanmei_updates,
    "preternatural": fetch_preternatural_updates,
    "biligame": fetch_biligame_updates,
    "silverpalace": fetch_silverpalace_updates,
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
    # 同一 tab 下多家公司混排时（鹰角/库洛/叠纸）带上公司名，供前端在游戏名后
    # 以括号展示；其余游戏不带该字段。
    if game.get("company"):
        record["company"] = game["company"]

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
