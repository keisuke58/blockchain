"""
Paper Trading Engine
Usage:
  python paper_trade.py                    # Run with default RSI strategy, $70k
  python paper_trade.py --strategy ml      # Use ML strategy
  python paper_trade.py --strategy rsi     # RSI strategy
  python paper_trade.py --strategy ma      # MA Crossover
  python paper_trade.py --capital 70000    # Capital in USD
  python paper_trade.py --symbol ETHUSDT   # Different symbol
  python paper_trade.py --interval 60      # Check every 60 seconds (default: 3600)
  python paper_trade.py --status           # Show current paper portfolio status

Trades are logged to logs/paper_trades.json
"""

import argparse
import json
import os
import time
from datetime import datetime
from colorama import init, Fore, Style
from tabulate import tabulate

import bot as b
import binance_api as bapi

init(autoreset=True)

PAPER_FILE = "logs/paper_trades.json"
JPY_RATE_FALLBACK = 148.0


# ── Persistence ──────────────────────────────────────────────

def load_portfolio() -> dict:
    if os.path.exists(PAPER_FILE):
        with open(PAPER_FILE, "r") as f:
            return json.load(f)
    return None


def save_portfolio(portfolio: dict):
    os.makedirs("logs", exist_ok=True)
    with open(PAPER_FILE, "w") as f:
        json.dump(portfolio, f, indent=2)


def new_portfolio(capital_usd: float, symbol: str, strategy: str) -> dict:
    return {
        "symbol":    symbol,
        "strategy":  strategy,
        "capital":   capital_usd,
        "cash":      capital_usd,
        "position":  0.0,
        "trades":    [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }


# ── Signal generators (single-candle, live) ──────────────────

def get_live_signal(strategy: str, symbol: str) -> tuple[int, dict]:
    """
    Returns (signal, info_dict)
    signal: 1=buy, -1=sell, 0=hold
    """
    df = b.fetch_ohlcv(symbol=symbol, days=7)
    df = b.add_indicators(df)

    info = {
        "price":  df["close"].iloc[-1],
        "rsi":    df["rsi"].iloc[-1],
        "ema20":  df["ema20"].iloc[-1],
        "ema50":  df["ema50"].iloc[-1],
        "bb_upper": df["bb_upper"].iloc[-1],
        "bb_lower": df["bb_lower"].iloc[-1],
    }

    if strategy == "rsi":
        rsi = info["rsi"]
        if rsi < 30:
            return 1, info
        elif rsi > 70:
            return -1, info
        return 0, info

    elif strategy == "ma":
        prev_ema20 = df["ema20"].iloc[-2]
        prev_ema50 = df["ema50"].iloc[-2]
        now_above  = info["ema20"] > info["ema50"]
        prev_above = prev_ema20 > prev_ema50
        if now_above and not prev_above:
            return 1, info
        elif not now_above and prev_above:
            return -1, info
        return 0, info

    elif strategy == "bb":
        price = info["price"]
        if price <= info["bb_lower"]:
            return 1, info
        elif price >= info["bb_upper"]:
            return -1, info
        return 0, info

    elif strategy == "ml":
        signal = get_ml_signal(symbol)
        return signal, info

    return 0, info


def get_ml_signal(symbol: str) -> int:
    """Use trained ML model if available, else return 0."""
    model_file = f"logs/ml_model_{symbol}.pkl"
    if not os.path.exists(model_file):
        print(f"  {Fore.YELLOW}ML model not trained yet. Run: python ml_strategy.py --symbol {symbol}{Style.RESET_ALL}")
        return 0

    import pickle
    from ml_strategy import build_features

    with open(model_file, "rb") as f:
        model = pickle.load(f)

    df = b.fetch_ohlcv(symbol=symbol, days=14)
    df = b.add_indicators(df)
    X = build_features(df)
    if len(X) == 0:
        return 0

    pred = model.predict(X.iloc[[-1]])[0]
    return int(pred)


# ── Execute paper trade ───────────────────────────────────────

def execute(portfolio: dict, signal: int, price: float, fee: float = 0.001):
    cash     = portfolio["cash"]
    position = portfolio["position"]
    ts       = datetime.now().isoformat()
    action   = None

    if signal == 1 and cash > 1:
        btc = (cash * (1 - fee)) / price
        portfolio["position"] = position + btc
        portfolio["cash"]     = 0.0
        action = {"ts": ts, "type": "BUY",  "price": price, "btc": btc,  "usd": cash}

    elif signal == -1 and position > 0:
        usd = position * price * (1 - fee)
        portfolio["cash"]     = cash + usd
        portfolio["position"] = 0.0
        action = {"ts": ts, "type": "SELL", "price": price, "btc": position, "usd": usd}

    if action:
        portfolio["trades"].append(action)

    portfolio["updated_at"] = ts
    return action


# ── Status display ───────────────────────────────────────────

def show_status(portfolio: dict):
    symbol = portfolio["symbol"]
    price  = bapi.get_btc_price(symbol) or 0.0
    jpy    = bapi.get_jpy_rate() or JPY_RATE_FALLBACK

    cash     = portfolio["cash"]
    position = portfolio["position"]
    total    = cash + position * price
    pnl      = total - portfolio["capital"]
    pnl_pct  = pnl / portfolio["capital"] * 100

    color = Fore.GREEN if pnl >= 0 else Fore.RED
    arrow = "^" if pnl >= 0 else "v"

    print(f"\n{Fore.YELLOW}{'='*55}")
    print(f"  Paper Portfolio  [{portfolio['strategy'].upper()}]  {symbol}")
    print(f"{'='*55}{Style.RESET_ALL}")
    print(f"  Capital   : ${portfolio['capital']:>10,.0f}")
    print(f"  Cash      : ${cash:>10,.2f}")
    print(f"  Position  : {position:.6f} {symbol[:3]}  (${position*price:,.2f})")
    print(f"  Total     : ${total:>10,.2f}  (JPY {total*jpy:,.0f})")
    print(f"  P&L       : {color}{arrow} ${pnl:+,.2f}  ({pnl_pct:+.2f}%){Style.RESET_ALL}")
    print(f"  Trades    : {len(portfolio['trades'])}")

    if portfolio["trades"]:
        print()
        rows = [[
            t["ts"][:16],
            Fore.GREEN + t["type"] + Style.RESET_ALL if t["type"] == "BUY" else Fore.RED + t["type"] + Style.RESET_ALL,
            f"${t['price']:,.2f}",
            f"{t['btc']:.6f}",
            f"${t['usd']:,.2f}",
        ] for t in portfolio["trades"][-10:]]
        print(tabulate(rows, headers=["Time", "Type", "Price", "BTC", "USD"]))


# ── Main loop ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="rsi",
                        choices=["rsi", "ma", "bb", "ml"])
    parser.add_argument("--symbol",   default="BTCUSDT")
    parser.add_argument("--capital",  type=float, default=70000.0)
    parser.add_argument("--interval", type=int,   default=3600,
                        help="Seconds between checks (default 3600=1h)")
    parser.add_argument("--status",   action="store_true",
                        help="Show current status and exit")
    args = parser.parse_args()

    # Status only
    if args.status:
        portfolio = load_portfolio()
        if not portfolio:
            print(f"{Fore.RED}  No paper portfolio found. Run without --status to start.{Style.RESET_ALL}")
            return
        show_status(portfolio)
        return

    # Load or create portfolio
    portfolio = load_portfolio()
    if not portfolio:
        portfolio = new_portfolio(args.capital, args.symbol, args.strategy)
        save_portfolio(portfolio)
        print(f"  {Fore.GREEN}New paper portfolio created.{Style.RESET_ALL}")
        print(f"  Strategy : {args.strategy.upper()}")
        print(f"  Capital  : ${args.capital:,.0f}")
    else:
        print(f"  Loaded existing portfolio ({portfolio['strategy'].upper()}, "
              f"${portfolio['capital']:,.0f})")

    print(f"  Checking every {args.interval}s. Ctrl+C to stop.\n")

    try:
        while True:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            signal, info = get_live_signal(portfolio["strategy"], portfolio["symbol"])
            price = info["price"]

            sig_text = {1: f"{Fore.GREEN}BUY ", -1: f"{Fore.RED}SELL", 0: "HOLD"}[signal]
            print(f"  [{ts}]  ${price:,.2f}  RSI={info['rsi']:.1f}  "
                  f"Signal={sig_text}{Style.RESET_ALL}", end="")

            action = execute(portfolio, signal, price)
            if action:
                print(f"  -> {action['type']} {action['btc']:.6f} BTC @ ${price:,.2f}")
                save_portfolio(portfolio)
            else:
                print()

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print(f"\n\n  Stopped. Final status:")
        show_status(portfolio)


if __name__ == "__main__":
    main()
