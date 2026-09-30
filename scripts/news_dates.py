"""Shared date guards for rolling news crawlers.

News sites occasionally expose a malformed future publication date.  A rolling
window must be bounded on both sides: otherwise one bad item can become the
latest day in the dashboard and also pollute the persistent daily snapshot.
"""

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.11 has zoneinfo
    ZoneInfo = None


def beijing_today():
    """Return today's date in the dashboard's Beijing-time data convention."""
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("Asia/Shanghai")).date()
        except Exception:
            pass
    return datetime.now(timezone(timedelta(hours=8))).date()


def is_within_news_window(published_at, window_start, latest_date=None):
    """Return whether an item date is valid for an inclusive rolling window."""
    date_text = str(published_at or "")[:10]
    if latest_date is None:
        latest_date = beijing_today()
    return window_start.isoformat() <= date_text <= latest_date.isoformat()
