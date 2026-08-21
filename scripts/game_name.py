"""新闻条目游戏名提取的纯函数模块，被四个资讯来源的爬虫共用。

为什么以标题里的书名号为准，而不是信任来源自带的游戏标签：
  - 3DMGame 列表页 div.bq 的首个 a.a 标签并不总是游戏名，很多时候是频道名或
    平台名。实测现有 649 条新闻里有 124 条标签与标题中的游戏名不符，其中
    「游戏新闻」44 条、「Steam」8 条，直接当游戏名用会污染前端的 top 游戏统计。
  - 游侠网、游民星空、GameLook 三个来源的列表页/接口完全没有游戏标签字段，
    标题里的书名号是唯一可用的信号。
  因此统一策略：标题书名号优先，来源标签只在标题无书名号时作兜底，且兜底前要
  过 looks_like_game 的黑名单过滤。

由于提取只依赖标题（+ 可选标签），是纯函数，爬虫可以在「合并后的全部条目」上
统一执行一遍，窗口内从旧 JSON 继承下来的老条目也会顺带补上 game_name，
不需要额外的回填脚本。
"""
import logging
import re

logger = logging.getLogger("game_name")

# 标题里的游戏名标记：《...》 或 【...】，内容 1~40 字符。
# 用 alternation 而不是混合字符类，避免匹配到 《...】 这种不成对的组合；
# re.search 会返回位置最靠前的匹配，正好满足「多个书名号取第一个」的要求。
TITLE_NAME_PATTERN = re.compile(
    r"《([^《》]{1,40})》|【([^【】]{1,40})】"
)

# 游戏名长度上限：超过基本可以判定是把整句话或一段描述当成名字了
MAX_NAME_LENGTH = 40

# 斜杠别名截断的下限：两侧都达到这个长度才认为是「主名/别名」，
# 否则视为名字本身含斜杠（「宝可梦：风/波」）
MIN_ALIAS_LENGTH = 2

# 中日文字符，用于判断是否该把半角冒号转成全角
CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")


# 非游戏标签黑名单，只在「用来源标签兜底」这一步生效，不影响标题书名号的提取。
# 分两层，因为单一策略两头都会出错：
#   - 精确相等层：短且会出现在真实游戏名里的词。用包含式会误杀，例如 EA 之于
#     《EA SPORTS FC》、卡普空之于《漫画英雄VS卡普空》、迪士尼之于《迪士尼梦幻星谷》。
#   - 包含层：厂商全称、硬件品类、栏目类目这类词，真实游戏名里基本不会出现，
#     必须用包含式才拦得住「EA 电子艺界」「任天堂Switch主机」「TGA颁奖典礼」
#     这类带前后缀的变体（精确相等会全部漏出）。
NON_GAME_NAMES = {
    # 频道 / 栏目名
    "游戏新闻",
    "商务新闻严",
    "商务新闻",
    "业界新闻",
    "游戏资讯",
    "单机新闻",
    "手游新闻",
    "网游新闻",
    "游戏杂谈",
    # 平台 / 商店
    "Steam",
    "Epic Games",
    "Epic",
    "PlayStation",
    "Xbox",
    "Switch",
    "GOG",
    "TapTap",
    "PSN",
    "Netflix",

    # 硬件型号（整体相等才拦，避免 Xbox / PS 前缀的真实游戏名被误杀）
    "PS3",
    "PS4",
    "PS5",
    "PS5 Pro",
    "PSP",
    "PSV",
    "Xbox One",
    "Xbox Series X",
    "Xbox Series S",
    "Switch 2",
    "NS2",
    "Steam Deck",

    # 发行商 / 厂商 / 硬件厂商
    "索尼",
    "微软",
    "任天堂",
    "育碧",
    "EA",
    "动视暴雪",
    "暴雪",
    "腾讯",
    "网易",
    "米哈游",
    "卡普空",
    "世嘉",
    "万代",
    "华纳",
    "迪士尼",
    "英伟达",
    "AMD",
    "Intel",
    "小米",

    # 人名
    "小岛秀夫",
    "宫崎英高",
    # 媒体 / 泛内容品类
    "B站",
    "哔哩哔哩",
    "抖音",
    "漫画",
    "动画",
    "电影",
    "电视剧",
    "小说",
    # 赛事 / 平台运营方
    "TGA",
    "KK官方对战平台",
    "SNK冠军系列赛",
}

# 只要标签里出现这些词就判定为非游戏。挑选标准：真实游戏名里基本不会出现，
# 因此可以安全地用包含式匹配，把带前后缀的变体一并拦掉。
NON_GAME_KEYWORDS = (
    "新闻",
    "资讯",
    "杂谈",
    "加速器",
    "颁奖典礼",
    "电子艺界",
    "主机",
    "对战平台",
    "系列赛",
    "显卡",
    "处理器",
    "外设",
    "手柄",
    "发行商",
    "开发商",
    "影业",
    "有限公司",
)


def _has_cjk(text):
    """是否包含中日文字符，用来判断该不该用全角标点。"""
    return bool(CJK_PATTERN.search(text))


def _is_alias_part(part):
    """斜杠两侧是否像一个独立完整的别名。

    只看长度：单字符（含「宝可梦：风/波」的「波」）不算独立别名，
    这样「GTA6/侠盗猎车6」「Fate/Grand Order」照旧截断，
    「宝可梦：风/波」保持完整。
    """
    return len(part.strip()) >= MIN_ALIAS_LENGTH


def normalize_game_name(name):
    """归一化游戏名，让同名异形能落到同一个统计键上。

    处理内容：
      1. 去首尾空白，连续空白压成一个空格
      2. 含中日文的名字里，单个半角冒号 ':' 统一成全角 '：'，并去掉冒号两侧空格
         （「龙之剑:觉醒」/「龙之剑： 觉醒」同源）；'::' 是纯符号写法（A PLATiNA
         :: LAB）不动，纯拉丁名（TIC-TAC: Twelve o'clock）也不塞全角冒号
      3. 只在 '/' 两侧都像独立别名时截断，取第一段（「GTA6/侠盗猎车6」→「GTA6」）；
         右侧只有一个字的（「宝可梦：风/波」）属于名字本身，不截
    """
    if not name:
        return ""
    normalized = re.sub(r"\s+", " ", name.strip())
    if _has_cjk(normalized):
        # (?<!:) / (?!:) 保证只替换孤立的半角冒号，'::' 原样保留
        normalized = re.sub(r"(?<!:):(?!:)", "：", normalized)
        normalized = re.sub(r"\s*：\s*", "：", normalized)
    head, sep, tail = normalized.partition("/")
    if sep and _is_alias_part(head) and _is_alias_part(tail):
        normalized = head
    return normalized.strip()


def looks_like_game(name):
    """判断一个来源标签是否像游戏名（用于兜底前的过滤）。"""
    normalized = normalize_game_name(name)
    if not normalized or len(normalized) > MAX_NAME_LENGTH:
        return False
    lowered = normalized.casefold()
    if any(
        lowered == normalize_game_name(banned).casefold()
        for banned in NON_GAME_NAMES
    ):
        return False
    return all(keyword.casefold() not in lowered for keyword in NON_GAME_KEYWORDS)


def derive_game_name(title, tag=""):
    """从新闻标题里提取游戏名；标题无书名号时用来源自带的标签兜底。

    返回归一化后的游戏名，无法判定时返回 ''（调用方仍应写入空串保持字段齐整）。
    """
    match = TITLE_NAME_PATTERN.search(title or "")
    if match:
        # 两个捕获组分别对应 《》 与 【】，命中的那个不为 None
        candidate = normalize_game_name(match.group(1) or match.group(2))
        if candidate:
            return candidate

    if tag:
        if looks_like_game(tag):
            return normalize_game_name(tag)
        logger.debug("标签 %s 命中非游戏黑名单，不作为游戏名", tag)

    return ""
