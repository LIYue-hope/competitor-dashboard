"""3DMGame 每日新闻总结生成脚本（试点，只处理一个来源）。

输入 data/3dmgame_news.json（10 天滚动窗口），按 published_at 的日期分组，
每天产出一段综述文字 + 当日游戏 Top 15 列表，写入 data/3dmgame_digest.json。

关于生成方式——为什么默认是规则生成：
  原计划是直接调 GitHub Models 的免费额度（Actions 里用 GITHUB_TOKEN 即可），
  但 GitHub Models 已于 2026-07-30 全量退役，playground / 模型目录 / 推理 API /
  BYOK 对所有客户都不再可用（github.blog/changelog/2026-07-30-github-models-is-now-retired），
  所以那条路已经不存在了。现在换成通用的 OpenAI 兼容调用入口，支持主用 + 备用
  两组配置，每组三个变量齐了才算可用，一组都没配就完整走规则生成：
    主用  DIGEST_LLM_BASE_URL / DIGEST_LLM_API_KEY / DIGEST_LLM_MODEL
    备用  DIGEST_LLM_FALLBACK_BASE_URL / DIGEST_LLM_FALLBACK_API_KEY
          DIGEST_LLM_FALLBACK_MODEL
  BASE_URL 形如 https://xxx/v1，不含 /chat/completions，由 call_llm 自行拼接。
  当前部署：主用智谱 GLM-4.7-Flash，备用百度千帆 ERNIE-3.5-8K，两家都是国内
  直连、永久免费不限量，只限并发；本项目稳态每天 1 次调用，碰不到任何速率上限。
  模型生成结果还要过 verify_digest 的数字校验，任一数字/日期在输入里找不到就
  换下一家、全都失败则退回规则文本——模型编造具体数字是这类摘要任务最主要的
  翻车方式。

增量与写文件保护（与各采集脚本保持一致的约定）：
  - 每个日期算一个 input_hash，旧文件里 hash 相同的直接复用，不重复生成
  - 新闻文件解析出 0 条时拒绝写，避免用空结果覆盖已有总结
  - 只读 3dmgame_news.json，绝不回写它
"""
import hashlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import DEFAULT_HEADERS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("summarize_3dmgame")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
NEWS_PATH = os.path.join(DATA_DIR, "3dmgame_news.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "3dmgame_digest.json")

SOURCE_NAME = "3DMGame"

# 每日榜单长度：用户指定 Top 15
TOP_N = 15

# 综述里点名列举的游戏数：Top 15 全列进一段话会变成念榜单，只讲前几名，
# 其余交给榜单区展示。
NARRATIVE_HEAD = 3

# 送模型的输入规模上限。3DM 摘要在采集侧被硬截断到 360 字符，单游戏取标题 +
# 摘要仍可能上千字，因此按游戏和总量两级封顶，保证请求体可控。
MAX_CHARS_PER_GAME = 420
MAX_INPUT_CHARS = 6000

# OpenAI 兼容接口的可选配置：主用一组、备用一组，缺任一项该组即视为没配。
def read_provider(prefix, label):
    base_url = os.environ.get(f"{prefix}BASE_URL", "").strip().rstrip("/")
    api_key = os.environ.get(f"{prefix}API_KEY", "").strip()
    model = os.environ.get(f"{prefix}MODEL", "").strip()
    if not (base_url and api_key and model):
        return None
    return {"label": label, "base_url": base_url, "api_key": api_key, "model": model}


# 列表顺序就是优先级：主用调不通（限流、超时、返回结构不对、输出没过数字校验）
# 才轮到备用。两家都不行就退回规则文本，页面永远有内容可显示。
LLM_PROVIDERS = [
    provider
    for provider in (
        read_provider("DIGEST_LLM_", "主用"),
        read_provider("DIGEST_LLM_FALLBACK_", "备用"),
    )
    if provider
]

LLM_TIMEOUT = 60

# 统计键：与前端 GameNewsPanel.vue 的 statKey 保持同一套规则——去掉空格与
# 半/全角冒号后小写，让「黑神话：钟馗」「黑神话钟馗」「GTA 6」「GTA6」落到同
# 一个键上。刻意不做前缀合并：「黑神话」可能是《黑神话：悟空》也可能是别的作品，
# 并进去统计就失真了。
STAT_STRIP_RE = re.compile(r"[\s:：]")

# 数字校验用：抓出文本里所有连续数字串
DIGIT_RUN_RE = re.compile(r"\d+")


def stat_key(name):
    """归一化统计键，规则与前端 statKey 一致。"""
    return STAT_STRIP_RE.sub("", name or "").lower()


def load_json(path):
    """读 JSON，文件不存在或损坏返回 None（调用方自行决定怎么降级）。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取失败：%s，原因：%s", path, exc)
        return None


def group_by_date(items):
    """按 published_at 的日期部分分组，返回 {日期: [条目]}。"""
    buckets = defaultdict(list)
    for item in items:
        date = (item.get("published_at") or "")[:10]
        if len(date) == 10:
            buckets[date].append(item)
    return buckets


def build_clusters(day_items):
    """把一天的条目按游戏聚成簇，按条数降序返回全部簇（不截断）。

    展示名取簇内出现次数最多的写法，次数相同取更长的（信息更全），
    与前端 topGames 的选名规则一致，避免两处显示不同的名字。
    """
    groups = {}
    for item in day_items:
        name = (item.get("game_name") or "").strip()
        key = stat_key(name)
        if not key:
            continue  # 无游戏指向的行业/平台资讯，单独计数不进榜
        group = groups.setdefault(key, {"variants": defaultdict(int), "items": []})
        group["variants"][name] += 1
        group["items"].append(item)

    clusters = []
    for group in groups.values():
        display = sorted(
            group["variants"].items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0])
        )[0][0]
        clusters.append(
            {"name": display, "count": len(group["items"]), "items": group["items"]}
        )
    clusters.sort(key=lambda c: (-c["count"], c["name"]))
    return clusters


def day_input_hash(day_items):
    """当天内容指纹，用于增量：内容没变就复用旧总结，不重复生成。

    用 url 集合而不是游戏名：《影之刃零》这类热门游戏天天有新稿，按名字做键
    的缓存永远不会失效，等于总结再也不更新。
    """
    urls = sorted((item.get("url") or "") for item in day_items)
    payload = "\n".join(urls)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def format_date_cn(date):
    """2026-08-21 -> 8月21日，去掉前导零更接近正常表述。"""
    try:
        parsed = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return date
    return f"{parsed.month}月{parsed.day}日"


def build_rules_digest(date, day_items, clusters, untagged_count):
    """纯规则综述：所有数字都是算出来的，不存在编造，任何时候都可用。

    这条路径同时是模型路径的兜底，因此不允许依赖网络或外部状态。
    """
    total = len(day_items)
    parts = [
        f"{format_date_cn(date)} {SOURCE_NAME} 共 {total} 条新闻，"
        f"涉及 {len(clusters)} 款游戏。"
    ]
    head = clusters[:NARRATIVE_HEAD]
    if head:
        listed = "、".join(f"《{c['name']}》（{c['count']} 条）" for c in head)
        parts.append(f"报道最集中的是{listed}。")
    rest = clusters[NARRATIVE_HEAD:TOP_N]
    if rest:
        names = "、".join(f"《{c['name']}》" for c in rest)
        parts.append(f"其余进入当日前 {min(len(clusters), TOP_N)} 的还有{names}。")

    if untagged_count:
        parts.append(f"另有 {untagged_count} 条未指向具体游戏的行业或平台资讯。")
    return "".join(parts)


def build_model_input(date, clusters, total, untagged_count):
    """拼出送模型的素材文本，按游戏和总量两级封顶。

    只喂 Top 15 簇：全天 ~80 条原文即使被截断过也有两三万字符，小模型放不下，
    而且长尾单条新闻对"当天全局综述"没有信息增量。
    """
    lines = [
        f"日期：{date}",
        f"当天 {SOURCE_NAME} 新闻总数：{total} 条，其中未指向具体游戏 {untagged_count} 条。",
        "按报道条数排序的游戏（含代表性标题与摘要）：",
    ]
    used = 0
    for rank, cluster in enumerate(clusters[:TOP_N], start=1):
        block = [f"{rank}. {cluster['name']}（{cluster['count']} 条）"]
        budget = MAX_CHARS_PER_GAME
        for item in cluster["items"]:
            text = (item.get("title") or "").strip()
            summary = (item.get("summary") or "").strip()
            if summary:
                text = f"{text} —— {summary}"
            if not text:
                continue
            text = text[:budget]
            block.append(f"   - {text}")
            budget -= len(text)
            if budget <= 0:
                break
        chunk = "\n".join(block)
        if used + len(chunk) > MAX_INPUT_CHARS:
            break
        lines.append(chunk)
        used += len(chunk)
    return "\n".join(lines)


def verify_digest(text, source_text):
    """校验模型输出：出现的每个数字串都必须能在输入素材里原样找到。

    这类摘要任务最主要的翻车方式是编造具体数字——发售日期、销量、版本号。
    条数、日期、价格全部来自输入，所以"输出的数字必须是输入里出现过的"是一条
    足够强又不会误杀的约束。命中即整段丢弃、退回规则文本，不做局部修补：
    改一半的句子读起来更可疑。
    """
    if not text or len(text) < 20:
        return False, "文本过短"
    allowed = set(DIGIT_RUN_RE.findall(source_text))
    for number in DIGIT_RUN_RE.findall(text):
        if number not in allowed:
            return False, f"输出里的数字 {number} 在输入素材中不存在"
    return True, ""


def call_llm(provider, prompt_input):
    """调用一组 provider 的 chat/completions，失败返回 None 交给调用方兜底。"""
    url = f"{provider['base_url']}/chat/completions"
    payload = {
        "model": provider["model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是游戏行业资讯编辑。根据给定素材写一段中文当日综述，"
                    "150~250 字，一整段不要分点。只允许使用素材里出现的事实与数字，"
                    "不确定的信息一律不写，不要输出标题、前言或结语。"
                ),
            },
            {"role": "user", "content": prompt_input},
        ],
        "temperature": 0.2,
        "max_tokens": 600,
    }
    headers = dict(DEFAULT_HEADERS)
    headers["Authorization"] = f"Bearer {provider['api_key']}"
    headers["Content-Type"] = "application/json"
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        logger.warning(
            "%s模型 %s 调用失败：%s", provider["label"], provider["model"], exc
        )
        return None


def llm_enabled():
    """至少配齐一组 provider 才启用模型路径。"""
    return bool(LLM_PROVIDERS)


def generate_narrative(date, prompt_input):
    """按主用→备用的顺序生成综述，返回通过数字校验的文本，都不行返回 None。

    校验不通过和调用失败同等对待，都继续换下一家：一段编造了数字的文本没有价值，
    换个模型重写比在原文上做局部修补可靠。
    """
    for provider in LLM_PROVIDERS:
        generated = call_llm(provider, prompt_input)
        if not generated:
            continue
        ok, reason = verify_digest(generated, prompt_input)
        if ok:
            return generated
        logger.warning(
            "%s %s模型 %s 输出未通过校验（%s）",
            date, provider["label"], provider["model"], reason,
        )
    return None


def build_day_entry(date, day_items):
    """产出某一天的总结条目：一段综述 + 当日 Top 15 榜单。"""
    clusters = build_clusters(day_items)
    untagged = sum(1 for item in day_items if not stat_key(item.get("game_name") or ""))
    total = len(day_items)

    rules_text = build_rules_digest(date, day_items, clusters, untagged)
    digest, digest_source = rules_text, "rules"

    if llm_enabled():
        prompt_input = build_model_input(date, clusters, total, untagged)
        generated = generate_narrative(date, prompt_input)
        if generated:
            digest, digest_source = generated, "llm"
        else:
            logger.warning("%s 模型路径未产出可用文本，退回规则文本", date)

    return {
        "date": date,
        "article_count": total,
        "game_count": len(clusters),
        "untagged_count": untagged,
        "digest": digest,
        "digest_source": digest_source,
        "input_hash": day_input_hash(day_items),
        "top_games": [
            {"name": c["name"], "count": c["count"]} for c in clusters[:TOP_N]
        ],
    }


def load_cached_entries(path):
    """读旧总结，返回 {日期: 条目}，只用于复用模型生成的结果。

    规则文本不进缓存：重算不花钱，而且改了模板后缓存会让页面上长期留着旧措辞。
    """
    data = load_json(path)
    if not data:
        return {}
    return {
        entry["date"]: entry
        for entry in data.get("items", [])
        if entry.get("date") and entry.get("digest_source") == "llm"
    }


def write_output(path, entries, window_days):
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_NAME,
        "window_days": window_days,
        "top_n": TOP_N,
        "items": entries,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("写入 %s（%d 天总结）", path, len(entries))


def main():
    news = load_json(NEWS_PATH)
    items = (news or {}).get("items") or []
    if not items:
        logger.error(
            "%s 没有可用条目，终止写入以避免覆盖已有总结", NEWS_PATH
        )
        return 1

    cached = load_cached_entries(OUTPUT_PATH)
    buckets = group_by_date(items)
    logger.info(
        "共 %d 条新闻、%d 个日期，模型路径：%s",
        len(items),
        len(buckets),
        "、".join(f"{p['label']} {p['model']}" for p in LLM_PROVIDERS)
        or "未配置（走规则生成）",
    )

    entries = []
    reused = 0
    for date in sorted(buckets, reverse=True):
        day_items = buckets[date]
        current_hash = day_input_hash(day_items)
        hit = cached.get(date)
        if hit and hit.get("input_hash") == current_hash:
            entries.append(hit)
            reused += 1
            continue
        entries.append(build_day_entry(date, day_items))

    logger.info("生成完成：新算 %d 天，复用 %d 天", len(entries) - reused, reused)
    write_output(OUTPUT_PATH, entries, (news or {}).get("window_days"))
    return 0


if __name__ == "__main__":
    sys.exit(main())








