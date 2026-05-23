import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import kill_switch_repo, signal_repo
from app.schemas.risk import TradingContext

log = logging.getLogger(__name__)

ET_TZ = ZoneInfo("America/New_York")


def build_trading_context(db: Session, settings: Settings) -> TradingContext:
    """
    Assemble TradingContext from DB state immediately before Risk Engine evaluation.
    Day and week boundaries are computed in America/New_York. All DB queries use UTC.

    In V0 all PnL fields return zero — no fills exist to compute realized PnL.
    """
    et_now = datetime.now(ET_TZ)
    et_today: date = et_now.date()
    week_start_et: date = et_today - timedelta(days=et_today.weekday())  # Monday

    # Convert ET day boundaries to UTC-aware datetimes for DB queries
    today_utc_start = datetime.combine(et_today, time.min, tzinfo=ET_TZ).astimezone(timezone.utc)
    week_utc_start = datetime.combine(week_start_et, time.min, tzinfo=ET_TZ).astimezone(timezone.utc)

    daily_approved = signal_repo.get_approved_since(db, today_utc_start)
    daily_trade_count = len(daily_approved)

    # V0: PnL tracking deferred — no fills to compute realized PnL
    log.debug(
        "pnl_tracking_deferred",
        extra={
            "reason": "v0_no_fills",
            "daily_trade_count": daily_trade_count,
            "et_today": et_today.isoformat(),
            "week_start_et": week_start_et.isoformat(),
        },
    )

    kill_switch_row = kill_switch_repo.get_state(db)
    kill_switch_active = kill_switch_row.active if kill_switch_row is not None else settings.KILL_SWITCH

    return TradingContext(
        et_trading_date=et_today,
        daily_trade_count=daily_trade_count,
        daily_pnl_pct=Decimal("0"),        # V0: no fills
        weekly_pnl_pct=Decimal("0"),       # V0: no fills
        consecutive_losses=0,               # V0: no fills
        daily_target_would_be_reached=False,  # V0: no fills to compare against
        kill_switch_active=kill_switch_active,
        equity=settings.INITIAL_EQUITY,
    )
