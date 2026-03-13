"""
Bitcoin Wallet CLI
Usage:
  python cli.py new          # Generate new wallet
  python cli.py info         # Show loaded wallet info
  python cli.py balance      # Check BTC balance
  python cli.py price        # Show BTC/USDT price (Binance)
  python cli.py binance      # Show Binance account balances
  python cli.py history      # Show Binance BTC trade history
  python cli.py send <addr> <btc>  # Send BTC (testnet by default)
"""

import sys
import json
from colorama import init, Fore, Style
from tabulate import tabulate

import wallet as w
import binance_api as bapi

init(autoreset=True)


def header(text: str):
    print(f"\n{Fore.YELLOW}{'='*50}")
    print(f"  {text}")
    print(f"{'='*50}{Style.RESET_ALL}")


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

    # Also show USD value if price available
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
        t["orderId"],
        t["side"],
        t["price"],
        t["qty"],
        t["quoteQty"],
        t["time"],
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


COMMANDS = {
    "new": cmd_new,
    "info": cmd_info,
    "balance": cmd_balance,
    "price": cmd_price,
    "binance": cmd_binance,
    "history": cmd_history,
    "send": cmd_send,
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

    fn = COMMANDS[cmd]
    if cmd == "send":
        fn(extra)
    elif cmd == "price":
        fn()
    elif cmd == "binance":
        fn()
    elif cmd == "history":
        fn()
    else:
        fn()


if __name__ == "__main__":
    main()
