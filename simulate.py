"""
Portfolio future value simulation
Starting from current Binance portfolio value.
"""

INITIAL_USD = 7134  # current portfolio
JPY_RATE = 160      # approximate

scenarios = {
    "慎重 (年+10%)":   0.10,
    "普通 (年+20%)":   0.20,
    "楽観 (年+30%)":   0.30,
    "BTC歴史平均(~40%)": 0.40,
}

years = [1, 5, 10, 20, 30, 50]

print(f"\n{'='*70}")
print(f"  ポートフォリオ将来価値シミュレーション")
print(f"  初期投資: ${INITIAL_USD:,} (約{INITIAL_USD * JPY_RATE / 10000:.0f}万円)")
print(f"{'='*70}")

for label, rate in scenarios.items():
    print(f"\n  [{label}]")
    print(f"  {'年数':>6}  {'USD':>16}  {'円':>16}  {'元手比'}  {'メモ'}")
    print(f"  {'-'*70}")
    for y in years:
        val = INITIAL_USD * (1 + rate) ** y
        jpy = val * JPY_RATE
        mult = val / INITIAL_USD

        # milestone notes
        note = ""
        if val >= 1_000_000_000: note = "100億ドル超"
        elif val >= 100_000_000: note = "10億ドル超"
        elif val >= 10_000_000:  note = "1億ドル超"
        elif val >= 1_000_000:   note = "100万ドル超 (億り人)"
        elif val >= 100_000:     note = "10万ドル超"

        print(f"  {y:>5}年  ${val:>14,.0f}  {jpy/10000:>12,.0f}万円  x{mult:>6.1f}  {note}")

print(f"""
{'='*70}
  税金シナリオ比較（50年後・楽観シナリオで$7,000万になった場合）
{'='*70}

  日本で売る場合:
    利益 = $70,000,000
    税金 (最大55%) = $38,500,000
    手取り = $31,500,000 (約50億円)

  ドバイで売る場合 (UAE = 非課税):
    利益 = $70,000,000
    税金 0%
    手取り = $70,000,000 (約112億円)

  差額: 約$38,500,000 (62億円) <- これが税金戦略の価値
{'='*70}

  ※ これは単純複利計算です。実際の価格は大きく変動します。
  ※ 過去のBTC年間リターンは非常に高かったが、将来を保証しません。
  ※ ドバイ移住には居住要件があります（年183日以上滞在など）。
""")
