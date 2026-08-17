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

輸出：`backtest/gsy_runup.json`（逐日序列＋穿越事件＋前瞻跌幅），與 `backtest/REPORT.md`。
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
FORWARD_DAYS = 505              # 其後 24 個月
THRESHOLDS = [100.0, 150.0]     # 文獻的兩個門檻
LIT = {100.0: 53.0, 150.0: 80.0}   # 文獻宣稱的其後 24 月崩盤機率 %
CRASH_DRAWDOWN = -40.0          # Greenwood-Shleifer 的「崩盤」定義：其後 24 月內跌幅 ≥40%


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


def forward_min(closes, i):
    """其後 24 個月的最大跌幅 %（相對於 i 當日）。窗不完整回 None——
    **不足的窗一律排除，不要拿「到目前為止」的部分窗當成完整結果**，
    那會系統性低估跌幅（近期的點永遠還沒跌完）。"""
    j = i + FORWARD_DAYS
    if j >= len(closes):
        return None
    w = closes[i + 1:j + 1]
    return (min(w) / closes[i] - 1) * 100


def main():
    OUT.mkdir(exist_ok=True)
    print("抓 SOXX 日收盤序列…")
    rows, rng, hit = series()
    dates = [d for d, _ in rows]
    closes = [c for _, c in rows]
    print(f"  {len(rows)} 筆，{dates[0]} → {dates[-1]}（rng={rng}，來源 {hit}）")

    daily = []
    for i in range(len(rows)):
        r = run24(closes, i)
        if r is None:
            continue
        daily.append({"d": dates[i].isoformat(), "close": round(closes[i], 4),
                      "ret24": round(r, 2),
                      "score": round(eng.pw(r, [[25, 0], [50, 25], [100, 60], [150, 85], [250, 100]]), 1),
                      "fwd24_min": (lambda v: round(v, 2) if v is not None else None)(forward_min(closes, i))})

    # 門檻穿越：只取「由下往上穿過」的那一天，避免同一波行情被重複計數
    events = {}
    for th in THRESHOLDS:
        evs, armed = [], True
        for k, row in enumerate(daily):
            if row["ret24"] >= th and armed:
                evs.append({"d": row["d"], "ret24": row["ret24"], "fwd24_min": row["fwd24_min"]})
                armed = False
            elif row["ret24"] < th * 0.9:      # 回落 10% 以下才重新武裝
                armed = True
        done = [e for e in evs if e["fwd24_min"] is not None]
        crashed = [e for e in done if e["fwd24_min"] <= CRASH_DRAWDOWN]
        events[str(th)] = {
            "穿越次數": len(evs),
            "窗已走完": len(done),
            "其後24月跌幅≥40%": len(crashed),
            "實測崩盤率%": round(100 * len(crashed) / len(done), 1) if done else None,
            "文獻崩盤率%": LIT[th],
            "事件": evs,
        }

    res = {"symbol": "SOXX", "rows": len(rows), "from": dates[0].isoformat(), "to": dates[-1].isoformat(),
           "source": hit, "window_trading_days": WINDOW_TRADING_DAYS, "forward_days": FORWARD_DAYS,
           "crash_drawdown_pct": CRASH_DRAWDOWN, "events": events, "daily": daily}
    (OUT / "gsy_runup.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"寫出 backtest/gsy_runup.json（{len(daily)} 筆日觀測）")
    for th, e in events.items():
        print(f"  門檻 {th}%：穿越 {e['穿越次數']} 次、窗走完 {e['窗已走完']} 次、"
              f"其後崩盤 {e['其後24月跌幅≥40%']} 次 → 實測 {e['實測崩盤率%']}%（文獻 {e['文獻崩盤率%']}%）")


if __name__ == "__main__":
    main()
