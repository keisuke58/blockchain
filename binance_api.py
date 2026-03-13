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
    client = Client(api_key, api_secret)
    # Sync timestamp offset with Binance server
    try:
        server_time = client.get_server_time()
        import time
        client.timestamp_offset = server_time["serverTime"] - int(time.time() * 1000)
    except Exception:
        pass
    return client


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


def get_earn_subscription_history(asset: str = None, size: int = 100) -> list:
    """
    Fetch Simple Earn (Flexible) subscription history.
    Returns list of purchases with asset, amount, purchase date.
    """
    client = get_client()
    if not client:
        return []
    try:
        params = {"size": size, "current": 1}
        if asset:
            params["asset"] = asset
        records = client._request_margin_api(
            "get", "simple-earn/flexible/history/subscriptionRecord",
            True, data=params
        )
        rows = records.get("rows", []) if isinstance(records, dict) else []
        return rows
    except Exception as e:
        print(f"Earn history fetch error: {e}")
        return []


def get_all_prices() -> dict:
    """Returns {symbol: price} for all USDT pairs."""
    if not BINANCE_AVAILABLE:
        return {}
    client = Client()
    try:
        tickers = client.get_all_tickers()
        return {t["symbol"]: float(t["price"]) for t in tickers}
    except Exception as e:
        print(f"Price fetch error: {e}")
        return {}


def get_jpy_rate() -> float:
    """Returns USD/JPY exchange rate via Binance USDTJPY or fallback."""
    if not BINANCE_AVAILABLE:
        return 150.0
    client = Client()
    try:
        ticker = client.get_symbol_ticker(symbol="USDTJPY")
        return float(ticker["price"])
    except Exception:
        # Fallback: use BTCJPY / BTCUSDT
        try:
            btc_jpy = float(client.get_symbol_ticker(symbol="BTCJPY")["price"])
            btc_usd = float(client.get_symbol_ticker(symbol="BTCUSDT")["price"])
            return btc_jpy / btc_usd
        except Exception:
            return 150.0


def get_portfolio_value() -> dict | None:
    """
    Calculate total portfolio value in USD and JPY.
    Handles both regular balances and LD (Simple Earn) assets.
    """
    balances = get_account_balance()
    if balances is None:
        return None

    prices = get_all_prices()
    jpy_rate = get_jpy_rate()

    items = []
    total_usd = 0.0

    for b in balances:
        asset = b["asset"]
        amount = float(b["free"]) + float(b["locked"])

        # Strip LD prefix for Simple Earn assets
        base = asset[2:] if asset.startswith("LD") else asset

        usd_value = 0.0
        if base == "USDT" or base == "USD":
            usd_value = amount
        elif f"{base}USDT" in prices:
            usd_value = amount * prices[f"{base}USDT"]
        elif base == "EUR":
            eur_usd = prices.get("EURUSDT", 1.08)
            usd_value = amount * eur_usd

        total_usd += usd_value
        items.append({
            "asset": asset,
            "base": base,
            "amount": amount,
            "usd_value": usd_value,
        })

    # Sort by USD value descending
    items.sort(key=lambda x: x["usd_value"], reverse=True)

    return {
        "items": items,
        "total_usd": total_usd,
        "total_jpy": total_usd * jpy_rate,
        "jpy_rate": jpy_rate,
    }
