"""采集 TapTap 热门 / 预约 / 新品榜，写入 data/taptap_rank.json。

榜页是前端渲染，HTML 里不一定有完整列表。这里先走 webapiv2，解析失败
再退回 HTML。任一榜单都解析不到时拒绝覆盖旧文件。

接口只认 type_name=hot/reserve/sell/new（played、download 会 400），
而且硬限 limit=10，所以名次要靠 from 翻页拼出来。
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import fetch_html, fetch_json  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawl_taptap_rank")

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "taptap_rank.json"
)

X_UA = (
    "V=1&PN=WebApp&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=PC"
    "&DS=Android&UID=0&OS=Windows&CH=website"
)

# list_type -> (接口 type_name, 页面路径候选)
# 榜单口径以接口返回的 title 为准：hot=热门榜、reserve=预约榜、new=新品榜。
# 接口没有「热玩榜/下载榜」这两个口径，别再往里塞，会 400 然后静默退化成
# 三个榜抓到同一份数据。
LIST_SPECS = {
    "hot": {"type_name": "hot", "paths": ("/top/hot",)},
    "reserve": {"type_name": "reserve", "paths": ("/top/reserve",)},
    "new": {"type_name": "new", "paths": ("/top/new",)},
}

APP_HREF_RE = re.compile(r"/app/(\d+)")
RANK_LIMIT = 50
API_URL = "https://www.taptap.cn/webapiv2/app-top/v2/hits"
# 接口不接受更大的 limit（limit=50 直接 400），只能一页 10 条往后翻
API_PAGE_SIZE = 10


def _app_name(node):
    if not isinstance(node, dict):
        return "", ""
    app = node.get("app") if isinstance(node.get("app"), dict) else node
    app_id = app.get("id") or app.get("app_id") or node.get("app_id") or ""
    title = app.get("title") or app.get("name") or node.get("title") or node.get("name")
    if isinstance(title, dict):
        title = title.get("text") or title.get("name") or ""
    return str(title or "").strip(), str(app_id or "").strip()


def _walk_apps(payload):
    """从接口 JSON 里尽量找出带游戏名的列表。"""
    found = []
    stack = [payload]
    seen_ids = set()
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            name, app_id = _app_name(cur)
            # 榜单名（热门榜）和页面 <title> 也带 name 但没有 app_id，
            # 以前会被当成第 1、2 名，把真实名次整体后移两位。没有 app_id
            # 的节点一律不是游戏，直接丢掉。
            if name and app_id and app_id not in seen_ids:
                seen_ids.add(app_id)
                found.append((name, app_id))
            # stack 是后进先出，直接 extend 会把列表顺序整体倒过来，
            # 而榜单顺序就是名次，必须倒着塞才能正着弹出来
            stack.extend(reversed(list(cur.values())))
        elif isinstance(cur, list):
            stack.extend(reversed(cur))
    # 上面会把嵌套 app 重复扫出来，按首次出现保序去重
    deduped = []
    seen = set()
    for name, app_id in found:
        key = app_id or name
        if key in seen:
            continue
        seen.add(key)
        deduped.append((name, app_id))
    return deduped


def fetch_rank_api(type_name):
    """按 type_name 翻页拉一个榜单，data.list 的顺序就是名次。"""
    rows = []
    seen_ids = set()
    title = ""
    for offset in range(0, RANK_LIMIT, API_PAGE_SIZE):
        url = "%s?from=%d&limit=%d&type_name=%s" % (
            API_URL,
            offset,
            API_PAGE_SIZE,
            type_name,
        )
        try:
            resp = fetch_json(url, headers={"X-UA": X_UA})
            data = resp.json()
        except Exception as exc:
            logger.warning("榜单接口失败 type_name=%s from=%d：%s", type_name, offset, exc)
            break
        block = data.get("data") or {}
        title = title or str(block.get("title") or "")
        page = block.get("list") or []
        if not page:
            break
        for node in page:
            name, app_id = _app_name(node)
            if not name or not app_id or app_id in seen_ids:
                continue
            seen_ids.add(app_id)
            rows.append(
                {
                    "rank": len(rows) + 1,
                    "game_name": name,
                    "app_id": app_id,
                    "list_type": None,
                    "source_url": "https://www.taptap.cn/app/%s" % app_id,
                }
            )
            if len(rows) >= RANK_LIMIT:
                break
        if len(rows) >= RANK_LIMIT or not block.get("next_page"):
            break
    return rows, title


def parse_rank_html(html, list_type):
    if not html:
        return []
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.S,
    )
    if match:
        try:
            payload = json.loads(match.group(1))
        except ValueError:
            payload = None
        if payload:
            rows = []
            for index, (name, app_id) in enumerate(
                _walk_apps(payload)[:RANK_LIMIT], start=1
            ):
                rows.append(
                    {
                        "rank": index,
                        "game_name": name,
                        "app_id": app_id or None,
                        "list_type": list_type,
                        "source_url": (
                            "https://www.taptap.cn/app/%s" % app_id if app_id else None
                        ),
                    }
                )
            if rows:
                return rows

    soup = BeautifulSoup(html, "html.parser")
    rows = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        hit = APP_HREF_RE.search(anchor.get("href") or "")
        if not hit:
            continue
        app_id = hit.group(1)
        if app_id in seen:
            continue
        name_node = anchor.find(class_=re.compile(r"title|name", re.I))
        name = (name_node.get_text(strip=True) if name_node else "") or anchor.get_text(
            strip=True
        )
        name = (name or "").strip()
        if not name or len(name) > 40:
            continue
        seen.add(app_id)
        rows.append(
            {
                "rank": len(rows) + 1,
                "game_name": name,
                "app_id": app_id,
                "list_type": list_type,
                "source_url": "https://www.taptap.cn/app/%s" % app_id,
            }
        )
        if len(rows) >= RANK_LIMIT:
            break
    return rows


def crawl_one_list(list_type, spec):
    rows, title = fetch_rank_api(spec["type_name"])
    if rows:
        for row in rows:
            row["list_type"] = list_type
        logger.info(
            "接口拿到 %s 榜 %d 条（type_name=%s，接口标题=%s，第 1 名=%s）",
            list_type,
            len(rows),
            spec["type_name"],
            title or "未知",
            rows[0]["game_name"],
        )
        return rows
    for path in spec["paths"]:
        html = fetch_html("https://www.taptap.cn" + path)
        rows = parse_rank_html(html, list_type)
        if rows:
            logger.info("HTML 拿到 %s 榜 %d 条（%s）", list_type, len(rows), path)
            return rows
        logger.warning("%s 榜页面无数据：%s", list_type, path)
    return []


def main():
    lists = {}
    for list_type, spec in LIST_SPECS.items():
        lists[list_type] = crawl_one_list(list_type, spec)

    total = sum(len(rows) for rows in lists.values())
    if total == 0:
        logger.error("三个榜都是 0 条，疑似 SPA/反爬，终止写入以免覆盖旧数据")
        return 1

    payload = {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "lists": lists,
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    logger.info("写入 %s，共 %d 条", OUTPUT_PATH, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
