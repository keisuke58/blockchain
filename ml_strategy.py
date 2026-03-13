"""
ML Trading Strategy (Random Forest)
Usage:
  python ml_strategy.py                    # Train on BTC 1y data + backtest
  python ml_strategy.py --symbol ETHUSDT   # Different symbol
  python ml_strategy.py --days 365         # Training period
  python ml_strategy.py --capital 70000    # Capital

Model saved to logs/ml_model_{symbol}.pkl
"""

import argparse
import os
import pickle
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import classification_report
from colorama import init, Fore, Style
from tabulate import tabulate

import bot as b

init(autoreset=True)

JPY_RATE = 148.0


# ── Feature engineering ──────────────────────────────────────

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    feat = pd.DataFrame(index=df.index)

    # Price momentum
    for p in [1, 3, 6, 12, 24]:
        feat[f"ret_{p}h"] = df["close"].pct_change(p)

    # RSI
    feat["rsi"] = df["rsi"]
    feat["rsi_slope"] = df["rsi"].diff(3)

    # EMA ratio
    feat["ema_ratio"] = df["ema20"] / df["ema50"] - 1

    # Bollinger Band position
    bb_width = df["bb_upper"] - df["bb_lower"]
    feat["bb_pos"]   = (df["close"] - df["bb_lower"]) / (bb_width + 1e-9)
    feat["bb_width"] = bb_width / df["close"]

    # Volume
    feat["vol_ratio"] = df["volume"] / df["volume"].rolling(24).mean()

    # Volatility
    feat["volatility"] = df["close"].pct_change().rolling(12).std()

    # High/Low range
    feat["hl_ratio"] = (df["high"] - df["low"]) / df["close"]

    return feat.dropna()


def build_labels(df: pd.DataFrame, horizon: int = 3, threshold: float = 0.005) -> pd.Series:
    """
    Label: 1 if price rises > threshold in next `horizon` candles
           -1 if price falls > threshold
            0 otherwise (skip these in training)
    """
    future_ret = df["close"].shift(-horizon) / df["close"] - 1
    labels = pd.Series(0, index=df.index)
    labels[future_ret >  threshold] =  1
    labels[future_ret < -threshold] = -1
    return labels


# ── Train ────────────────────────────────────────────────────

def train(symbol: str, days: int) -> RandomForestClassifier:
    print(f"  Fetching {days} days of {symbol} data...")
    df = b.fetch_ohlcv(symbol=symbol, days=days)
    df = b.add_indicators(df)

    X = build_features(df)
    y = build_labels(df).loc[X.index]

    # Only use clear signals (drop neutral)
    mask = y != 0
    X_filtered = X[mask]
    y_filtered = y[mask]

    print(f"  Samples : {len(X_filtered)}  (buy={int((y_filtered==1).sum())}, sell={int((y_filtered==-1).sum())})")

    # Time-series cross-validation (no lookahead bias)
    tscv = TimeSeriesSplit(n_splits=5)
    scores = []

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=20,
        random_state=42,
        class_weight="balanced",
    )

    print("  Cross-validating (TimeSeriesSplit)...")
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X_filtered)):
        X_tr, X_val = X_filtered.iloc[train_idx], X_filtered.iloc[val_idx]
        y_tr, y_val = y_filtered.iloc[train_idx], y_filtered.iloc[val_idx]
        model.fit(X_tr, y_tr)
        acc = model.score(X_val, y_val)
        scores.append(acc)
        print(f"    Fold {fold+1}: accuracy = {acc:.3f}")

    print(f"  Mean CV accuracy: {Fore.GREEN}{np.mean(scores):.3f}{Style.RESET_ALL}  "
          f"(random baseline ~0.500)")

    # Final fit on all data
    model.fit(X_filtered, y_filtered)

    # Feature importance
    importances = sorted(
        zip(X.columns, model.feature_importances_),
        key=lambda x: x[1], reverse=True
    )[:8]
    print()
    print("  Top features:")
    for feat, imp in importances:
        bar = "#" * int(imp * 100)
        print(f"    {feat:<15} {bar}  {imp:.3f}")

    return model


# ── ML Backtest ──────────────────────────────────────────────

def backtest_ml(df: pd.DataFrame, model, capital: float) -> dict:
    X = build_features(df)
    df_aligned = df.loc[X.index]

    preds = model.predict(X)
    proba = model.predict_proba(X)
    confidence = proba.max(axis=1)

    # Only trade on high-confidence signals
    signals = pd.Series(0, index=X.index)
    for i in range(len(signals)):
        if confidence[i] >= 0.60:
            signals.iloc[i] = int(preds[i])

    return b.backtest(df_aligned, signals, capital)


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",  default="BTCUSDT")
    parser.add_argument("--days",    type=int,   default=365)
    parser.add_argument("--capital", type=float, default=70000.0)
    args = parser.parse_args()

    print(f"\n{Fore.YELLOW}{'='*60}")
    print(f"  ML Strategy Trainer  |  {args.symbol}  |  {args.days} days")
    print(f"{'='*60}{Style.RESET_ALL}")

    model = train(args.symbol, args.days)

    # Save model
    os.makedirs("logs", exist_ok=True)
    model_file = f"logs/ml_model_{args.symbol}.pkl"
    with open(model_file, "wb") as f:
        pickle.dump(model, f)
    print(f"\n  Model saved to {Fore.GREEN}{model_file}{Style.RESET_ALL}")

    # Backtest ML vs Hold
    print(f"\n  Backtesting on last 90 days...")
    df90  = b.fetch_ohlcv(symbol=args.symbol, days=90)
    df90  = b.add_indicators(df90)

    ml_result   = backtest_ml(df90, model, args.capital)
    hold_result = b.backtest(df90, b.strategy_hold(df90), args.capital)

    rows = []
    for name, r in [("ML (60% conf)", ml_result), ("Hold", hold_result)]:
        color = Fore.GREEN if r["pnl_usd"] >= 0 else Fore.RED
        rows.append([
            name,
            f"${r['final_usd']:>10,.0f}",
            f"{color}{r['pnl_pct']:>+.1f}%{Style.RESET_ALL}",
            f"{color}${r['pnl_usd']:>+,.0f}{Style.RESET_ALL}",
            f"JPY {r['pnl_usd'] * JPY_RATE:>+,.0f}",
            f"{r['max_dd']:.1f}%",
            f"{r['sharpe']:.2f}",
            str(r["trades"]),
        ])

    print()
    print(tabulate(rows,
        headers=["Strategy", "Final(USD)", "Return%", "PnL(USD)", "PnL(JPY)",
                 "MaxDD", "Sharpe", "Trades"]))

    print(f"\n  Capital : ${args.capital:,.0f}  (JPY {args.capital * JPY_RATE:,.0f})")
    print(f"\n  {Fore.CYAN}To use this model in paper trading:{Style.RESET_ALL}")
    print(f"    python paper_trade.py --strategy ml --symbol {args.symbol}")
    print(f"\n  {Fore.YELLOW}Warning: ML models overfit easily. Always paper trade first.{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
