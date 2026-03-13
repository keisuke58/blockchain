"""
Trading Bot Backtester
Usage:
  python bot.py                  # Backtest all strategies on BTC 1h (90 days)
  python bot.py --symbol ETHUSDT # Different symbol
  python bot.py --days 180       # Longer period
  python bot.py --capital 70000  # Different capital (USD)

Strategies tested:
  1. MA Crossover  (20/50 EMA)
  2. RSI Mean Reversion
  3. Bollinger Bands
  4. Hold (baseline)

Capital default: 1000万円 = ~$70,000 USD
"""

import argparse
from binance.client import Client
import pandas as pd
import numpy as np
from datetime import datetime
from colorama import init, Fore, Style
from tabulate import tabulate

init(autoreset=True)

JPY_RATE = 148.0  # approximate, update if needed


# ── Data fetching ────────────────────────────────────────────

def fetch_ohlcv(symbol: str = "BTCUSDT", interval: str = "1h", days: int = 90) -> pd.DataFrame:
    client = Client()
    limit = days * 24  # 1h candles
    limit = min(limit, 1000)
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df.set_index("open_time", inplace=True)
    return df[["open", "high", "low", "close", "volume"]]


# ── Indicators ───────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # EMA
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    # RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # Bollinger Bands (20, 2std)
    df["bb_mid"] = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * std
    df["bb_lower"] = df["bb_mid"] - 2 * std

    return df.dropna()


# ── Backtest engine ──────────────────────────────────────────

def backtest(df: pd.DataFrame, signals: pd.Series, capital_usd: float,
             fee: float = 0.001) -> dict:
    """
    signals: Series of 1 (buy/hold), -1 (sell/flat), 0 (hold current)
    Returns performance metrics.
    """
    cash = capital_usd
    position = 0.0  # BTC held
    trades = []
    equity = []

    for i, (ts, row) in enumerate(df.iterrows()):
        sig = signals.iloc[i] if i < len(signals) else 0
        price = row["close"]

        if sig == 1 and cash > 1:
            # Buy: go all in
            btc_bought = (cash * (1 - fee)) / price
            position += btc_bought
            trades.append({"type": "BUY", "price": price, "ts": ts})
            cash = 0.0

        elif sig == -1 and position > 0:
            # Sell: exit all
            cash = position * price * (1 - fee)
            trades.append({"type": "SELL", "price": price, "ts": ts})
            position = 0.0

        total = cash + position * price
        equity.append(total)

    final = cash + position * df["close"].iloc[-1]
    eq_series = pd.Series(equity, index=df.index)

    # Max drawdown
    rolling_max = eq_series.cummax()
    drawdown = (eq_series - rolling_max) / rolling_max
    max_dd = drawdown.min()

    # Sharpe (hourly returns, annualized)
    returns = eq_series.pct_change().dropna()
    sharpe = (returns.mean() / returns.std() * (24 * 365) ** 0.5) if returns.std() > 0 else 0

    return {
        "final_usd": final,
        "pnl_usd": final - capital_usd,
        "pnl_pct": (final - capital_usd) / capital_usd * 100,
        "trades": len(trades),
        "max_dd": max_dd * 100,
        "sharpe": sharpe,
        "equity": eq_series,
    }


# ── Strategies ───────────────────────────────────────────────

def strategy_hold(df: pd.DataFrame) -> pd.Series:
    """Buy at start, never sell."""
    signals = pd.Series(0, index=df.index)
    signals.iloc[0] = 1
    return signals


def strategy_ma_cross(df: pd.DataFrame) -> pd.Series:
    """Buy when EMA20 crosses above EMA50, sell when crosses below."""
    signals = pd.Series(0, index=df.index)
    prev_above = df["ema20"].iloc[0] > df["ema50"].iloc[0]

    for i in range(1, len(df)):
        now_above = df["ema20"].iloc[i] > df["ema50"].iloc[i]
        if now_above and not prev_above:
            signals.iloc[i] = 1   # golden cross
        elif not now_above and prev_above:
            signals.iloc[i] = -1  # death cross
        prev_above = now_above

    return signals


def strategy_rsi(df: pd.DataFrame, oversold: float = 30, overbought: float = 70) -> pd.Series:
    """Buy on RSI < 30 (oversold), sell on RSI > 70 (overbought)."""
    signals = pd.Series(0, index=df.index)
    in_position = False

    for i in range(len(df)):
        rsi = df["rsi"].iloc[i]
        if rsi < oversold and not in_position:
            signals.iloc[i] = 1
            in_position = True
        elif rsi > overbought and in_position:
            signals.iloc[i] = -1
            in_position = False

    return signals


def strategy_bollinger(df: pd.DataFrame) -> pd.Series:
    """Buy when price touches lower band, sell at upper band."""
    signals = pd.Series(0, index=df.index)
    in_position = False

    for i in range(len(df)):
        price = df["close"].iloc[i]
        lower = df["bb_lower"].iloc[i]
        upper = df["bb_upper"].iloc[i]

        if price <= lower and not in_position:
            signals.iloc[i] = 1
            in_position = True
        elif price >= upper and in_position:
            signals.iloc[i] = -1
            in_position = False

    return signals


# ── Display ──────────────────────────────────────────────────

def print_header(text):
    print(f"\n{Fore.YELLOW}{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}{Style.RESET_ALL}")


def print_results(results: dict, capital_usd: float):
    rows = []
    for name, r in results.items():
        pnl_color = Fore.GREEN if r["pnl_usd"] >= 0 else Fore.RED
        rows.append([
            name,
            f"${r['final_usd']:>10,.0f}",
            f"{pnl_color}{r['pnl_pct']:>+.1f}%{Style.RESET_ALL}",
            f"{pnl_color}${r['pnl_usd']:>+,.0f}{Style.RESET_ALL}",
            f"JPY {r['pnl_usd'] * JPY_RATE:>+,.0f}",
            f"{r['max_dd']:.1f}%",
            f"{r['sharpe']:.2f}",
            str(r["trades"]),
        ])

    # Sort by final value
    rows.sort(key=lambda x: float(x[1].replace("$", "").replace(",", "")), reverse=True)

    print(tabulate(
        rows,
        headers=["Strategy", "Final(USD)", "Return%", "PnL(USD)", "PnL(JPY)", "MaxDD", "Sharpe", "Trades"],
    ))

    print(f"\n  Capital : ${capital_usd:,.0f}  (JPY {capital_usd * JPY_RATE:,.0f})")


def print_equity_chart(results: dict, height: int = 10):
    print(f"\n  {Fore.CYAN}Equity Curve (relative to start){Style.RESET_ALL}")

    colors = {
        "Hold":      Fore.YELLOW,
        "MA Cross":  Fore.CYAN,
        "RSI":       Fore.GREEN,
        "Bollinger": Fore.MAGENTA,
    }

    # Normalize all equity curves to start at 100
    normalized = {}
    for name, r in results.items():
        eq = r["equity"]
        normalized[name] = (eq / eq.iloc[0] * 100)

    all_vals = [v for eq in normalized.values() for v in eq]
    min_v = min(all_vals)
    max_v = max(all_vals)

    width = 60
    grid = [[" "] * width for _ in range(height)]

    for name, eq in normalized.items():
        indices = np.linspace(0, len(eq) - 1, width).astype(int)
        color = colors.get(name, Fore.WHITE)
        symbol = name[0]
        for x, idx in enumerate(indices):
            val = eq.iloc[idx]
            y = int((val - min_v) / (max_v - min_v + 1e-9) * (height - 1))
            y = max(0, min(height - 1, y))
            grid[y][x] = f"{color}{symbol}{Style.RESET_ALL}"

    for row_idx in range(height - 1, -1, -1):
        val = min_v + (max_v - min_v) * row_idx / (height - 1)
        label = f"{val:>6.0f} |"
        line = "".join(grid[row_idx])
        print(f"  {label}{line}")

    print(f"  {'':8}+{'-' * width}")

    # Legend
    print()
    for name, color in colors.items():
        if name in results:
            pnl = results[name]["pnl_pct"]
            arrow = "^" if pnl >= 0 else "v"
            print(f"    {color}{name[0]}{Style.RESET_ALL} = {name}  ({arrow}{pnl:+.1f}%)")


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",  default="BTCUSDT")
    parser.add_argument("--days",    type=int,   default=90)
    parser.add_argument("--capital", type=float, default=70000.0)  # ~1000万円
    args = parser.parse_args()

    print_header(f"Trading Bot Backtest  |  {args.symbol}  |  {args.days} days")
    print(f"  Capital : ${args.capital:,.0f}  (~JPY {args.capital * JPY_RATE:,.0f})")
    print(f"  Fetching {args.days} days of {args.symbol} data from Binance...")

    df = fetch_ohlcv(symbol=args.symbol, days=args.days)
    df = add_indicators(df)

    print(f"  Candles : {len(df)}  ({df.index[0].date()} to {df.index[-1].date()})")
    print(f"  Price   : ${df['close'].iloc[0]:,.0f} -> ${df['close'].iloc[-1]:,.0f}")
    print()

    strategies = {
        "Hold":      strategy_hold(df),
        "MA Cross":  strategy_ma_cross(df),
        "RSI":       strategy_rsi(df),
        "Bollinger": strategy_bollinger(df),
    }

    results = {}
    for name, signals in strategies.items():
        results[name] = backtest(df, signals, args.capital)

    print_header("Results")
    print_results(results, args.capital)
    print_equity_chart(results)

    # Best strategy
    best = max(results.items(), key=lambda x: x[1]["final_usd"])
    print(f"\n  {Fore.GREEN}Best: {best[0]}  (${best[1]['final_usd']:,.0f}  {best[1]['pnl_pct']:+.1f}%){Style.RESET_ALL}")
    print(f"\n  {Fore.YELLOW}Note: Past performance does not guarantee future results.{Style.RESET_ALL}")
    print(f"  Fee: 0.1% per trade (Binance standard)")


if __name__ == "__main__":
    main()
