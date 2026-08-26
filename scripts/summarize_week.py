"""上周游戏总结：跨源聚合热度榜 + LLM 综述 + 热点消息推荐。

一期用已有资讯条数、跨源覆盖、预约、官方动态、评测评论；
二期叠 TapTap 关注/评价/讨论 与榜单名次。缺测维度记 0，不倒扣。

社区维度算「窗口内新增」而不是历史存量：每次运行把 TapTap 存量拍进
community_history.json，评分时用窗口内最后一张快照减窗口开始前最后一张，
拿不到基线就记 0。

窗口：北京时间「上一个自然周的周一到周日」。
"""
import hashlib
import json
import logging
import os
import re
import sys

from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from heat_utils import (  # noqa: E402
    BEIJING,
    format_count_label,
    in_range,
    last_week_range,
    log_norm,
    parse_count,
    pick_display_name,
)
from game_name import derive_game_name  # noqa: E402
from summarize_news import (  # noqa: E402
    DATA_DIR,
    call_llm,
    format_date_cn,
    llm_enabled,
    load_json,
    stat_key,
    verify_digest,
)

logger = logging.getLogger("summarize_week")

NEWS_SOURCES = [
    ("3dmgame", "3DMGame"),
    ("youxia", "\u6e38\u4fa0\u7f51"),
    ("gamersky", "\u6e38\u6c11\u661f\u7a7a"),
    ("gamelook", "GameLook"),
    ("gameres", "\u6e38\u8d44\u7f51"),
]
REVIEW_KEYS = ("3dmgame", "youxia", "gamersky")

TOP_N = 10
NEWS_PER_GAME = 2
OUTPUT_NAME = "weekly_digest.json"

# 热度权重：媒体 30% / 跨源 15% / 预约 18% / 社区 15% / 榜单 12% / 官方 7% / 评测 3%
W_MEDIA = 0.30
W_COVERAGE = 0.15
W_RESERVE = 0.18
W_COMMUNITY = 0.15
W_RANK = 0.12
W_OFFICIAL = 0.07
W_REVIEW = 0.03

# 一周内单款游戏的资讯条数上限：超过即视为满格（四源合计，头部游戏可达上百条）
MEDIA_CAP = 200

# 社区看的是「周内新增」，量级比存量小两个数量级，满格单独给一档
COMMUNITY_CAP = 100000

# TapTap 存量快照：内部字段名 -> 采集字段名
COMMUNITY_FIELDS = (
    ("follow", "follow_count"),
    ("review", "review_count"),
    ("discussion", "discussion_count"),
)
COMMUNITY_HISTORY_NAME = "community_history.json"
# 快照留半年多，够跨周做差，也不至于把文件撑大
HISTORY_KEEP_DAYS = 200



EVENT_HINTS = (
    "\u53d1\u552e",
    "\u6d4b\u8bd5",
    "\u9500\u91cf",
    "\u9884\u7ea6",
    "\u66f4\u65b0",
    "\u6cc4\u9732",
    "\u516c\u6d4b",
    "\u4e0a\u7ebf",
    "\u4e89\u8bae",
    "\u5f00\u670d",
    "\u767b\u9646",
    "\u4e0a\u5e02",
)

WEEKLY_SYSTEM_PROMPT = (
    "你是游戏行业资讯编辑。根据素材写上周综合总结，只输出一段连续正文，"
    "不要标题、不要前言结语、不要分点或分行、不要 Markdown 标记：\n"
    "用 500~600 字把上周整体情况和热度榜上各款游戏的关键动态写在一起，"
    "热度榜里的游戏尽量都提到，提到游戏时用《》包裹，讲清具体发生了什么"
    "（发售、测试、销量、泄露、争议、版本更新等），不要写成条数统计，也不要逐款游戏各写一段。\n"
    "只允许使用素材里出现的事实与数字，素材没写的一律不写。"
)

# 「综述：」这类前缀是给模型对齐格式用的，落到页面上就是噪声。
OVERVIEW_PREFIX_RE = re.compile(r"^(综述|总结|概述)\s*[:：]\s*")



def _empty_bucket():
    return {
        "variants": defaultdict(int),
        "articles": [],
        "sources": set(),
        "reservation": None,
        "follow": None,
        # 窗口内新增的社区数据（关注/评价/讨论），拿不到基线时保持 None
        "community_delta": None,
        "best_rank": None,
        "rank_lists": set(),
        "official_count": 0,
        "review_articles": 0,
        "comment_sum": 0,
    }


def _max_count(old, new):
    if new is None:
        return old
    if old is None:
        return new
    return max(old, new)


def _min_rank(old, new):
    if new is None:
        return old
    if old is None:
        return new
    return min(old, new)


def load_news_articles(data_dir, start, end):
    articles = []
    for key, label in NEWS_SOURCES:
        payload = load_json(os.path.join(data_dir, "%s_news.json" % key)) or {}
        for item in payload.get("items") or []:
            if not in_range(item.get("published_at"), start, end):
                continue
            articles.append(
                {
                    "source_key": key,
                    "source": label,
                    "title": (item.get("title") or "").strip(),
                    "url": item.get("url") or "",
                    "game_name": (item.get("game_name") or "").strip(),
                    "published_at": item.get("published_at") or "",
                    "summary": (item.get("summary") or "").strip(),
                }
            )
    return articles


def merge_reservation(bucket, raw):
    parsed = parse_count(raw)
    bucket["reservation"] = _max_count(bucket["reservation"], parsed)


def ingest_upcoming(data_dir, buckets):
    taptap = load_json(os.path.join(data_dir, "taptap_upcoming.json")) or []
    if isinstance(taptap, dict):
        taptap = taptap.get("items") or []
    for item in taptap:
        name = (item.get("game_name") or "").strip()
        key = stat_key(name)
        if not key:
            continue
        bucket = buckets.setdefault(key, _empty_bucket())
        bucket["variants"][name] += 1
        merge_reservation(bucket, item.get("reservation_count"))
        # 关注存量只当入榜门槛用；打分看的是 community_delta（周内新增）
        bucket["follow"] = _max_count(bucket["follow"], parse_count(item.get("follow_count")))


    haoyou = load_json(os.path.join(data_dir, "haoyoukuaibao_upcoming.json")) or {}
    for day in haoyou.get("days") or []:
        for item in day.get("games") or []:
            name = (item.get("game_name") or "").strip()
            key = stat_key(name)
            if not key:
                continue
            bucket = buckets.setdefault(key, _empty_bucket())
            bucket["variants"][name] += 1
            merge_reservation(bucket, item.get("reservation_count"))


def community_snapshot(data_dir):
    """把 TapTap 当前的关注/评价/讨论存量拍成一张快照。"""
    taptap = load_json(os.path.join(data_dir, "taptap_upcoming.json")) or []
    if isinstance(taptap, dict):
        taptap = taptap.get("items") or []
    games = {}
    for item in taptap:
        key = stat_key((item.get("game_name") or "").strip())
        if not key:
            continue
        row = {}
        for field, source in COMMUNITY_FIELDS:
            value = parse_count(item.get(source))
            if value is not None:
                row[field] = value
        if row:
            games[key] = row
    return games


def update_community_history(data_dir, snapshot, today=None):
    """按天累积快照，同一天重复跑覆盖当天那条；空快照不写，避免污染基线。"""
    if not snapshot:
        return None
    day = today
    if day is None:
        day = datetime.now(BEIJING).date()
    elif isinstance(day, datetime):
        day = day.astimezone(BEIJING).date()
    day = day.isoformat()
    path = os.path.join(data_dir, COMMUNITY_HISTORY_NAME)
    history = load_json(path) or {}
    snapshots = [
        item for item in (history.get("snapshots") or []) if item.get("date") != day
    ]
    snapshots.append({"date": day, "games": snapshot})
    snapshots.sort(key=lambda item: item.get("date") or "")
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "snapshots": snapshots[-HISTORY_KEEP_DAYS:],
    }
    os.makedirs(data_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return payload


def community_deltas(history, start, end):
    """窗口内最后一张快照 - 窗口开始前最后一张快照，得到「本周新增」。

    没有窗口前的基线（比如刚上线只攒了一周快照）就返回空，让社区维度记 0，
    而不是把历史存量当成本周增量。
    """
    snapshots = sorted(
        (history or {}).get("snapshots") or [], key=lambda item: item.get("date") or ""
    )
    base = None
    latest = None
    for snap in snapshots:
        day = snap.get("date") or ""
        if day < start.isoformat():
            base = snap
        elif day <= end.isoformat():
            latest = snap
    if not base or not latest:
        return {}

    deltas = {}
    base_games = base.get("games") or {}
    for key, now_row in (latest.get("games") or {}).items():
        base_row = base_games.get(key)
        if not base_row:
            continue
        row = {}
        for field, _source in COMMUNITY_FIELDS:
            if field in now_row and field in base_row:
                row[field] = max(0, now_row[field] - base_row[field])
        if row:
            deltas[key] = row
    return deltas


def ingest_community(data_dir, start, end, buckets):
    history = load_json(os.path.join(data_dir, COMMUNITY_HISTORY_NAME)) or {}
    deltas = community_deltas(history, start, end)
    for key, row in deltas.items():
        bucket = buckets.get(key)
        if bucket is not None:
            bucket["community_delta"] = row


def ingest_hot_games(data_dir, start, end, buckets):
    payload = load_json(os.path.join(data_dir, "hot_games_dynamics.json")) or {}
    for publisher in payload.get("publishers") or []:
        for game in publisher.get("games") or []:
            name = (game.get("game_name") or "").strip()
            key = stat_key(name)
            if not key:
                continue
            count = 0
            for update in game.get("updates") or []:
                if in_range(update.get("date"), start, end):
                    count += 1
            if count == 0 and not buckets.get(key):
                continue
            bucket = buckets.setdefault(key, _empty_bucket())
            if name:
                bucket["variants"][name] += 1
            bucket["official_count"] += count


def ingest_reviews(data_dir, start, end, buckets):
    for key in REVIEW_KEYS:
        payload = load_json(os.path.join(data_dir, "%s_reviews.json" % key)) or {}
        for item in payload.get("items") or []:
            if not in_range(item.get("published_at"), start, end):
                continue
            name = (item.get("game_name") or "").strip()
            if not name:
                name = (derive_game_name(item.get("title") or "") or "").strip()
            # 评测经常没打 game_name，尝试从标题里已有标注走；没有就跳过，避免污染榜单
            sk = stat_key(name)
            if not sk:
                continue
            bucket = buckets.setdefault(sk, _empty_bucket())
            bucket["variants"][name] += 1
            bucket["review_articles"] += 1
            comments = item.get("comment_count")
            if isinstance(comments, int) and comments > 0:
                bucket["comment_sum"] += comments


def ingest_ranks(data_dir, buckets):
    payload = load_json(os.path.join(data_dir, "taptap_rank.json")) or {}
    lists = payload.get("lists") or {}
    for list_type, rows in lists.items():
        for row in rows or []:
            name = (row.get("game_name") or "").strip()
            key = stat_key(name)
            if not key:
                continue
            rank = row.get("rank")
            try:
                rank = int(rank)
            except (TypeError, ValueError):
                continue
            bucket = buckets.setdefault(key, _empty_bucket())
            bucket["variants"][name] += 1
            bucket["best_rank"] = _min_rank(bucket["best_rank"], rank)
            bucket["rank_lists"].add(list_type)


def ingest_news(articles, buckets):
    for item in articles:
        name = item["game_name"]
        key = stat_key(name)
        if not key:
            continue
        bucket = buckets.setdefault(key, _empty_bucket())
        bucket["variants"][name] += 1
        bucket["articles"].append(item)
        bucket["sources"].add(item["source_key"])


def rank_score(best_rank):
    if not best_rank or best_rank > 50:
        return 0.0
    return (51 - best_rank) / 50.0


def qualifies(bucket):
    media = len(bucket["articles"])
    coverage = len(bucket["sources"])
    reservation = bucket["reservation"] or 0
    follow = bucket["follow"] or 0
    best = bucket["best_rank"]
    return (
        media >= 3
        or coverage >= 2
        or reservation >= 10000
        or follow >= 10000
        or (best is not None and best <= 20)
    )


def heat_breakdown(bucket):
    media = len(bucket["articles"])
    coverage = len(bucket["sources"])
    reservation = bucket["reservation"]
    # 社区只认窗口内新增，历史存量不参与打分
    community = sum((bucket["community_delta"] or {}).values())
    official = bucket["official_count"]
    review_signal = bucket["comment_sum"] + bucket["review_articles"]
    parts = {
        "media": log_norm(media, MEDIA_CAP),
        "coverage": coverage / 4.0,
        "reservation": log_norm(reservation, 2000000),
        "community": log_norm(community, COMMUNITY_CAP),
        "rank": rank_score(bucket["best_rank"]),
        "official": log_norm(official, 20),
        "review": log_norm(review_signal, 50),
    }
    total = (
        W_MEDIA * parts["media"]
        + W_COVERAGE * parts["coverage"]
        + W_RESERVE * parts["reservation"]
        + W_COMMUNITY * parts["community"]
        + W_RANK * parts["rank"]
        + W_OFFICIAL * parts["official"]
        + W_REVIEW * parts["review"]
    )
    return total, parts


def collect_games(data_dir, start, end):
    articles = load_news_articles(data_dir, start, end)
    buckets = {}
    ingest_news(articles, buckets)
    ingest_upcoming(data_dir, buckets)
    ingest_community(data_dir, start, end, buckets)
    ingest_hot_games(data_dir, start, end, buckets)
    ingest_reviews(data_dir, start, end, buckets)
    ingest_ranks(data_dir, buckets)

    ranked = []
    for key, bucket in buckets.items():
        if not qualifies(bucket) and len(bucket["articles"]) == 0:
            continue
        if not qualifies(bucket):
            continue
        name = pick_display_name(bucket["variants"])
        score, parts = heat_breakdown(bucket)
        ranked.append(
            {
                "key": key,
                "name": name,
                "heat": score,
                "parts": parts,
                "bucket": bucket,
            }
        )
    ranked.sort(key=lambda row: (-row["heat"], -len(row["bucket"]["articles"]), row["name"]))
    return articles, ranked


def pick_game_news(row, limit=NEWS_PER_GAME):
    """挑该游戏本周的代表资讯，直接挂在热度榜行上（优先带事件关键词、优先新）。"""
    articles = [item for item in row["bucket"]["articles"] if item.get("url")]
    hinted = [
        item
        for item in articles
        if any(hint in (item.get("title") or "") for hint in EVENT_HINTS)
    ]
    pool = sorted(
        hinted or articles, key=lambda item: item.get("published_at") or "", reverse=True
    )
    news = []
    used_urls = set()
    for item in pool:
        if len(news) >= limit:
            break
        if item["url"] in used_urls:
            continue
        used_urls.add(item["url"])
        news.append(
            {
                "title": item.get("title") or "",
                "url": item["url"],
                "source": item.get("source") or "",
                "published_at": (item.get("published_at") or "")[:10],
            }
        )
    return news


def _headline(row):
    """取该游戏本周的一条代表标题，优先带事件关键词的。"""
    articles = row["bucket"]["articles"]
    hinted = [
        item
        for item in articles
        if any(hint in (item.get("title") or "") for hint in EVENT_HINTS)
    ]
    for item in (hinted or articles):
        title = (item.get("title") or "").strip().rstrip("。；;")
        if title:
            return title[:40]
    return ""


def rules_overview(start, end, articles, ranked):
    untagged = sum(1 for item in articles if not stat_key(item.get("game_name")))
    head = ranked[:3]
    named = "\u3001".join(
        "\u300a%s\u300b\uff08%d \u6761\uff09" % (row["name"], len(row["bucket"]["articles"]))
        for row in head
    )
    text = "%d\u6708%d\u65e5\u2013%d\u6708%d\u65e5\u56db\u6e90\u5171 %d \u6761\u65b0\u95fb\uff0c\u6d89\u53ca %d \u6b3e\u6e38\u620f\u3002" % (
        start.month,
        start.day,
        end.month,
        end.day,
        len(articles),
        len(ranked),
    )
    if named:
        text += "\u62a5\u9053\u4e0e\u70ed\u5ea6\u6700\u96c6\u4e2d\u7684\u662f%s\u3002" % named
        # 综合总结里带上头部游戏各自的一条代表事件，避免通篇只有条数
        events = []
        for row in head:
            headline = _headline(row)
            if not headline:
                continue
            # 标题本身多半已经带了《游戏名》，再补前缀就会重复
            if row["name"] in headline:
                events.append(headline)
            else:
                events.append("\u300a%s\u300b%s" % (row["name"], headline))
        if events:
            text += "\u5176\u4e2d\uff1a%s\u3002" % "\uff1b".join(events)
    if untagged:
        text += "\u53e6\u6709 %d \u6761\u672a\u6307\u5411\u5177\u4f53\u6e38\u620f\u7684\u884c\u4e1a\u8d44\u8baf\u3002" % untagged
    return text


def build_model_input(start, end, articles, ranked):
    untagged = sum(1 for item in articles if not stat_key(item.get("game_name")))
    lines = [
        "\u5468\u671f\uff1a%s\uff08%s\uff09 \u81f3 %s\uff08%s\uff09"
        % (
            start.isoformat(),
            format_date_cn(start.isoformat()),
            end.isoformat(),
            format_date_cn(end.isoformat()),
        ),
        "\u56db\u6e90\u65b0\u95fb\u603b\u6570\uff1a%d \u6761\uff0c\u6d89\u53ca\u6e38\u620f %d \u6b3e\uff0c\u672a\u6307\u5411\u5177\u4f53\u6e38\u620f %d \u6761\u3002"
        % (len(articles), len(ranked), untagged),
        "\u6309\u7efc\u5408\u70ed\u5ea6\u6392\u5e8f\u7684\u6e38\u620f\uff08\u542b\u6761\u6570/\u6765\u6e90/\u9884\u7ea6/\u699c\u5355\u4e0e\u4ee3\u8868\u6807\u9898\uff09\uff1a",
    ]
    for index, row in enumerate(ranked[:TOP_N], start=1):
        bucket = row["bucket"]
        reserve = format_count_label(bucket["reservation"]) or "\u65e0"
        rank_label = str(bucket["best_rank"]) if bucket["best_rank"] else "\u65e0"
        lines.append(
            "%d. %s\uff08%d \u6761\uff0c%d \u4e2a\u8d44\u8baf\u6e90\uff0c\u9884\u7ea6 %s\uff0c\u699c\u5355 %s\uff09"
            % (index, row["name"], len(bucket["articles"]), len(bucket["sources"]), reserve, rank_label)
        )
        for item in bucket["articles"][:5]:
            title = (item.get("title") or "").strip()
            if title:
                lines.append("   - %s" % title[:120])
    return "\n".join(lines)


def clean_weekly_text(raw):
    """模型偶尔会带标题、分点或 Markdown 记号，统一压成一段正文。"""
    if not raw:
        return ""
    lines = []
    for line in raw.splitlines():
        line = line.strip().lstrip("#").strip()
        line = re.sub(r"^[-*\u2022]\s*", "", line)
        line = re.sub(r"^\d+[.\u3001)]\s*", "", line)
        line = line.replace("**", "")
        line = OVERVIEW_PREFIX_RE.sub("", line).strip()
        if line:
            lines.append(line)
    return "".join(lines)


def generate_weekly_text(prompt_input):
    if not llm_enabled():
        return None
    from summarize_news import LLM_PROVIDERS

    for provider in LLM_PROVIDERS:
        raw = call_llm(provider, prompt_input, system_prompt=WEEKLY_SYSTEM_PROMPT)
        if not raw:
            continue
        overview = clean_weekly_text(raw)
        ok, reason = verify_digest(overview, prompt_input)
        if not ok:
            logger.warning(
                "%s %s \u7efc\u8ff0\u672a\u901a\u8fc7\u6821\u9a8c\uff08%s\uff09",
                provider["label"],
                provider["model"],
                reason,
            )
            continue
        return overview
    return None


def week_input_hash(articles):
    urls = sorted(item.get("url") or "" for item in articles)
    payload = "\n".join(urls)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def serialize_entry(rank, row):
    bucket = row["bucket"]
    delta = bucket["community_delta"] or {}
    return {
        "rank": rank,
        "name": row["name"],
        "heat_score": round(row["heat"] * 100, 1),
        "media_count": len(bucket["articles"]),
        "source_count": len(bucket["sources"]),
        "reservation_label": format_count_label(bucket["reservation"]),
        "follow_delta_label": format_count_label(delta.get("follow")),
        "best_rank": bucket["best_rank"],
        "rank_lists": sorted(bucket["rank_lists"]),
        "official_count": bucket["official_count"],
        "news": pick_game_news(row),
    }


def heat_formula_note():
    """页面小字用：把权重口径直接从常量拼出来，避免前后端各写一份。"""
    return (
        "\u70ed\u5ea6 = \u8d44\u8baf\u91cf %d%% + \u8de8\u6e90\u8986\u76d6 %d%% + \u9884\u7ea6\u91cf %d%% "
        "+ \u793e\u533a\uff08\u5468\u5185\u65b0\u589e\u5173\u6ce8/\u8bc4\u4ef7/\u8ba8\u8bba\uff09%d%% + TapTap \u699c\u5355\u540d\u6b21 %d%% "
        "+ \u5b98\u65b9\u52a8\u6001 %d%% + \u8bc4\u6d4b\u8ba8\u8bba %d%%\uff1b"
        "\u5404\u9879\u5148\u5bf9\u6570\u5f52\u4e00\uff08\u8d44\u8baf\u6ee1\u683c %d \u6761\uff09\uff0c"
        "\u7f3a\u6d4b\u7684\u7ef4\u5ea6\u8ba1 0\u3001\u4e0d\u5012\u6263\uff0c\u6ee1\u5206 100\u3002"
    ) % (
        round(W_MEDIA * 100),
        round(W_COVERAGE * 100),
        round(W_RESERVE * 100),
        round(W_COMMUNITY * 100),
        round(W_RANK * 100),
        round(W_OFFICIAL * 100),
        round(W_REVIEW * 100),
        MEDIA_CAP,
    )


def build_payload(start, end, articles, ranked, data_dir=DATA_DIR):
    top = ranked[:TOP_N]
    prompt_input = build_model_input(start, end, articles, ranked)
    overview = generate_weekly_text(prompt_input)
    digest_source = "llm" if overview else "rules"
    if not overview:
        overview = rules_overview(start, end, articles, ranked)

    ranking_rows = [serialize_entry(index, row) for index, row in enumerate(top, start=1)]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "article_count": len(articles),
        "game_count": len(ranked),
        "digest": overview,
        "digest_source": digest_source,
        "heat_formula": heat_formula_note(),
        "input_hash": week_input_hash(articles),
        "hot_ranking": ranking_rows,
    }


def write_output(path, payload):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    logger.info("\u5199\u5165 %s\uff08%d \u6b3e\u6e38\u620f\uff09", path, len(payload.get("hot_ranking") or []))


def run(data_dir=None, today=None):
    data_dir = data_dir or DATA_DIR
    start, end = last_week_range(today)
    # 先把今天的社区存量落进历史，再算窗口增量：跨周做差要靠这条链攒基线
    update_community_history(data_dir, community_snapshot(data_dir), today=today)
    articles, ranked = collect_games(data_dir, start, end)
    output_path = os.path.join(data_dir, OUTPUT_NAME)
    if not articles:
        logger.error("\u7a97\u53e3\u5185\u6ca1\u6709\u65b0\u95fb\uff0c\u8df3\u8fc7\u5199\u5165\u4ee5\u907f\u514d\u8986\u76d6\u5df2\u6709\u5468\u62a5")
        return False

    current_hash = week_input_hash(articles)
    old = load_json(output_path)
    if (
        old
        and old.get("input_hash") == current_hash
        and old.get("digest_source") == "llm"
        and old.get("hot_ranking")
        and old.get("week_start") == start.isoformat()
    ):
        logger.info("\u5468\u62a5 hash \u672a\u53d8\uff0c\u590d\u7528\u65e7\u7ed3\u679c")
        return True

    payload = build_payload(start, end, articles, ranked, data_dir=data_dir)
    write_output(output_path, payload)
    return True


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger.info(
        "\u6a21\u578b\u8def\u5f84\uff1a%s",
        "\u5df2\u914d\u7f6e" if llm_enabled() else "\u672a\u914d\u7f6e\uff08\u8d70\u89c4\u5219\u751f\u6210\uff09",
    )
    ok = run()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
