#!/usr/bin/env python3
"""`^SOX` 能不能取代／延伸 `SOXX`——在動 gsy_runup 之前先問清楚。

## 為什麼要有這一支

`^SOX`（費城半導體指數）yfinance 回得到 **1994-05-04**，比 `SOXX` 這檔 ETF 的
2001-07-13 早了七年——涵蓋 **2000 年網通泡沫**，而那正是本儀表板門檻設定所類比的那一次。
事故檔把「SOXX 自己也回不到 2000」列為死路，這條路看起來通了。

**但 `^SOX` 是價格指數，`SOXX` 是 ETF，兩者不是同一條序列。**
拿 `^SOX` 校準、線上卻跑 `SOXX`，就是 MAINTENANCE §6.15 記過的那個錯誤的複製品：
*我們宣稱有校準的訊號，跟被校準的那個不是同一個。*

所以這一支不問「兩條線像不像」，問的是：
**在重疊的那 25 年裡，兩者會不會讓儀表板說出不同的話。**
比的是分數與燈號，不是相關係數——相關係數 0.99 也可以在門檻附近天天翻面。

## 它不做什麼

不寫 `data.json`、不改任何指標、不下結論說該換。它只把差異量出來。
換不換是看完數字之後的決定。

## 用法

放在 repo 的 `scripts/` 底下跑（要 import 引擎的 `pw()` 與 `data.json` 的錨點，
**不重抄一份**——重抄就是製造第二個會漂的定義）：

    cd <repo>/scripts && python3 sox_compare.py
"""
import json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import update_data as eng
except ImportError:
    sys.exit("找不到 update_data.py——這一支要放在 repo 的 scripts/ 底下跑")

RET24_BACK, ACCEL_BACK, YR = 505, 758, 253   # 與 eng.gsy_stats 一致，刻意照抄位移
ZONES = [(33, "綠"), (67, "黃"), (84, "橘"), (10**9, "紅")]


def fetch(sym):
    import yfinance as yf
    df = yf.Ticker(sym).history(period="max", interval="1d", auto_adjust=False)
    c = df["Close"].dropna()
    return [(d.date(), float(v)) for d, v in c.items() if v > 0]


def rolling(rows):
    """每一天的 ret24／accel，位移與 eng.gsy_stats 完全一致。"""
    dates = [d for d, _ in rows]; cl = [c for _, c in rows]
    out = {}
    for i in range(len(cl)):
        if i + 1 < RET24_BACK: continue
        r24 = (cl[i] / cl[i + 1 - RET24_BACK] - 1) * 100
        rec = {"ret24": r24}
        if i + 1 >= ACCEL_BACK:
            prior = (cl[i + 1 - YR] / cl[i + 1 - ACCEL_BACK] - 1) * 100
            rec["accel"] = r24 - prior
        out[dates[i]] = rec
    return out


def zone(s):
    for hi, name in ZONES:
        if s < hi: return name


def episodes(flagged, gap=90):
    """近乎連續的穿越是**同一段行情**，不是多次事件。
    2010 年那一段在 150% 上下擺盪，逐日計會數成十次。"""
    eps = []
    for d in flagged:
        if eps and (d - eps[-1][-1]).days <= gap: eps[-1].append(d)
        else: eps.append([d])
    return [e[0] for e in eps]


def independent(starts, horizon=730):
    """**出場端也要合併。** 兩次穿越相隔不到 24 個月，它們的前瞻窗幾乎完全重疊，
    崩盤與否是同一段資料——分開計就是把一個觀察值當成兩個。"""
    out = []
    for d in starts:
        if out and (d - out[-1]).days < horizon: continue
        out.append(d)
    return out


def pct(xs, q):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(len(xs) * q))]


def fwd_dd(rows, i, horizon=505):
    """從第 i 天起、往後 horizon 個交易日內，**窗內任一點**起算的最大回撤。
    §6.15 那次就是把起點寫成穿越當日，才產出一個看起來像結論的 0%。"""
    seg = [c for _, c in rows[i:i + horizon + 1]]
    if len(seg) < 20: return None
    peak, worst = seg[0], 0.0
    for c in seg:
        peak = max(peak, c)
        worst = min(worst, c / peak - 1)
    return worst * 100


def main():
    anchors = None
    dj = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.json")
    for it in json.load(open(dj, encoding="utf-8"))["indicators"]:
        if it["id"] == "gsy_runup": anchors = it["anchors"]
    if not anchors: sys.exit("data.json 裡找不到 gsy_runup 的錨點")
    print(f"gsy_runup 錨點（取自 data.json，未重抄）：{anchors}\n")

    rows = {}
    for s in ("^SOX", "SOXX"):
        rows[s] = fetch(s)
        print(f"{s:<8}{len(rows[s]):>6} 筆　{rows[s][0][0]} → {rows[s][-1][0]}")
    R = {s: rolling(v) for s, v in rows.items()}
    print(f"\n可算 ret24 的起點：^SOX {min(R['^SOX'])}　SOXX {min(R['SOXX'])}")

    common = sorted(set(R["^SOX"]) & set(R["SOXX"]))
    print(f"重疊 {len(common)} 天（{common[0]} → {common[-1]}）")

    # ---- 一、重疊期：兩者會不會讓儀表板說出不同的話 ----
    print("\n" + "=" * 78); print("一、重疊期比對（比的是分數與燈號，不是相關係數）"); print("=" * 78)
    dr, ds, zdiff, tdiff = [], [], 0, 0
    for d in common:
        a, b = R["^SOX"][d]["ret24"], R["SOXX"][d]["ret24"]
        sa, sb = eng.pw(a, anchors), eng.pw(b, anchors)
        dr.append(abs(a - b)); ds.append(abs(sa - sb))
        if zone(sa) != zone(sb): zdiff += 1
        if (a >= 150) != (b >= 150): tdiff += 1
    n = len(common)
    print(f"{'':<22}{'中位':>9}{'平均':>9}{'p90':>9}{'最大':>9}")
    print(f"{'|Δ ret24|（pp）':<22}{pct(dr,.5):>9.1f}{sum(dr)/n:>9.1f}{pct(dr,.9):>9.1f}{max(dr):>9.1f}")
    print(f"{'|Δ 分數|（分）':<22}{pct(ds,.5):>9.1f}{sum(ds)/n:>9.1f}{pct(ds,.9):>9.1f}{max(ds):>9.1f}")
    print(f"\n燈號不同的天數　{zdiff:>5} / {n}　（{zdiff/n:.2%}）")
    print(f"gsy150 判定不同　{tdiff:>5} / {n}　（{tdiff/n:.2%}）")
    for thr in [a[0] for a in anchors]:
        k = sum(1 for d in common if (R["^SOX"][d]["ret24"] >= thr) != (R["SOXX"][d]["ret24"] >= thr))
        print(f"  錨點 {thr:>3}% 兩側判定不同：{k:>5} 天（{k/n:.2%}）")

    # ---- 二、SOXX 看不到的那一段 ----
    print("\n" + "=" * 78); print("二、只有 ^SOX 看得到的那一段（SOXX 之前）"); print("=" * 78)
    pre = [d for d in sorted(R["^SOX"]) if d < min(R["SOXX"])]
    if not pre:
        print("沒有額外涵蓋期間")
    else:
        print(f"{pre[0]} → {pre[-1]}　{len(pre)} 天　"
              f"（SOXX 完全看不到，含 2000 年網通泡沫）")
        idx = {d: i for i, (d, _) in enumerate(rows["^SOX"])}
        hot = [d for d in pre if eng.pw(R["^SOX"][d]["ret24"], anchors) >= 84]
        peaks = independent(episodes(hot))
        print(f"\n進入紅燈（分數 ≥84）的獨立段落 {len(peaks)} 次"
              f"（原始天數 {len(hot)}，合併後才是事件數）")
        print("段落起日      該段峰值   峰值分數  峰日          峰後24月最大回撤")
        for k, st in enumerate(peaks):
            nxt = peaks[k + 1] if k + 1 < len(peaks) else None
            seg = [d for d in pre if d >= st and (nxt is None or d < nxt)]
            pk = max(seg, key=lambda d: R["^SOX"][d]["ret24"])
            r = R["^SOX"][pk]["ret24"]; dd = fwd_dd(rows["^SOX"], idx[pk])
            print(f"{str(st):<12}{r:>10.1f}{eng.pw(r, anchors):>10.1f}  {str(pk):<12}"
                  f"{(f'{dd:.1f}%' if dd is not None else '窗未走完'):>14}")

    # ---- 三、全樣本的 gsy150 事件 ----
    print("\n" + "=" * 78); print("三、^SOX 全樣本的 gsy150 穿越事件"); print("=" * 78)
    idx = {d: i for i, (d, _) in enumerate(rows["^SOX"])}
    ds_all = sorted(R["^SOX"])
    flagged = [d for d in ds_all if R["^SOX"][d]["ret24"] >= 150]
    raw = episodes(flagged)
    ev = independent(raw)
    print(f"逐日在 150% 之上 {len(flagged)} 天　→ 合併相鄰段落 {len(raw)} 段"
          f"　→ 前瞻窗不重疊的獨立事件 **{len(ev)}** 次")
    print("中間那兩步不能省：同一段行情在門檻上下擺盪會被數成十幾次，"
          "而相隔不到 24 個月的兩次穿越，崩盤與否看的是同一段資料。")
    print(f"{'穿越日':<12}{'ret24':>9}{'後24月最大回撤':>16}{'≥40%?':>8}")
    hits = 0
    for d in ev:
        dd = fwd_dd(rows["^SOX"], idx[d])
        if dd is not None and dd <= -40: hits += 1
        print(f"{str(d):<12}{R['^SOX'][d]['ret24']:>9.1f}"
              f"{(f'{dd:.1f}%' if dd is not None else '窗未走完'):>16}"
              f"{('是' if dd is not None and dd <= -40 else '否'):>8}")
    if ev:
        print(f"\n崩盤率 {hits}/{len(ev)}　文獻（Greenwood-Shleifer-You）在 150% 組是 80%")
        print("**事件數是個位數，這只能說「與文獻方向一致／不一致」，不可能是統計顯著性。**")

    out = {"overlap": {"n": n, "median_dret": pct(dr, .5), "max_dret": max(dr),
                       "median_dscore": pct(ds, .5), "max_dscore": max(ds),
                       "zone_diff": zdiff, "trig_diff": tdiff},
           "sox_first": str(rows["^SOX"][0][0]), "soxx_first": str(rows["SOXX"][0][0]),
           "gsy150_days": len(flagged), "gsy150_runs": len(raw),
           "gsy150_events": [str(d) for d in ev]}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sox_compare.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {os.path.abspath(p)}")


if __name__ == "__main__":
    main()
