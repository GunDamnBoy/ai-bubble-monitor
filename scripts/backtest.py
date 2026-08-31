#!/usr/bin/env python3
"""回測第一階段：驗 `gsy_runup` 那組唯一有文獻校準的錨點。

**為什麼是這一項先做**：22 個指標的錨點裡，只有 `gsy_runup` 宣稱有機率意義
（Greenwood-Shleifer, JFE 2019：產業 24 個月漲幅 ≥100% → 其後 24 個月崩盤機率 53%、
≥150% → 80%）。它同時是整個模型「泡沫」判斷的支點。**如果連它都驗不出來，
其餘 21 項的專家判斷就更沒有立足點**——所以第一階段只做它，做完再決定要不要往下走。

**這支腳本不在雲端工作階段跑**：覆核／維護容器的 Bash 連不到 Yahoo／Stooq／FRED
（`AGENT_BRIEF.md` §8.3 的兩條路對照表），只有 GitHub Actions runner 有網路。
所以它是 `workflow_dispatch` 手動觸發的一次性作業，**不進每日排程、不碰 `data.json`**。

**範圍上的硬限制**（2026-08-17 逐一查證，見 `MAINTENANCE.md` §5 的回測待辦）：
- SOXX 這檔 ETF 2001-07-10 才成立，加上 24 個月窗 → **`gsy_runup` 最早只能算到 2003-07**。
  也就是說它自己也回不到 2000 年網通泡沫——用它的門檻談 2000 年，永遠是專家判斷。
- 因此本階段能檢驗的事件是 2008、2020、2022（外加 2018Q4 與 2015-16 的兩次修正）。
- 樣本數會很小（門檻穿越次數個位數），**結論只能是「與文獻方向一致／不一致」，
  不可能是統計顯著性**。這一點要寫在結論裡，不要事後假裝樣本夠。

**崩盤定義有兩種，都要算**（v2，2026-08-17 第一輪之後補）：從穿越當日起算的跌幅，
與窗內從高點起算的最大回撤。第一輪只做前者，結果 0/16——但其中兩次是 −39.74% 與
−39.51%，差 0.3–0.5pp 沒跨過門檻。**用一條寫錯的定義得到的 0%，比沒有結果更危險**，
因為它看起來像個結論。文獻用的是哪一種待核對（見 REPORT），在核對之前兩種並列。

輸出：`backtest/gsy_runup.json`（逐日序列＋穿越事件＋兩種前瞻跌幅＋獨立事件分組）。
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "backtest"
sys.path.insert(0, str(ROOT / "scripts"))

import update_data as eng   # noqa: E402  重用引擎的抓取與統計，不另寫第二份

WINDOW_TRADING_DAYS = 505       # 約 24 個月，與 gsy_stats 同一個定義
FIVE_YEAR_DAYS = 1260           # 約 5 年
FIVE_YEAR_MIN = 50.0            # 論文的第三個條件：5 年 raw ≥50%
FORWARD_DAYS = 505              # 其後 24 個月
THRESHOLDS = [100.0, 150.0]
LIT = {100.0: 53.0, 150.0: 80.0}      # 美國產業組合，Table 3 Panel A
LIT_BASE = 14.0                       # 無條件崩盤率（1928–2013 全部 industry-months；1970 後 11%）
CRASH_DRAWDOWN = -40.0

# 論文（Greenwood-Shleifer-You, NBER WP 23191 / JFE 2019）的定義，2026-08-17 逐句核對過：
#
# run-up：過去 2 年 **raw ≥ 門檻 且 net-of-market ≥ 門檻**，再加過去 5 年 raw ≥50%
#         （p.7；5 年那個條件正文寫 50%、Table 1/2 表註寫 100%，取正文並在此標明差異）
# crash： 「a 40 percent or more drawdown in absolute terms beginning at any point after
#         we have first identified the price increase」（p.9）——**回撤的起點是窗內任一點**，
#         等價於識別日後 24 個月的最大回撤 ≥40%。
# 樣本： 美國 Fama-French 48 產業、**每個產業至少 10 家公司**（p.8，刻意排除少數公司驅動的情形）、
#         市值加權月報酬，可識別區間 1928-01～2012-03。
#
# **論文全文找不到任何把這套機率套用到單一 ETF 或個股的討論**。SOXX 是 ETF 不是 CRSP 市值加權
# 產業組合，這一步外推是我們自己做的，不是論文說的——結論裡要標成 assumption。


def series(sym="SOXX", stooq_sym="soxx.us"):
    """拿盡量長的日收盤序列。三層備援與引擎同一支，命中哪一層記在 PX_HIT。"""
    for rng in ("max", "25y", "20y"):
        try:
            rows = eng.px_rows(sym, stooq_sym, rng=rng)
            if len(rows) > 2000:
                return rows, rng, eng.PX_HIT.get(sym)
        except Exception as ex:
            print(f"  {sym} rng={rng} 失敗：{str(ex)[:80]}")
    raise RuntimeError(f"{sym}: 拿不到夠長的序列")


def run24(closes, i):
    """第 i 個交易日當下的「24 個月漲幅 %」。資料不足回 None。"""
    if i < WINDOW_TRADING_DAYS:
        return None
    return (closes[i] / closes[i - WINDOW_TRADING_DAYS] - 1) * 100


def forward_from_entry(closes, i):
    """其後 24 個月的最大跌幅 %，**相對於穿越當日的收盤價**。

    窗不完整回 None——不足的窗一律排除，不要拿「到目前為止」的部分窗當成完整
    結果，那會系統性低估跌幅（近期的點永遠還沒跌完）。
    """
    j = i + FORWARD_DAYS
    if j >= len(closes):
        return None
    w = closes[i + 1:j + 1]
    return (min(w) / closes[i] - 1) * 100


def forward_drawdown(closes, i):
    """其後 24 個月內的**最大回撤** %：從窗內的高點跌到其後的低點。

    **這一版才對得上文獻的定義**（待核對，見 REPORT）。第一輪回測用的是
    `forward_from_entry`——從穿越當日起算——而價格若在穿越後繼續漲一段再跌，
    那個算法會系統性低估跌幅。2026-08-17 第一輪的結果就卡在這裡：2022-02-02
    的穿越算出 −39.74%、2024-06-17 算出 −39.51%，兩次都差 0.3–0.5 個百分點
    沒跨過 −40% 的門檻，而那個差距是雜訊、不是訊號。**兩種定義都算、並列輸出，
    不要只留一個**——差異本身就是結論的一部分。
    """
    j = i + FORWARD_DAYS
    if j >= len(closes):
        return None
    peak = closes[i]
    worst = 0.0
    for c in closes[i + 1:j + 1]:
        if c > peak:
            peak = c
        dd = (c / peak - 1) * 100
        if dd < worst:
            worst = dd
    return worst


def episodes(evs, gap_days=365):
    """把穿越事件收攏成**獨立事件**。

    2026-08-17 第一輪算出 100% 門檻「穿越 19 次」，但 2018 一年就佔 5 次、
    2022 佔 3 次——它們是同一波行情的重複計數。把相隔不到一年的併成一個事件，
    才知道真正的樣本數（第一輪的 19 次其實只有約 5 個獨立事件）。
    """
    out = []
    for e in evs:
        d = dt.date.fromisoformat(e["d"])
        if out and (d - dt.date.fromisoformat(out[-1][-1]["d"])).days <= gap_days:
            out[-1].append(e)
        else:
            out.append([e])
    return out


def main():
    OUT.mkdir(exist_ok=True)
    print("抓 SOXX 日收盤序列…")
    rows, rng, hit = series()
    dates = [d for d, _ in rows]
    closes = [c for _, c in rows]
    print(f"  {len(rows)} 筆，{dates[0]} → {dates[-1]}（rng={rng}，來源 {hit}）")

    print("抓 SPY 當大盤基準（論文用 CRSP 市值加權全市場，這裡以 SPY 代理）…")
    mrows, mrng, mhit = series("SPY", "spy.us")
    mkt = {d: c for d, c in mrows}
    print(f"  {len(mrows)} 筆，{mrows[0][0]} → {mrows[-1][0]}（rng={mrng}，來源 {mhit}）")

    def mkt_run24(i):
        """同期大盤 24 月漲幅。對不到交易日就回 None——**不要用鄰近日硬湊**，
        對不上就是這一天不判定，寧可少一個觀測。"""
        if i < WINDOW_TRADING_DAYS:
            return None
        a, b = mkt.get(dates[i]), mkt.get(dates[i - WINDOW_TRADING_DAYS])
        return (a / b - 1) * 100 if a and b else None

    def run5y(i):
        if i < FIVE_YEAR_DAYS:
            return None
        return (closes[i] / closes[i - FIVE_YEAR_DAYS] - 1) * 100

    daily = []
    for i in range(len(rows)):
        r = run24(closes, i)
        if r is None:
            continue
        m = mkt_run24(i)
        r5 = run5y(i)
        daily.append({"d": dates[i].isoformat(), "close": round(closes[i], 4),
                      "ret24": round(r, 2),
                      "score": round(eng.pw(r, [[25, 0], [50, 25], [100, 60], [150, 85], [250, 100]]), 1),
                      "mkt24": round(m, 2) if m is not None else None,
                      "net24": round(r - m, 2) if m is not None else None,
                      "ret5y": round(r5, 2) if r5 is not None else None,
                      "fwd24_from_entry": (lambda v: round(v, 2) if v is not None else None)(forward_from_entry(closes, i)),
                      "fwd24_drawdown": (lambda v: round(v, 2) if v is not None else None)(forward_drawdown(closes, i))})

    # 門檻穿越：只取「由下往上穿過」的那一天，避免同一波行情被重複計數
    def qualifies(row, th, strict):
        """strict=False：現行指標的做法（只看 SOXX 自己的 24 月漲幅）。
        strict=True：論文的三條件（raw、net-of-market、5 年）全部要過。"""
        if row["ret24"] < th:
            return False
        if not strict:
            return True
        return (row["net24"] is not None and row["net24"] >= th
                and row["ret5y"] is not None and row["ret5y"] >= FIVE_YEAR_MIN)

    events = {}
    for th in THRESHOLDS:
      for strict in (False, True):
        key = f"{th}{'｜論文三條件' if strict else '｜現行指標(只看raw)'}"
        evs, armed = [], True
        for k, row in enumerate(daily):
            if qualifies(row, th, strict) and armed:
                evs.append({"d": row["d"], "ret24": row["ret24"], "net24": row["net24"],
                            "ret5y": row["ret5y"],
                            "fwd24_from_entry": row["fwd24_from_entry"],
                            "fwd24_drawdown": row["fwd24_drawdown"]})
                armed = False
            elif row["ret24"] < th * 0.9:      # 回落 10% 以下才重新武裝
                armed = True
        eps = episodes(evs)
        done = [e for e in evs if e["fwd24_drawdown"] is not None]
        # 兩種定義各算一次；差異本身就是結論的一部分
        crash_dd = [e for e in done if e["fwd24_drawdown"] <= CRASH_DRAWDOWN]
        crash_en = [e for e in done if e["fwd24_from_entry"] <= CRASH_DRAWDOWN]
        # 獨立事件層級：同一波行情只算一次，該波內任一穿越崩盤就算崩盤
        ep_done = [g for g in eps if any(e["fwd24_drawdown"] is not None for e in g)]
        ep_crash = [g for g in ep_done
                    if any(e["fwd24_drawdown"] is not None and e["fwd24_drawdown"] <= CRASH_DRAWDOWN for e in g)]
        events[key] = {
            "穿越次數": len(evs),
            "獨立事件數": len(eps),
            "窗已走完（穿越）": len(done),
            "窗已走完（獨立事件）": len(ep_done),
            "崩盤_從高點回撤": len(crash_dd),
            "崩盤_從穿越日起算": len(crash_en),
            "實測崩盤率%_從高點回撤": round(100 * len(crash_dd) / len(done), 1) if done else None,
            "實測崩盤率%_從穿越日起算": round(100 * len(crash_en) / len(done), 1) if done else None,
            "實測崩盤率%_獨立事件": round(100 * len(ep_crash) / len(ep_done), 1) if ep_done else None,
            "文獻崩盤率%": LIT[th],
            "文獻無條件基準%": LIT_BASE,
            "事件": evs,
            "獨立事件": [[e["d"] for e in g] for g in eps],
        }

    res = {"symbol": "SOXX", "market_proxy": "SPY", "rows": len(rows),
           "from": dates[0].isoformat(), "to": dates[-1].isoformat(), "source": hit,
           "定義": {"run-up": "論文：raw 2y ≥門檻 且 net-of-market 2y ≥門檻 且 raw 5y ≥50%；"
                             "現行指標只有第一個條件",
                   "crash": "識別日後 24 個月內最大回撤 ≥40%（回撤起點為窗內任一點）",
                   "已知外推": "論文的單位是 ≥10 家公司的 CRSP 市值加權產業組合，"
                              "全文未討論套用到單一 ETF；SOXX 這一步是我們的假設，不是論文說的"}, "window_trading_days": WINDOW_TRADING_DAYS, "forward_days": FORWARD_DAYS,
           "crash_drawdown_pct": CRASH_DRAWDOWN, "events": events, "daily": daily}
    (OUT / "gsy_runup.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"寫出 backtest/gsy_runup.json（{len(daily)} 筆日觀測）")
    for key, e in events.items():
        print(f"  {key}：穿越 {e['穿越次數']} 次／獨立事件 {e['獨立事件數']} 個｜窗走完 "
              f"{e['窗已走完（穿越）']}／{e['窗已走完（獨立事件）']}")
        print(f"    崩盤率（從高點回撤・論文定義）{e['實測崩盤率%_從高點回撤']}%｜"
              f"（從穿越日起算・第一輪的錯誤定義）{e['實測崩盤率%_從穿越日起算']}%｜"
              f"（獨立事件）{e['實測崩盤率%_獨立事件']}%"
              f"　vs 文獻 {e['文獻崩盤率%']}%（無條件基準 {e['文獻無條件基準%']}%）")


if __name__ == "__main__":
    main()
