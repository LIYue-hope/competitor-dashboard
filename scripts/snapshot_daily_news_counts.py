"""持久化各资讯站每日新增条数，供前端趋势图使用。

资讯原始文件只保留滚动窗口，不能由前端长期回算。本脚本在各新闻爬虫之后运行：
以文章发布日期聚合五个来源，将当天可见窗口回填/修正到 2026-09-01 起的独立历史文件，
此前日期不再因原始窗口滚动而丢失。重复运行是幂等的。
"""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "daily_news_history.json"
START_DATE = "2026-09-01"
SOURCES = (
    ("dm", "3DMGame", "3dmgame_news.json"),
    ("yx", "游侠网", "youxia_news.json"),
    ("gs", "游民星空", "gamersky_news.json"),
    ("gl", "GameLook", "gamelook_news.json"),
    ("gr", "游资网", "gameres_news.json"),
)


def read_json(path):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def now_beijing():
    """Return Beijing time even in minimal Python installs without tzdata."""
    try:
        zone = ZoneInfo("Asia/Shanghai")
    except Exception:
        zone = timezone(timedelta(hours=8))
    return datetime.now(zone)


def source_counts(filename):
    """Return a source's visible counts, or ``None`` when its input is unusable.

    An absent or malformed crawler output does not mean the source had zero
    articles.  An empty ``items`` list, however, is a valid successful read
    and is intentionally returned as an empty Counter so today's zero can be
    recorded. Keeping that distinction prevents a transient crawler failure
    from erasing already persisted trend data.
    """
    counts = Counter()
    payload = read_json(DATA / filename)
    items = payload.get("items") if isinstance(payload, dict) else None
    # 空列表是一次成功读取且确实没有资讯；只有缺失/损坏的结构才算来源不可用。
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        date = str(item.get("published_at") or "")[:10]
        if date >= START_DATE:
            counts[date] += 1
    return counts


def main():
    previous = read_json(OUTPUT)
    if not isinstance(previous, dict):
        previous = {}
    days = {entry.get("date"): dict(entry.get("counts") or {}) for entry in previous.get("days", []) if entry.get("date") >= START_DATE}
    all_counts = {key: source_counts(filename) for key, _label, filename in SOURCES}
    available_counts = [counts for counts in all_counts.values() if counts is not None]
    visible_dates = set().union(*(counts.keys() for counts in available_counts))

    # 仅回写仍在各源滚动窗口内可见的日期；更早日期保留先前的每日快照。
    for date in visible_dates:
        row = days.setdefault(date, {})
        for key, _label, _filename in SOURCES:
            counts = all_counts[key]
            if counts is not None:
                row[key] = counts[date]

    today = now_beijing().date().isoformat()
    if today >= START_DATE and available_counts:
        # 即使所有可用站点当天均无新文章，也要留下这一天，曲线才是连续的每日记录。
        # 不可用来源不写入 0：缺失键表示“本次没有可信读数”，与真实的 0 条区分。
        row = days.setdefault(today, {})
        for key, _label, _filename in SOURCES:
            counts = all_counts[key]
            if counts is not None:
                row[key] = counts[today]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_date": START_DATE,
        "sources": [{"key": key, "label": label} for key, label, _filename in SOURCES],
        "days": [
            # 不补齐缺失来源。前端会将缺失值显示为暂无数据而非伪造的 0 条。
            {"date": date, "counts": {
                key: int(days[date][key])
                for key, _label, _filename in SOURCES
                if key in days[date]
            }}
            for date in sorted(days)
        ],
    }
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"wrote {OUTPUT}: {len(output['days'])} days")


if __name__ == "__main__":
    main()
