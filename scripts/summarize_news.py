"""资讯源每日新闻总结生成脚本（3DMGame / 游侠网 / 游民星空 / GameLook）。

对每个来源读 data/<key>_news.json（10 天滚动窗口），按 published_at 的日期分组，
每天产出一段整体综述 + Top 15 每款游戏各自一段新闻总结，写入
data/<key>_digest.json。刻意不做「游戏名 + 条数」的清单：光有名字和条数看不出
当天到底发生了什么，一句话讲清动态才是这个 tab 存在的意义。

四个来源共用同一套流程，只有输入/输出文件名与来源名不同（见 SOURCES）。
命令行可传来源 key 只跑其中一部分，例如 `python scripts/summarize_news.py youxia`，
不传则四个都跑。


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
  直连、永久免费不限量，只限并发；本项目稳态每天 4 次调用（每个来源一次，日期
  维度靠 input_hash 复用），碰不到任何速率上限。
  模型生成结果还要过 verify_digest 的数字校验，任一数字/日期在输入里找不到就
  换下一家、全都失败则退回规则文本——模型编造具体数字是这类摘要任务最主要的
  翻车方式。

增量与写文件保护（与各采集脚本保持一致的约定）：
  - 每个日期算一个 input_hash，旧文件里 hash 相同的直接复用，不重复生成
  - 新闻文件解析出 0 条时拒绝写，避免用空结果覆盖已有总结
  - 只读 <key>_news.json，绝不回写它
"""
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import DEFAULT_HEADERS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("summarize_news")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def source_paths(key, name):
    """一个来源的输入输出：文件名规则与采集脚本一致，只差 news / digest 后缀。"""
    return {
        "key": key,
        "name": name,
        "news_path": os.path.join(DATA_DIR, f"{key}_news.json"),
        "output_path": os.path.join(DATA_DIR, f"{key}_digest.json"),
    }


# 四个资讯源都有 game_name 标注（采集侧统一打标），所以同一套聚簇逻辑通用。
SOURCES = [
    source_paths("3dmgame", "3DMGame"),
    source_paths("youxia", "游侠网"),
    source_paths("gamersky", "游民星空"),
    source_paths("gamelook", "GameLook"),
]


# 每日榜单长度：用户指定 Top 15
TOP_N = 15

# 综述里点名列举的游戏数：Top 15 全列进一段话会变成念榜单，只讲前几名，
# 其余交给下面各游戏的单独总结。
NARRATIVE_HEAD = 3

# 规则版单游戏总结的取材与长度：直接串标题，串三条足够看出当天在讲什么。
RULES_TITLES_PER_GAME = 3
RULES_SUMMARY_MAX = 160

# 送模型的输入规模上限。各站摘要在采集侧被硬截断（3DM 为 360 字符），单游戏取
# 标题 + 摘要仍可能上千字，因此按游戏和总量两级封顶，保证请求体可控。
# 单游戏 360 × 15 款仍在总量 6000 以内，保证 Top 15 都能进素材而不是被截在半路；
# 总量也要给备用的 ERNIE-3.5-8K 留出输出空间，不能再往上放。
MAX_CHARS_PER_GAME = 360
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

# 429/1305 是共享算力的瞬时限流，隔几秒重试就能过，不该直接掉到备用或规则文本。
# 实测同一个 key 打 glm-4.7-flash 大约三次里中一次，所以给到 6 次、每次多等 2 秒
# （最长 2+4+6+8+10=30 秒），单次运行一共约 30 个请求，等待总量仍在 CI 可接受范围。
LLM_MAX_ATTEMPTS = 6
LLM_RETRY_BACKOFF = 2
LLM_RETRY_MAX_WAIT = 10



# 统计键：与前端 GameNewsPanel.vue 的 statKey 保持同一套规则——去掉空格与
# 半/全角冒号后小写，让「黑神话：钟馗」「黑神话钟馗」「GTA 6」「GTA6」落到同
# 一个键上。刻意不做前缀合并：「黑神话」可能是《黑神话：悟空》也可能是别的作品，
# 并进去统计就失真了。
STAT_STRIP_RE = re.compile(r"[\s:：]")

# 数字校验用：抓出文本里所有连续数字串
DIGIT_RUN_RE = re.compile(r"\d+")

# 解析模型输出用：综述行前缀、游戏名与总结之间的分隔符、行首编号
OVERVIEW_PREFIX_RE = re.compile(r"^综述\s*[：:]\s*")
GAME_LINE_SEP_RE = re.compile(r"\s*[｜|]\s*")
LEADING_NUM_RE = re.compile(r"^\d+\s*[.、）)]\s*")


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


def build_rules_digest(source_name, date, day_items, clusters, untagged_count):
    """纯规则综述：所有数字都是算出来的，不存在编造，任何时候都可用。

    这条路径同时是模型路径的兜底，因此不允许依赖网络或外部状态。
    只点名前几款，剩下的不再罗列名字——每款游戏下面都有自己的总结，
    在综述里再报一遍名字纯属重复。
    """
    total = len(day_items)
    parts = [
        f"{format_date_cn(date)} {source_name} 共 {total} 条新闻，"
        f"涉及 {len(clusters)} 款游戏。"
    ]
    head = clusters[:NARRATIVE_HEAD]
    if head:
        listed = "、".join(f"《{c['name']}》（{c['count']} 条）" for c in head)
        parts.append(f"报道最集中的是{listed}。")

    if untagged_count:
        parts.append(f"另有 {untagged_count} 条未指向具体游戏的行业或平台资讯。")
    return "".join(parts)


def build_rules_game_summary(cluster):
    """规则版单游戏总结：串该游戏当天的代表性标题，不做改写。

    不改写是有意的——规则路径没有语言能力，硬拼出来的句子只会读着更别扭，
    原标题本身就是最准确、信息量最高的表述。
    """
    titles = []
    for item in cluster["items"][:RULES_TITLES_PER_GAME]:
        title = (item.get("title") or "").strip().rstrip("。；;")
        if title:
            titles.append(title)
    if not titles:
        return f"当天有 {cluster['count']} 条相关报道。"
    text = "；".join(titles)
    if len(text) > RULES_SUMMARY_MAX:
        text = text[:RULES_SUMMARY_MAX].rstrip("；") + "…"
    if cluster["count"] > len(titles):
        return f"{text}（当天共 {cluster['count']} 条）"
    return f"{text}。"


def build_model_input(source_name, date, clusters, total, untagged_count):
    """拼出送模型的素材文本，按游戏和总量两级封顶。

    只喂 Top 15 簇：全天 ~80 条原文即使被截断过也有两三万字符，小模型放不下，
    而且长尾游戏本来也不进当日榜，没有单独总结的必要。
    """
    lines = [
        f"日期：{date}",
        # 涉及游戏数也要写进素材：综述本该提这个数，但数字校验只认素材里出现过的
        # 数字，不给它就等于禁止模型说「涉及 N 款游戏」。
        f"当天 {source_name} 新闻总数：{total} 条，涉及游戏 {len(clusters)} 款，"
        f"其中未指向具体游戏 {untagged_count} 条。",
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


def verify_digest(text, source_text, min_len=20):
    """校验模型输出：出现的每个数字串都必须能在输入素材里原样找到。

    这类摘要任务最主要的翻车方式是编造具体数字——发售日期、销量、版本号。
    条数、日期、价格全部来自输入，所以"输出的数字必须是输入里出现过的"是一条
    足够强又不会误杀的约束。命中即整段丢弃、退回规则文本，不做局部修补：
    改一半的句子读起来更可疑。

    min_len 是"短到不像正经句子"的下限，按用途分档：综述要求 80~140 字，20
    以下必然是残句；单游戏总结本身就短，同一个下限会把合理的一句话也误杀。
    """
    if not text or len(text) < min_len:
        return False, "文本过短"
    allowed = set(DIGIT_RUN_RE.findall(source_text))
    for number in DIGIT_RUN_RE.findall(text):
        if number not in allowed:
            return False, f"输出里的数字 {number} 在输入素材中不存在"
    return True, ""


def extract_message_text(data):
    """从 chat/completions 响应里取正文，取不到就返回空串让调用方兜底。

    刻意只认 content：智谱的思考型模型会把推理过程放在 reasoning_content，那段是
    草稿而不是成品，直接拿去当总结会把「用户想要…」这类自言自语写到页面上。
    所以 content 为空时记一条日志退回上层，而不是拿推理过程凑数。
    """
    message = data["choices"][0]["message"]
    text = (message.get("content") or "").strip()
    if not text and message.get("reasoning_content"):
        logger.warning("模型只返回了推理过程、正文为空，按失败处理")
    return text


def call_llm(provider, prompt_input, system_prompt=None):
    """调用一组 provider 的 chat/completions，失败返回 None 交给调用方兜底。"""
    url = f"{provider['base_url']}/chat/completions"
    payload = {
        "model": provider["model"],
        "messages": [
            {
                "role": "system",
                "content": system_prompt or (
                    "你是游戏行业资讯编辑。根据素材写当日总结，严格按以下格式输出，"
                    "不要输出标题、前言、结语或 Markdown 标记：\n"
                    "第一行以「综述：」开头，用 80~140 字概括当天整体情况；\n"
                    "之后每款游戏各占一行，格式为「游戏名｜这款游戏当天的动态」，"
                    "游戏名与素材里的写法保持一致，顺序也和素材一致，每行 40~80 字，"
                    "讲清具体发生了什么（发售、更新、销量、争议等），"
                    "不要只重复标题也不要写成条数统计。\n"
                    "只允许使用素材里出现的事实与数字，素材没写的一律不写。"
                ),
            },
            {"role": "user", "content": prompt_input},
        ],
        "temperature": 0.2,
        # 综述 + 15 行单游戏总结，中文按 1 字≈1.5 token 估，1600 才够写完不被截断
        "max_tokens": 1600,
    }
    # 智谱的 glm-4.5/4.7 系列默认开思考，推理会吃光 max_tokens 让 content 空着返回，
    # 这个任务也不需要长链推理，所以显式关掉。只对智谱下发：这个字段不是通用参数，
    # 发给千帆有被当成非法入参拒掉的风险。
    if "bigmodel.cn" in provider["base_url"]:
        payload["thinking"] = {"type": "disabled"}
    headers = dict(DEFAULT_HEADERS)
    headers["Authorization"] = f"Bearer {provider['api_key']}"
    headers["Content-Type"] = "application/json"
    for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(
                url, json=payload, headers=headers, timeout=LLM_TIMEOUT
            )
            # 429 = 共享算力被占满，等一会儿再打同一个模型比直接换备用更划算
            if resp.status_code == 429 and attempt < LLM_MAX_ATTEMPTS:
                wait = min(LLM_RETRY_BACKOFF * attempt, LLM_RETRY_MAX_WAIT)
                logger.warning(
                    "%s模型 %s 被限流（429），%s 秒后重试（第 %s/%s 次）",
                    provider["label"],
                    provider["model"],
                    wait,
                    attempt,
                    LLM_MAX_ATTEMPTS,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return extract_message_text(resp.json())
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "%s模型 %s 调用失败：%s", provider["label"], provider["model"], exc
            )
            return None
    return None




def llm_enabled():
    """至少配齐一组 provider 才启用模型路径。"""
    return bool(LLM_PROVIDERS)


def parse_model_output(text):
    """把模型输出拆成（综述, {统计键: 单游戏总结}）。

    用行 + 分隔符而不是 JSON：备用的 ERNIE-3.5-8K 属于小模型，让它吐结构化 JSON
    的失败率明显高于吐纯文本，而这里的格式简单到解析根本不需要 JSON。
    """
    overview = ""
    summaries = {}
    for raw in (text or "").splitlines():
        line = LEADING_NUM_RE.sub("", raw.strip().lstrip("-•*# ").strip())
        if not line:
            continue
        if OVERVIEW_PREFIX_RE.match(line):
            overview = OVERVIEW_PREFIX_RE.sub("", line).strip()
            continue
        parts = GAME_LINE_SEP_RE.split(line, maxsplit=1)
        if len(parts) != 2:
            # 模型偶尔漏掉「综述：」前缀，此时把第一段散文当综述，别整天作废
            if not overview:
                overview = line
            continue
        name = parts[0].strip().strip("《》").strip()
        summary = parts[1].strip()
        key = stat_key(name)
        if key and summary:
            summaries[key] = summary
    return overview, summaries


def generate_digest(date, prompt_input):
    """按主用→备用顺序生成综述与各游戏总结，返回 (综述, {统计键: 总结})。

    两级校验粒度不同：综述没过数字校验就换下一家（整天的门面不能带假数字）；
    单个游戏的句子没过只丢它自己、由规则文本补位——为其中一句话把另外十几款
    游戏的可用总结全扔掉不划算。
    """
    for provider in LLM_PROVIDERS:
        raw = call_llm(provider, prompt_input)
        if not raw:
            continue
        overview, summaries = parse_model_output(raw)
        ok, reason = verify_digest(overview, prompt_input)
        if not ok:
            logger.warning(
                "%s %s模型 %s 综述未通过校验（%s）",
                date, provider["label"], provider["model"], reason,
            )
            continue
        kept = {}
        for key, summary in summaries.items():
            # 单游戏这句话本来就短，长度下限比综述放宽，只挡明显的残句
            good, why = verify_digest(summary, prompt_input, min_len=10)
            if good:
                kept[key] = summary
            else:
                logger.warning("%s 丢弃 %s 的单游戏总结（%s）", date, key, why)
        return overview, kept
    return None, {}


def build_day_entry(source_name, date, day_items):
    """产出某一天的总结条目：一段整体综述 + Top 15 每款游戏各自的新闻总结。"""
    clusters = build_clusters(day_items)
    untagged = sum(1 for item in day_items if not stat_key(item.get("game_name") or ""))
    total = len(day_items)

    rules_text = build_rules_digest(source_name, date, day_items, clusters, untagged)
    digest, digest_source = rules_text, "rules"
    model_summaries = {}

    if llm_enabled():
        prompt_input = build_model_input(source_name, date, clusters, total, untagged)
        overview, model_summaries = generate_digest(date, prompt_input)
        if overview:
            digest, digest_source = overview, "llm"
        else:
            logger.warning("%s 模型路径未产出可用文本，退回规则文本", date)

    game_digests = []
    for cluster in clusters[:TOP_N]:
        summary = model_summaries.get(stat_key(cluster["name"]))
        game_digests.append(
            {
                "name": cluster["name"],
                "count": cluster["count"],
                "summary": summary or build_rules_game_summary(cluster),
                "summary_source": "llm" if summary else "rules",
            }
        )

    return {
        "date": date,
        "article_count": total,
        "game_count": len(clusters),
        "untagged_count": untagged,
        "digest": digest,
        "digest_source": digest_source,
        "input_hash": day_input_hash(day_items),
        "game_digests": game_digests,
    }


def load_cached_entries(path):
    """读旧总结，返回 {日期: 条目}，只用于复用模型生成的结果。

    规则文本不进缓存：重算不花钱，而且改了模板后缓存会让页面上长期留着旧措辞。
    同理也要求带 game_digests——早期只有 top_games 的条目结构已经不兼容，
    复用会让页面上那天没有各游戏总结。
    """
    data = load_json(path)
    if not data:
        return {}
    return {
        entry["date"]: entry
        for entry in data.get("items", [])
        if entry.get("date")
        and entry.get("digest_source") == "llm"
        and entry.get("game_digests")
    }


def write_output(path, source_name, entries, window_days):
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_name,
        "window_days": window_days,
        "top_n": TOP_N,
        "items": entries,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("写入 %s（%d 天总结）", path, len(entries))


def run_source(source):
    """处理一个来源，返回 True 表示已写出总结文件。"""
    news = load_json(source["news_path"])
    items = (news or {}).get("items") or []
    if not items:
        logger.error(
            "%s 没有可用条目，跳过 %s 以避免覆盖已有总结",
            source["news_path"],
            source["name"],
        )
        return False

    cached = load_cached_entries(source["output_path"])
    buckets = group_by_date(items)
    logger.info(
        "%s：共 %d 条新闻、%d 个日期", source["name"], len(items), len(buckets)
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
        entries.append(build_day_entry(source["name"], date, day_items))

    logger.info(
        "%s 生成完成：新算 %d 天，复用 %d 天",
        source["name"],
        len(entries) - reused,
        reused,
    )
    write_output(
        source["output_path"], source["name"], entries, (news or {}).get("window_days")
    )
    return True


def main():
    # 允许只跑指定来源，便于本地单独调试某一站；不传参数就四个都跑。
    wanted = [arg.strip().lower() for arg in sys.argv[1:] if arg.strip()]
    targets = [s for s in SOURCES if not wanted or s["key"] in wanted]
    unknown = [key for key in wanted if key not in {s["key"] for s in SOURCES}]
    if unknown:
        logger.error("未知来源：%s，可选：%s",
                     "、".join(unknown), "、".join(s["key"] for s in SOURCES))
        return 1

    logger.info(
        "模型路径：%s",
        "、".join(f"{p['label']} {p['model']}" for p in LLM_PROVIDERS)
        or "未配置（走规则生成）",
    )

    # 一个来源失败（新闻文件缺失或为空）不影响其余来源，但整体以非 0 退出，
    # 让 Actions 的哨兵步骤能报出来。
    failed = [s["name"] for s in targets if not run_source(s)]
    if failed:
        logger.error("以下来源未生成总结：%s", "、".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())








