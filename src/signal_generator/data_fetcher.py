import pandas as pd
import yfinance as yf

TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "1d": "1d",
}


class DataFetchError(Exception):
    pass


def fetch_ohlcv(ticker: str, period: str, timeframe: str) -> pd.DataFrame:
    interval = TIMEFRAME_MAP.get(timeframe, timeframe)
    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
    except Exception as exc:
        raise DataFetchError(f"yfinance error for {ticker}: {exc}") from exc

    if df is None or df.empty:
        raise DataFetchError(f"No data returned for {ticker}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)

    return df
