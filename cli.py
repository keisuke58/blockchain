"""
Bitcoin Wallet CLI
Usage:
  python cli.py new               # Generate new wallet
  python cli.py info              # Show loaded wallet info
  python cli.py balance           # Check BTC balance
  python cli.py price             # Show BTC/USDT price (Binance)
  python cli.py binance           # Show Binance account balances
  python cli.py portfolio         # Show total portfolio value (USD + JPY)
  python cli.py chart             # ASCII price chart (BTC 24h)
  python cli.py save              # Save portfolio snapshot to CSV
  python cli.py alert <price>     # Alert when BTC crosses price (USD)
  python cli.py history           # Show Binance BTC trade history
  python cli.py send <addr> <btc> # Send BTC (testnet by default)
"""

import sys
import csv
import time
import os
from datetime import datetime
from colorama import init, Fore, Style
from tabulate import tabulate

import wallet as w
import binance_api as bapi

init(autoreset=True)

SNAPSHOT_FILE = "portfolio_history.csv"


def header(text: str):
    print(f"\n{Fore.YELLOW}{'='*55}")
    print(f"  {text}")
    print(f"{'='*55}{Style.RESET_ALL}")


# ── existing commands ──────────────────────────────────────

def cmd_new(testnet: bool = True):
    header("Generate New Bitcoin Wallet")
    wallet = w.create_new_wallet(testnet=testnet)
    data = wallet.to_dict()
    print(f"  Network    : {Fore.CYAN}{data['network']}")
    print(f"  Address    : {Fore.GREEN}{data['address']}")
    print(f"  Private Key: {Fore.RED}{data['private_key_wif']}")
    print(f"\n{Fore.RED}  WARNING: Save your private key securely! Never share it.")
    print(f"  Tip: Add it to .env as BTC_PRIVATE_KEY=<key>")


def cmd_info(testnet: bool = True):
    header("Wallet Info")
    wallet = w.load_wallet_from_env(testnet=testnet)
    if not wallet:
        print(f"{Fore.RED}  No wallet found. Set BTC_PRIVATE_KEY in .env or run: python cli.py new")
        return
    data = wallet.to_dict()
    print(f"  Network : {Fore.CYAN}{data['network']}")
    print(f"  Address : {Fore.GREEN}{data['address']}")


def cmd_balance(testnet: bool = True):
    header("Bitcoin Balance")
    wallet = w.load_wallet_from_env(testnet=testnet)
    if not wallet:
        print(f"{Fore.RED}  No wallet loaded. Set BTC_PRIVATE_KEY in .env")
        return
    print(f"  Fetching balance for {wallet.address} ...")
    bal = wallet.get_balance()
    print(f"  Balance : {Fore.GREEN}{bal['btc']:.8f} BTC  ({bal['satoshis']:,} sat)")
    price = bapi.get_btc_price()
    if price:
        usd = bal["btc"] * price
        print(f"  Value   : {Fore.YELLOW}${usd:,.2f} USD  (BTC = ${price:,.2f})")


def cmd_price():
    header("Bitcoin Price (Binance)")
    price = bapi.get_btc_price()
    if price:
        print(f"  BTC/USDT : {Fore.GREEN}${price:,.2f}")
    else:
        print(f"{Fore.RED}  Failed to fetch price.")
    klines = bapi.get_klines(limit=6)
    if klines:
        rows = [[
            f"{k['open_time'] // 1000}",
            f"${k['open']:,.2f}",
            f"${k['high']:,.2f}",
            f"${k['low']:,.2f}",
            f"${k['close']:,.2f}",
        ] for k in klines]
        print()
        print(tabulate(rows, headers=["Timestamp", "Open", "High", "Low", "Close"]))


def cmd_binance():
    header("Binance Account Balances")
    balances = bapi.get_account_balance()
    if balances is None:
        print(f"{Fore.RED}  Set BINANCE_API_KEY and BINANCE_API_SECRET in .env")
        return
    if not balances:
        print("  No non-zero balances found.")
        return
    rows = [[b["asset"], b["free"], b["locked"]] for b in balances]
    print(tabulate(rows, headers=["Asset", "Free", "Locked"]))


def cmd_history():
    header("Binance BTC Trade History")
    trades = bapi.get_recent_btc_trades(limit=10)
    if trades is None:
        print(f"{Fore.RED}  Set BINANCE_API_KEY and BINANCE_API_SECRET in .env")
        return
    if not trades:
        print("  No trades found.")
        return
    rows = [[
        t["orderId"], t["side"], t["price"],
        t["qty"], t["quoteQty"], t["time"],
    ] for t in trades]
    print(tabulate(rows, headers=["Order ID", "Side", "Price", "Qty", "Total USDT", "Time"]))


def cmd_send(args):
    if len(args) < 2:
        print(f"{Fore.RED}  Usage: python cli.py send <address> <amount_btc>")
        return
    recipient, amount = args[0], float(args[1])
    header(f"Send {amount} BTC to {recipient}")
    wallet = w.load_wallet_from_env(testnet=True)
    if not wallet:
        print(f"{Fore.RED}  No wallet loaded.")
        return
    confirm = input(f"  Confirm send {amount} BTC to {recipient}? [y/N] ")
    if confirm.lower() != "y":
        print("  Cancelled.")
        return
    tx_id = wallet.send(recipient, amount)
    print(f"  TX ID: {Fore.GREEN}{tx_id}")


# ── new commands ───────────────────────────────────────────

def cmd_portfolio():
    header("Portfolio Value")
    print("  Fetching prices and balances...")
    result = bapi.get_portfolio_value()
    if result is None:
        print(f"{Fore.RED}  Set BINANCE_API_KEY and BINANCE_API_SECRET in .env")
        return

    rows = []
    for item in result["items"]:
        if item["usd_value"] < 0.01:
            continue
        pct = item["usd_value"] / result["total_usd"] * 100 if result["total_usd"] else 0
        rows.append([
            item["asset"],
            f"{item['amount']:.6f}",
            f"${item['usd_value']:,.2f}",
            f"{pct:.1f}%",
        ])

    print(tabulate(rows, headers=["Asset", "Amount", "USD Value", "Allocation"]))
    print()
    print(f"  {'Total USD':15}: {Fore.GREEN}${result['total_usd']:>12,.2f}")
    print(f"  {'Total JPY':15}: {Fore.YELLOW}JPY {result['total_jpy']:>12,.0f}")
    print(f"  {'USD/JPY':15}: {result['jpy_rate']:.2f}")


def cmd_chart():
    header("BTC Price Chart (24h, 1h candles)")
    klines = bapi.get_klines(limit=24)
    if not klines:
        print(f"{Fore.RED}  Failed to fetch data.")
        return

    closes = [k["close"] for k in klines]
    highs  = [k["high"]  for k in klines]
    lows   = [k["low"]   for k in klines]

    min_p = min(lows)
    max_p = max(highs)
    height = 12
    width  = len(closes)

    def scale(price):
        return int((price - min_p) / (max_p - min_p) * (height - 1))

    # Build grid
    grid = [[" "] * width for _ in range(height)]
    for x, (c, h, l) in enumerate(zip(closes, highs, lows)):
        hi = scale(h)
        lo = scale(l)
        cl = scale(c)
        for y in range(lo, hi + 1):
            grid[y][x] = "|"
        grid[cl][x] = "*"

    # Print top to bottom
    current = closes[-1]
    change = closes[-1] - closes[0]
    change_pct = change / closes[0] * 100
    color = Fore.GREEN if change >= 0 else Fore.RED
    arrow = "^" if change >= 0 else "v"

    print(f"  Current: {color}${current:,.2f}  {arrow} {change_pct:+.2f}% (24h){Style.RESET_ALL}")
    print(f"  High: ${max_p:,.2f}   Low: ${min_p:,.2f}")
    print()

    for row_idx in range(height - 1, -1, -1):
        price_at = min_p + (max_p - min_p) * row_idx / (height - 1)
        label = f"${price_at:>10,.0f} |"
        line = "".join(grid[row_idx])
        print(f"  {label}{line}")

    print(f"  {'':12}+{'-' * width}")
    print(f"  {'':13}{'24h ago':>8}{'':>{width-16}}{'now':>8}")


def cmd_save():
    header("Save Portfolio Snapshot")
    result = bapi.get_portfolio_value()
    if result is None:
        print(f"{Fore.RED}  Set BINANCE_API_KEY and BINANCE_API_SECRET in .env")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.exists(SNAPSHOT_FILE)

    with open(SNAPSHOT_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "total_usd", "total_jpy", "jpy_rate"])
        writer.writerow([now, f"{result['total_usd']:.2f}", f"{result['total_jpy']:.0f}", f"{result['jpy_rate']:.2f}"])

    print(f"  Saved to {Fore.GREEN}{SNAPSHOT_FILE}")
    print(f"  Total USD : ${result['total_usd']:,.2f}")
    print(f"  Total JPY : JPY {result['total_jpy']:,.0f}")
    print(f"  Timestamp : {now}")

    # Show history
    if os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE, "r") as f:
            rows = list(csv.reader(f))
        print()
        print(tabulate(rows[1:], headers=rows[0]))


def cmd_alert(args):
    if not args:
        print(f"{Fore.RED}  Usage: python cli.py alert <target_price_usd>")
        return
    target = float(args[0])
    header(f"Price Alert: BTC crosses ${target:,.0f}")

    current = bapi.get_btc_price()
    above = current >= target if current else None
    print(f"  Current price : ${current:,.2f}")
    print(f"  Target price  : ${target:,.2f}")
    print(f"  Watching... (Ctrl+C to stop)")

    try:
        while True:
            price = bapi.get_btc_price()
            if price is None:
                time.sleep(30)
                continue
            now_above = price >= target
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{ts}] BTC = ${price:,.2f}", end="\r")

            if above is not None and now_above != above:
                direction = "ABOVE" if now_above else "BELOW"
                color = Fore.GREEN if now_above else Fore.RED
                print(f"\n  {color}🔔 ALERT! BTC is now {direction} ${target:,.0f}  (${price:,.2f})")
                above = now_above

            time.sleep(30)
    except KeyboardInterrupt:
        print(f"\n  Alert stopped.")


# ── dispatch ───────────────────────────────────────────────

COMMANDS = {
    "new":       (cmd_new,       False),
    "info":      (cmd_info,      False),
    "balance":   (cmd_balance,   False),
    "price":     (cmd_price,     False),
    "binance":   (cmd_binance,   False),
    "history":   (cmd_history,   False),
    "send":      (cmd_send,      True),
    "portfolio": (cmd_portfolio, False),
    "chart":     (cmd_chart,     False),
    "save":      (cmd_save,      False),
    "alert":     (cmd_alert,     True),
}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    extra = sys.argv[2:]
    if cmd not in COMMANDS:
        print(f"{Fore.RED}Unknown command: {cmd}")
        print(__doc__)
        return
    fn, takes_args = COMMANDS[cmd]
    fn(extra) if takes_args else fn()


if __name__ == "__main__":
    main()
