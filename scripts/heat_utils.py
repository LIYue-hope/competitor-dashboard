"""热度计算纯函数：解析量级字符串、对数归一化、上周日期窗口。

不访问网络，也不依赖采集脚本，方便单测和被 summarize_week 复用。
"""
from datetime import date, datetime, timedelta, timezone
from math import log1p


BEIJING = timezone(timedelta(hours=8))

# 把「214万」「123.7万」「2390」这类展示字符串收成整数。
COUNT_SUFFIX_WAN = "\u4e07"


def parse_count(value):
    """把预约/关注等量级转成整数；无法解析时返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value < 0:
            return None
        return int(value)
    text = str(value).strip()
    if not text or text in ("\u6682\u65e0", "\u6682\u65e0\u6570\u636e", "-", "--"):
        return None
    text = text.replace(",", "").replace(" ", "")
    multiplier = 1.0
    if text.endswith(COUNT_SUFFIX_WAN):
        multiplier = 10000.0
        text = text[: -len(COUNT_SUFFIX_WAN)]
    try:
        number = float(text)
    except ValueError:
        return None
    if number < 0:
        return None
    return int(number * multiplier)


def log_norm(value, cap):
    """把非负计数压到 0~1。None/0 记 0；超过 cap 记 1。"""
    if value is None or value <= 0 or cap <= 0:
        return 0.0
    if value >= cap:
        return 1.0
    return log1p(value) / log1p(cap)


def last_week_range(today=None):
    """上一个自然周的周一到周日（北京时间），返回 (start, end) 含首尾。

    今天若是 2026-08-23（周日），返回 (2026-08-10, 2026-08-16)。
    注意资讯只保留约 10 天，窗口靠前的几天可能已经没有留存数据。
    """
    if today is None:
        today = datetime.now(BEIJING).date()
    elif isinstance(today, datetime):
        today = today.astimezone(BEIJING).date()
    start = today - timedelta(days=today.weekday() + 7)
    end = start + timedelta(days=6)
    return start, end


def in_range(date_str, start, end):
    """published_at / date 字段是否落在 [start, end]。"""
    parsed = parse_date(date_str)
    if parsed is None:
        return False
    return start <= parsed <= end


def parse_date(date_str):
    """从 'YYYY-MM-DD ...' 或 'YYYY-MM-DD' 取出 date；失败返回 None。"""
    if not date_str:
        return None
    text = str(date_str).strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def pick_display_name(variants):
    """展示名：出现次数最多，次数相同取更长的写法。"""
    if not variants:
        return ""
    return sorted(variants.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0][0]


def format_count_label(value):
    """整数转回展示标签：>=10000 用万。"""
    if value is None:
        return None
    if value >= 10000:
        wan = value / 10000.0
        if abs(wan - round(wan)) < 1e-6:
            return "%d%s" % (int(round(wan)), COUNT_SUFFIX_WAN)
        return ("%.1f%s" % (wan, COUNT_SUFFIX_WAN)).replace(".0" + COUNT_SUFFIX_WAN, COUNT_SUFFIX_WAN)
    return str(int(value))
