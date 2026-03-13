"""
Live Trading Bot (Real Money)
Usage:
  python live_bot.py                  # Run once (called by Task Scheduler)
  python live_bot.py --status         # Show current position and P&L
  python live_bot.py --budget 10      # Budget in EUR (default: 10)
  python live_bot.py --symbol BTCEUR  # Symbol (default: BTCEUR)
  python live_bot.py --strategy rsi   # Strategy: rsi / ml (default: rsi)

Safety:
  - Only trades up to --budget EUR (default 10 EUR)
  - Stop loss: -15% from entry
  - Daily loss limit: -20% of budget
  - All actions logged to logs/live_bot.log and logs/live_state.json
"""

import argparse
import json
import os
import math
import logging
from datetime import datetime, date
from colorama import init, Fore, Style

import binance_api as bapi
import bot as b

init(autoreset=True)

LOG_FILE   = "logs/live_bot.log"
STATE_FILE = "logs/live_state.json"
FEE        = 0.001   # 0.1% Binance standard

# ── Logging ──────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger("live_bot")


# ── State persistence ────────────────────────────────────────

def load_state(symbol: str, budget: float, strategy: str) -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "symbol":       symbol,
        "strategy":     strategy,
        "budget_eur":   budget,
        "position_btc": 0.0,
        "entry_price":  None,
        "daily_loss":   0.0,
        "last_date":    str(date.today()),
        "trades":       [],
    }


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Quantity rounding ─────────────────────────────────────────

def round_qty(qty: float, step: float) -> float:
    precision = max(0, -int(math.log10(step)))
    return round(math.floor(qty / step) * step, precision)


def get_step_size(client, symbol: str) -> float:
    info = client.get_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            for f in s["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    return float(f["stepSize"])
    return 0.00001


# ── Signal ───────────────────────────────────────────────────

def get_signal(strategy: str, symbol: str) -> tuple[int, dict]:
    usdt_symbol = symbol.replace("EUR", "USDT")
    try:
        df = b.fetch_ohlcv(symbol=usdt_symbol, days=7)
        df = b.add_indicators(df)
    except Exception:
        df = b.fetch_ohlcv(symbol=symbol, days=7)
        df = b.add_indicators(df)

    info = {
        "price": float(bapi.get_btc_price(symbol) or df["close"].iloc[-1]),
        "rsi":   df["rsi"].iloc[-1],
        "ema20": df["ema20"].iloc[-1],
        "ema50": df["ema50"].iloc[-1],
        "bb_upper": df["bb_upper"].iloc[-1],
        "bb_lower": df["bb_lower"].iloc[-1],
    }

    if strategy == "rsi":
        if info["rsi"] < 30:
            return 1, info
        elif info["rsi"] > 70:
            return -1, info
        return 0, info

    elif strategy == "ml":
        model_file = f"logs/ml_model_BTCUSDT.pkl"
        if not os.path.exists(model_file):
            log.warning("ML model not found. Run: python ml_strategy.py")
            return 0, info
        import pickle
        from ml_strategy import build_features
        with open(model_file, "rb") as f:
            model = pickle.load(f)
        try:
            df2 = b.fetch_ohlcv(symbol="BTCUSDT", days=14)
            df2 = b.add_indicators(df2)
            X = build_features(df2)
            proba = model.predict_proba(X.iloc[[-1]])[0]
            if max(proba) >= 0.60:
                pred = model.predict(X.iloc[[-1]])[0]
                return int(pred), info
        except Exception as e:
            log.warning(f"ML prediction failed: {e}")
        return 0, info

    return 0, info


# ── Safety checks ────────────────────────────────────────────

def check_stop_loss(state: dict, current_price: float) -> bool:
    if state["entry_price"] and state["position_btc"] > 0:
        drop = (current_price - state["entry_price"]) / state["entry_price"]
        if drop <= -0.15:
            log.warning(f"STOP LOSS triggered: entry={state['entry_price']:.2f} "
                        f"current={current_price:.2f} drop={drop:.1%}")
            return True
    return False


def reset_daily_loss_if_new_day(state: dict):
    today = str(date.today())
    if state.get("last_date") != today:
        state["daily_loss"] = 0.0
        state["last_date"]  = today


def check_daily_loss_limit(state: dict) -> bool:
    limit = state["budget_eur"] * 0.20
    if state["daily_loss"] <= -limit:
        log.warning(f"Daily loss limit hit: {state['daily_loss']:.2f} EUR")
        return True
    return False


# ── Order execution ──────────────────────────────────────────

def place_buy(client, state: dict, price: float):
    budget  = state["budget_eur"]
    step    = get_step_size(client, state["symbol"])
    qty_raw = (budget * (1 - FEE)) / price
    qty     = round_qty(qty_raw, step)

    if qty * price < 5.0:
        log.info(f"Order too small ({qty * price:.2f} EUR < 5 EUR min). Skipping.")
        return False

    try:
        order = client.create_order(
            symbol=state["symbol"],
            side="BUY",
            type="MARKET",
            quantity=qty,
        )
        filled_price = float(order["fills"][0]["price"]) if order.get("fills") else price
        filled_qty   = float(order["executedQty"])

        state["position_btc"] = filled_qty
        state["entry_price"]  = filled_price
        state["trades"].append({
            "ts":    datetime.now().isoformat(),
            "type":  "BUY",
            "price": filled_price,
            "qty":   filled_qty,
            "eur":   filled_qty * filled_price,
        })
        log.info(f"BUY  {filled_qty:.6f} {state['symbol'][:3]} @ {filled_price:.2f} EUR  "
                 f"(total {filled_qty * filled_price:.2f} EUR)")
        return True

    except Exception as e:
        log.error(f"BUY order failed: {e}")
        return False


def place_sell(client, state: dict, price: float, reason: str = "signal"):
    qty = round_qty(state["position_btc"], get_step_size(client, state["symbol"]))
    if qty <= 0:
        return False

    try:
        order = client.create_order(
            symbol=state["symbol"],
            side="SELL",
            type="MARKET",
            quantity=qty,
        )
        filled_price = float(order["fills"][0]["price"]) if order.get("fills") else price
        filled_qty   = float(order["executedQty"])
        proceeds     = filled_qty * filled_price * (1 - FEE)

        # Track P&L
        if state["entry_price"]:
            pnl = proceeds - (filled_qty * state["entry_price"])
            state["daily_loss"] += min(0, pnl)
        else:
            pnl = 0

        state["trades"].append({
            "ts":     datetime.now().isoformat(),
            "type":   "SELL",
            "price":  filled_price,
            "qty":    filled_qty,
            "eur":    proceeds,
            "reason": reason,
        })
        state["position_btc"] = 0.0
        state["entry_price"]  = None

        arrow = "^" if pnl >= 0 else "v"
        log.info(f"SELL {filled_qty:.6f} {state['symbol'][:3]} @ {filled_price:.2f} EUR  "
                 f"P&L: {arrow}{pnl:+.4f} EUR  [{reason}]")
        return True

    except Exception as e:
        log.error(f"SELL order failed: {e}")
        return False


# ── Status display ───────────────────────────────────────────

def show_status(state: dict):
    client = bapi.get_client()
    if not client:
        print(f"{Fore.RED}  No API keys found.{Style.RESET_ALL}")
        return

    symbol = state["symbol"]
    price  = float(bapi.get_btc_price(symbol) or 0)
    pos    = state["position_btc"]
    value  = pos * price

    print(f"\n{Fore.YELLOW}{'='*55}")
    print(f"  Live Bot Status  [{state['strategy'].upper()}]  {symbol}")
    print(f"{'='*55}{Style.RESET_ALL}")
    print(f"  Budget     : {state['budget_eur']:.2f} EUR")
    print(f"  Position   : {pos:.6f} BTC  ({value:.4f} EUR)")
    if state["entry_price"]:
        pnl = (price - state["entry_price"]) / state["entry_price"] * 100
        c   = Fore.GREEN if pnl >= 0 else Fore.RED
        print(f"  Entry      : {state['entry_price']:.2f} EUR")
        print(f"  Unrealized : {c}{pnl:+.2f}%{Style.RESET_ALL}")
    print(f"  Daily loss : {state['daily_loss']:.4f} EUR")
    print(f"  Trades     : {len(state['trades'])}")

    if state["trades"]:
        print()
        from tabulate import tabulate
        rows = [[
            t["ts"][:16],
            (Fore.GREEN if t["type"] == "BUY" else Fore.RED) + t["type"] + Style.RESET_ALL,
            f"{t['price']:.2f}",
            f"{t['qty']:.6f}",
            f"{t['eur']:.4f}",
        ] for t in state["trades"][-8:]]
        print(tabulate(rows, headers=["Time", "Type", "Price(EUR)", "Qty", "EUR"]))


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget",   type=float, default=10.0)
    parser.add_argument("--symbol",   default="BTCEUR")
    parser.add_argument("--strategy", default="rsi", choices=["rsi", "ml"])
    parser.add_argument("--status",   action="store_true")
    args = parser.parse_args()

    state = load_state(args.symbol, args.budget, args.strategy)

    if args.status:
        show_status(state)
        return

    client = bapi.get_client()
    if not client:
        log.error("No Binance API keys. Check .env")
        return

    reset_daily_loss_if_new_day(state)

    if check_daily_loss_limit(state):
        log.info("Daily loss limit reached. Skipping today.")
        save_state(state)
        return

    signal, info = get_signal(state["strategy"], state["symbol"])
    price = info["price"]

    log.info(f"Signal={signal:+d}  Price={price:.2f}  RSI={info['rsi']:.1f}  "
             f"Pos={state['position_btc']:.6f}")

    # Stop loss check
    if check_stop_loss(state, price):
        place_sell(client, state, price, reason="stop_loss")
        save_state(state)
        return

    # Execute signal
    if signal == 1 and state["position_btc"] == 0:
        place_buy(client, state, price)

    elif signal == -1 and state["position_btc"] > 0:
        place_sell(client, state, price, reason="signal")

    else:
        log.info("HOLD - no action")

    save_state(state)


if __name__ == "__main__":
    main()
