# Bitcoin Wallet + Binance Integration

Python製のBitcoinウォレット。Binance APIとの連携で残高・価格・取引履歴も確認できます。

## Features

- Bitcoin アドレス生成（Mainnet / Testnet）
- ウォレット残高確認
- BTC/USDT リアルタイム価格取得（Binance）
- Binance アカウント残高表示
- Binance BTC 取引履歴
- BTC 送金（Testnet）

## Setup

```bash
# 依存パッケージをインストール
pip install -r requirements.txt

# .env を作成
cp .env.example .env
# .env に Binance API キーを設定
```

## Usage

```bash
# 新しいウォレットを生成
python cli.py new

# ウォレット情報を表示
python cli.py info

# BTC 残高を確認
python cli.py balance

# BTC/USDT 価格を確認（Binance）
python cli.py price

# Binance アカウント残高
python cli.py binance

# Binance BTC 取引履歴
python cli.py history

# BTC を送金（Testnet）
python cli.py send <address> <amount_btc>
```

## Security

- 秘密鍵は `.env` ファイルで管理し、**絶対に Git にコミットしない**
- `.gitignore` に `.env` を含めています
- 本番（Mainnet）での送金前に必ず Testnet でテストすること

## Structure

```
blockchain/
├── wallet.py        # Bitcoin ウォレットコア（bit ライブラリ）
├── binance_api.py   # Binance API 連携
├── cli.py           # コマンドラインインターフェース
├── requirements.txt # 依存パッケージ
├── .env.example     # 環境変数テンプレート
└── .gitignore
```
