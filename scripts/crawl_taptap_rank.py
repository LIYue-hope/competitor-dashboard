"""采集 TapTap 下载 / 预约 / 热玩榜，写入 data/taptap_rank.json。

榜页经常是前端渲染，HTML 里不一定有完整列表。这里先走 webapiv2，
解析失败再退回 HTML。任一榜单都解析不到时拒绝覆盖旧文件。
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

# list_type -> (api type_name 候选, 页面路径候选)
LIST_SPECS = {
    "download": {
        "type_names": ("hot", "download", "sold"),
        "paths": ("/top/download", "/top/hot"),
    },
    "reserve": {
        "type_names": ("reserve", "reserved"),
        "paths": ("/top/reserve", "/top/reserved"),
    },
    "played": {
        "type_names": ("played", "play"),
        "paths": ("/top/played", "/top/play"),
    },
}

APP_HREF_RE = re.compile(r"/app/(\d+)")
RANK_LIMIT = 50


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
            if name and (app_id not in seen_ids or not app_id):
                if app_id:
                    seen_ids.add(app_id)
                if APP_HREF_RE.search("/app/%s" % app_id) or name:
                    found.append((name, app_id))
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
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
    url = "https://www.taptap.cn/webapiv2/app-top/v2/hits"
    try:
        resp = fetch_json(
            url,
            headers={"X-UA": X_UA},
        )
    except Exception as exc:
        logger.warning("榜单接口失败 type_name=%s：%s", type_name, exc)
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    rows = []
    for index, (name, app_id) in enumerate(_walk_apps(data)[:RANK_LIMIT], start=1):
        if not name:
            continue
        rows.append(
            {
                "rank": index,
                "game_name": name,
                "app_id": app_id or None,
                "list_type": None,
                "source_url": (
                    "https://www.taptap.cn/app/%s" % app_id if app_id else None
                ),
            }
        )
    return rows


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
    for type_name in spec["type_names"]:
        rows = fetch_rank_api(type_name)
        if rows:
            for row in rows:
                row["list_type"] = list_type
            logger.info("接口拿到 %s 榜 %d 条（type_name=%s）", list_type, len(rows), type_name)
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
