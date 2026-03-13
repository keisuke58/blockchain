"""
Binance API integration
- BTC/USDT real-time price
- Account balance (requires API key)
- Recent trade history
"""

import os
from dotenv import load_dotenv

load_dotenv()

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
    BINANCE_AVAILABLE = True
except ImportError:
    BINANCE_AVAILABLE = False


def get_client() -> "Client | None":
    """Create an authenticated Binance client from .env keys."""
    if not BINANCE_AVAILABLE:
        print("python-binance not installed. Run: pip install python-binance")
        return None
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        return None
    return Client(api_key, api_secret)


def get_btc_price(symbol: str = "BTCUSDT") -> float | None:
    """Fetch latest BTC price in USDT (no API key required)."""
    if not BINANCE_AVAILABLE:
        return None
    client = Client()  # public endpoint
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])
    except Exception as e:
        print(f"Price fetch error: {e}")
        return None


def get_account_balance() -> list[dict] | None:
    """
    Fetch non-zero balances from Binance account.
    Requires BINANCE_API_KEY and BINANCE_API_SECRET in .env
    """
    client = get_client()
    if not client:
        return None
    try:
        account = client.get_account()
        balances = [
            b for b in account["balances"]
            if float(b["free"]) > 0 or float(b["locked"]) > 0
        ]
        return balances
    except BinanceAPIException as e:
        print(f"Binance API error: {e}")
        return None


def get_recent_btc_trades(limit: int = 10) -> list[dict] | None:
    """
    Fetch recent BTC trades from your Binance account.
    Requires API key.
    """
    client = get_client()
    if not client:
        return None
    try:
        trades = client.get_my_trades(symbol="BTCUSDT", limit=limit)
        return trades
    except BinanceAPIException as e:
        print(f"Binance API error: {e}")
        return None


def get_klines(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 24) -> list:
    """
    Fetch candlestick (OHLCV) data.
    interval: '1m','5m','1h','1d', etc.
    """
    if not BINANCE_AVAILABLE:
        return []
    client = Client()
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        result = []
        for k in klines:
            result.append({
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })
        return result
    except Exception as e:
        print(f"Klines fetch error: {e}")
        return []
