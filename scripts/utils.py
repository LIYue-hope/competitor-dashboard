"""公共方法：HTTP 请求封装、关键词匹配等。"""
import logging
import time

import requests

logger = logging.getLogger("competitor_dashboard")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 大厂/大IP关键词库（可按需扩充）。命中发行商/研发商名称即视为大厂/大IP。
MAJOR_PUBLISHER_KEYWORDS = [
    "腾讯",
    "网易",
    "米哈游",
    "完美世界",
    "字节跳动",
    "朝夕光年",
    "莉莉丝",
    "三七互娱",
    "游族",
    "巨人网络",
    "盛趣",
    "西山居",
    "多益网络",
    "第九城市",
    "创梦天地",
    "阿里",
    "百度",
    "心动网络",
    "紫龙游戏",
    "叠纸",
    "鹰角网络",
    "库洛游戏",
    "蜂巢游戏",
    "祖龙娱乐",
]

# "挂机/搬砖"玩法关键词库（匹配游戏简介、标签等文本）。
AFK_GRINDING_KEYWORDS = [
    "挂机",
    "搬砖",
    "自动战斗",
    "自动挂机",
    "离线收益",
    "自动打怪",
    "放置",
]


def fetch_html(url, timeout=10, retries=2, backoff=1.5):
    """发起 GET 请求并返回响应文本，失败时重试，最终失败返回 None。"""
    for attempt in range(1, retries + 2):
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.warning(
                "请求失败（第%d次）：%s，原因：%s", attempt, url, exc
            )
            if attempt <= retries:
                time.sleep(backoff * attempt)
    logger.error("请求彻底失败，放弃：%s", url)
    return None


def fetch_json(url, timeout=10, retries=2, backoff=1.5, headers=None):
    """发起 GET 请求并解析为 JSON，失败时重试，最终失败抛出最后一次异常。

    与 fetch_html 不同：这里失败时抛异常而不是返回 None，因为调用方
    （米哈游公告 API、腾讯 cmc/cross 接口等）后续需要区分"网络失败"
    与"正常返回但业务字段异常"，抛异常能让上层统一走 build_game_record
    的 try/except 降级为 source_status="error"，不会用空数据覆盖旧数据。
    """
    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    last_exc = None
    for attempt in range(1, retries + 2):
        try:
            resp = requests.get(url, headers=merged_headers, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or resp.encoding
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "请求失败（第%d次）：%s，原因：%s", attempt, url, exc
            )
            if attempt <= retries:
                time.sleep(backoff * attempt)
    raise last_exc


def retry_until_nonempty(fetch_parse, label, attempts=3, wait_seconds=5):
    """反复执行"抓取 + 解析"，直到拿到非空结果，全部失败返回最后一次的空结果。

    fetch_html / fetch_json 只在 requests 抛异常时重试，而这些站点偶发返回
    HTTP 200 但正文缺少目标容器（反爬/限流的降级页面），这类响应不会触发它们
    的重试，只会解析出 0 条。前端「数据更新」按钮会按需触发采集，命中频率远高
    于每天一次的定时任务，因此在"抓取 + 解析"这一整层再加一次重试。

    fetch_parse 需要返回列表/字典等可判空的结果；抛异常视为本次失败继续重试。
    """
    result = None
    for attempt in range(1, attempts + 1):
        try:
            result = fetch_parse()
        except Exception:
            logger.exception("%s 第 %d/%d 次抓取解析异常", label, attempt, attempts)
            result = None
        else:
            if result:
                return result
            logger.warning("%s 第 %d/%d 次解析到 0 条", label, attempt, attempts)

        if attempt < attempts:
            logger.info("%s 等待 %d 秒后重试", label, wait_seconds)
            time.sleep(wait_seconds)

    return result


def match_keywords(text, keywords):
    """判断 text 中是否包含 keywords 列表中的任一关键词。"""
    if not text:
        return False
    return any(keyword in text for keyword in keywords)


def is_major_publisher(publisher_name):
    """判断发行商/研发商名称是否命中大厂/大IP关键词库。"""
    return match_keywords(publisher_name, MAJOR_PUBLISHER_KEYWORDS)


def has_afk_grinding_tag(*texts):
    """判断任意文本（简介、标签等）中是否包含挂机/搬砖类关键词。"""
    combined = " ".join(t for t in texts if t)
    return match_keywords(combined, AFK_GRINDING_KEYWORDS)
