#!/usr/bin/env python3
"""senti 換血前的量測：候選序列的分佈、漂移、以及跟現有輸入的重複度。

## 為什麼先量

`senti` 目前四個輸入只有三個活著（AAII 永久被擋），而錨點是專家判斷。
要改它有兩件事必須先知道，兩件都不能靠推理得出：

1. **錨點該設在哪。** 這一族序列有 15–36 年歷史，門檻可以**從分佈算出來**
   而不是猜。但分佈會漂——`^SKEW` 有記錄在案的長期上飄——所以要**逐十年**看，
   不能只看全樣本。全樣本分位數設出來的固定門檻，若各十年差很多，
   等於用 1990 年代的尺量 2026 年。
2. **會不會變成一個 VIX 合成指標。** `senti` 是等權平均。現在四個輸入裡
   VIX 已經佔一個，而 CNN F&G 的七個成分本身就含 VIX（規格已承認這是接受的重複）。
   再加期限結構、VVIX、SKEW 三個波動率家族的東西，就會變成 6/7 都是波動率——
   **那時它量的不再是情緒，是 VIX 的三種切法**，而名字不會改。
   所以要先看相關矩陣。

## 它不做什麼

不寫 `data.json`、不改任何指標、不下結論說要接哪幾個。只把數字攤開。

## 用法

    cd <repo>/scripts && python3 senti_calib.py
"""
import json, os, sys, time

CAND = [
    ("^VIX",    "VIX 水位",        "低＝自滿＝熱"),
    ("^VIX9D",  "9 日 VIX",        "配期限結構用"),
    ("^VIX3M",  "3 月 VIX",        "配期限結構用"),
    ("^VVIX",   "波動的波動",       "低＝自滿＝熱"),
    ("^SKEW",   "尾部風險定價",     "方向待定，見輸出"),
]
GRID = [5, 10, 25, 33, 50, 67, 75, 90, 95]


def pull(yf, sym):
    df = yf.Ticker(sym).history(period="max", interval="1d", auto_adjust=False)
    c = df["Close"]
    n_raw = len(c)
    c = c.dropna()
    return c, n_raw


def pcts(vals, grid=GRID):
    v = sorted(vals); n = len(v)
    return [v[min(n - 1, int(n * g / 100))] for g in grid]


def main():
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        sys.exit("需要 yfinance 與 pandas")

    S, meta = {}, {}
    print("=" * 88); print("零、取值與尾端 NaN"); print("=" * 88)
    print("**這一節是這支程式最重要的一節。** 探針顯示 ^VIX9D／^VIX3M 的最後一列是 NaN——")
    print("序列 99.97% 完整，而唯一缺的那天正好是日更儀表板唯一會讀的那天。")
    print(f"\n{'序列':<10}{'原始列':>8}{'去NaN':>8}{'尾端NaN':>9}{'最後有值日':>13}{'最後值':>10}")
    for sym, name, _ in CAND:
        try:
            c, n_raw = pull(yf, sym)
            S[sym] = c
            gap = n_raw - len(c)
            print(f"{sym:<10}{n_raw:>8}{len(c):>8}{gap:>9}"
                  f"{str(c.index[-1].date()):>13}{c.iloc[-1]:>10.2f}")
            meta[sym] = str(c.index[-1].date())
        except Exception as e:
            print(f"{sym:<10}  失敗：{e.__class__.__name__}: {str(e)[:50]}")
        time.sleep(0.8)
    if len(S) < 2: sys.exit("取到的序列太少")

    dates = {v: meta[v] for v in meta}
    if len(set(dates.values())) > 1:
        print(f"\n**各序列的最後有值日不一致**：{dates}")
        print("接進引擎時，asof 要填該序列自己那一天，不是今天——"
              "填今天就是對使用者謊報新鮮度（§8.4 的通則）。")

    # 衍生：期限結構
    if "^VIX9D" in S and "^VIX" in S:
        a, b = S["^VIX9D"].align(S["^VIX"], join="inner")
        S["TS9D"] = a / b
        CAND.append(("TS9D", "期限結構 9D/30D", "<1 為正價差＝平靜＝熱"))
    if "^VIX" in S and "^VIX3M" in S:
        a, b = S["^VIX"].align(S["^VIX3M"], join="inner")
        S["TS3M"] = a / b
        CAND.append(("TS3M", "期限結構 30D/3M", "<1 為正價差＝平靜＝熱"))

    print("\n" + "=" * 88); print("一、全樣本分位數（固定錨點要從這裡設，不是用猜的）"); print("=" * 88)
    hdr = "".join(f"{g:>8}" for g in GRID)
    print(f"{'序列':<10}{'起':>12}{'年':>6}" + hdr)
    for sym, name, _ in CAND:
        if sym not in S: continue
        c = S[sym]
        yrs = (c.index[-1] - c.index[0]).days / 365.25
        row = "".join(f"{x:>8.2f}" for x in pcts(c.values))
        print(f"{sym:<10}{str(c.index[0].date()):>12}{yrs:>6.1f}" + row)

    print("\n" + "=" * 88); print("二、逐十年分位數（分佈有沒有漂）"); print("=" * 88)
    print("固定門檻的前提是分佈穩定。若各十年的中位數差很多，"
          "全樣本設出來的門檻等於用舊尺量新市場。")
    for sym, name, _ in CAND:
        if sym not in S: continue
        c = S[sym]
        print(f"\n{sym}（{name}）")
        print(f"{'十年':<10}{'天':>7}{'p10':>9}{'中位':>9}{'p90':>9}")
        for dec in (1990, 2000, 2010, 2020):
            seg = c[(c.index.year >= dec) & (c.index.year < dec + 10)]
            if len(seg) < 200: continue
            p = pcts(seg.values, [10, 50, 90])
            print(f"{dec}s{'':<5}{len(seg):>7}{p[0]:>9.2f}{p[1]:>9.2f}{p[2]:>9.2f}")

    print("\n" + "=" * 88); print("三、相關矩陣（會不會變成一個 VIX 合成指標）"); print("=" * 88)
    keys = [k for k, _, _ in CAND if k in S]
    df = pd.DataFrame({k: S[k] for k in keys}).dropna()
    print(f"重疊 {len(df)} 天（{df.index[0].date()} → {df.index[-1].date()}）")
    print("\n水位的相關係數：")
    print(df.corr().round(2).to_string())
    print("\n20 日變化的相關係數（水位會被共同趨勢灌水，變化比較誠實）：")
    print(df.pct_change(20).dropna().corr().round(2).to_string())
    print("\n**任兩項的水位相關 >0.8，就是同一件事量兩次。**"
          "\n等權平均裡塞兩個高度相關的輸入，等於偷偷給它雙倍權重——"
          "而規格 §6.6 刻意不設個別權重，就是為了避免這種暗權重。")

    print("\n" + "=" * 88); print("四、從分位數推出的建議錨點"); print("=" * 88)
    print("格式照 pw()：[[值, 分數], ...]，分數愈高愈熱。")
    print("**方向是判斷，不是資料能決定的**——這裡兩個方向都印，接哪個要寫進 §4.1。")
    prop = {}
    for sym, name, note in CAND:
        if sym not in S: continue
        p = pcts(S[sym].values, [10, 33, 67, 90])
        inv = [[round(float(p[3]), 2), 0], [round(float(p[2]), 2), 33],
               [round(float(p[1]), 2), 67], [round(float(p[0]), 2), 100]]
        fwd = [[round(float(p[0]), 2), 0], [round(float(p[1]), 2), 33],
               [round(float(p[2]), 2), 67], [round(float(p[3]), 2), 100]]
        prop[sym] = {"invert": inv, "forward": fwd, "now": round(float(S[sym].iloc[-1]), 2)}
        print(f"\n{sym}（{name}）　現值 {S[sym].iloc[-1]:.2f}　{note}")
        print(f"  低值＝熱（invert）：{inv}")
        print(f"  高值＝熱（forward）：{fwd}")

    out = {"asof": meta, "proposed": prop}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "senti_calib.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {os.path.abspath(p)}")


if __name__ == "__main__":
    main()
