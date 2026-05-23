from datetime import datetime

import pytz


def is_market_open(now: datetime) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=pytz.utc)
    local = now.astimezone(pytz.timezone("America/New_York"))
    if local.weekday() >= 5:
        return False
    market_open = local.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = local.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= local < market_close
