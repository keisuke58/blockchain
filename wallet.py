"""
Bitcoin Wallet - Core functionality
Supports mainnet and testnet address generation, balance checking, and transactions.
"""

import os
from dotenv import load_dotenv
from bit import Key, PrivateKeyTestnet
from bit.network import NetworkAPI

load_dotenv()


class BitcoinWallet:
    def __init__(self, private_key: str = None, testnet: bool = False):
        """
        Initialize wallet.
        - private_key: WIF-format private key (None = generate new)
        - testnet: True = use testnet, False = mainnet
        """
        self.testnet = testnet
        key_class = PrivateKeyTestnet if testnet else Key

        if private_key:
            self.key = key_class(private_key)
        else:
            self.key = key_class()

    @property
    def address(self) -> str:
        return self.key.address

    @property
    def private_key_wif(self) -> str:
        return self.key.to_wif()

    def get_balance(self) -> dict:
        """Returns balance in BTC and satoshis."""
        balance_satoshi = self.key.get_balance()
        balance_btc = int(balance_satoshi) / 1e8
        return {
            "satoshis": int(balance_satoshi),
            "btc": balance_btc,
        }

    def get_transactions(self) -> list:
        """Returns recent transaction history."""
        try:
            if self.testnet:
                txs = NetworkAPI.get_transactions_testnet(self.address)
            else:
                txs = NetworkAPI.get_transactions(self.address)
            return txs
        except Exception as e:
            return []

    def send(self, recipient: str, amount_btc: float, fee: str = "medium") -> str:
        """
        Send BTC to a recipient address.
        - amount_btc: amount in BTC
        - fee: 'fast', 'medium', or 'slow'
        Returns transaction ID.
        """
        amount_satoshi = int(amount_btc * 1e8)
        outputs = [(recipient, amount_satoshi, "satoshi")]
        tx_id = self.key.send(outputs, fee=fee)
        return tx_id

    def to_dict(self) -> dict:
        return {
            "network": "testnet" if self.testnet else "mainnet",
            "address": self.address,
            "private_key_wif": self.private_key_wif,
        }


def create_new_wallet(testnet: bool = False) -> BitcoinWallet:
    """Generate a brand-new Bitcoin wallet."""
    return BitcoinWallet(testnet=testnet)


def load_wallet_from_env(testnet: bool = False) -> BitcoinWallet | None:
    """Load wallet from BTC_PRIVATE_KEY in .env."""
    pk = os.getenv("BTC_PRIVATE_KEY")
    if not pk:
        return None
    return BitcoinWallet(private_key=pk, testnet=testnet)
