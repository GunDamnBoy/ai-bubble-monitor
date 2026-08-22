#!/usr/bin/env python3
"""發布閘門：降級的產出不准蓋掉線上那份好資料。

## 為什麼需要這一支

`update_data.py` 的 `attempt()` 把每一項的失敗都吞掉、沿用舊值，整次更新絕不中斷。
**那在指標層是對的**——寧可讓一項停在上週，也不要編一個數字。

但 workflow 這一層原本沒有對應的檢查：程式不會非零退出，所以
**32 項掛掉 30 項，`git commit` 照樣執行**。唯一的閘門是 `git diff --cached --quiet`，
而那只判斷「有沒有 diff」，跟內容好不好無關。

這一支只問一個問題：**這份新的 data.json，適合蓋掉線上那份嗎？**

## 擋 vs 只提醒

| | 判準 | 理由 |
|---|---|---|
| **擋**（exit 1） | 產出本身壞了或不可信：結構缺件、指標數變了、綜合溫度一天跳超過門檻、整層變 null、戳記倒退 | 這些不是「資料舊了」，是「資料錯了」 |
| **只提醒**（exit 0） | 抓取失敗數偏高 | 這條路引擎已經有 `fresh` 與 `asof` 在頁面上自己承認。擋住它反而更糟 |

## 擋住之後會發生什麼（這道閘門的已知代價）

不 commit、job 紅燈。GitHub 對排程 workflow 的失敗會寄信給 repo 擁有者，那是通知管道。
線上維持前一天的 data.json——**而那份的 `fresh` 是昨天算的**。
所以連續擋兩天以上時，頁面會停在舊資料卻不顯示「資料延遲」。

**這道閘門把「發布壞資料」換成「安靜地停更」。** 後者比較安全，但不是沒有代價，
所以 job 失敗必須真的有人看到——不要把這個 workflow 的通知關掉。

用法：`python scripts/gate.py`（在 repo 根目錄，checkout 之後、commit 之前）
放行指標數變動：`ALLOW_COUNT_CHANGE=1 python scripts/gate.py`
"""
import json, os, subprocess, sys

MAX_JUMP = float(os.environ.get("GATE_MAX_JUMP", "8"))
MAX_NEW_NULL = int(os.environ.get("GATE_MAX_NEW_NULL", "3"))
WARN_FAILS = int(os.environ.get("GATE_WARN_FAILS", "8"))
ALLOW_COUNT = os.environ.get("ALLOW_COUNT_CHANGE") == "1"

R = {"block": 0, "warn": 0, "ok": 0}


def block(m): R["block"] += 1; print(f"BLOCK {m}")
def warn(m):  R["warn"] += 1;  print(f"WARN  {m}")
def ok(m):    R["ok"] += 1;    print(f"OK    {m}")


def prev_data():
    """線上那份（HEAD 的 data.json）。第一次跑或拿不到就回 None，只做結構檢查。"""
    try:
        raw = subprocess.run(["git", "show", "HEAD:data.json"],
                             capture_output=True, timeout=30).stdout
        return json.loads(raw) if raw else None
    except Exception:
        return None


def nulls(d):
    return sum(1 for i in d.get("indicators", []) if i.get("score") is None)


def main():
    path = "data.json"
    if not os.path.isfile(path):
        block("data.json 不存在——引擎沒有寫出東西"); sys.exit(1)

    size = os.path.getsize(path)
    try:
        new = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        block(f"data.json 解析失敗：{e}"); sys.exit(1)
    ok(f"data.json 解析成功（{size/1024:.0f} KB）")

    # ---- 結構：這幾個鍵不在，前端就是空白頁 ----
    need = ["composite", "dims", "indicators", "meta", "triggers", "tw"]
    missing = [k for k in need if k not in new]
    if missing:
        block(f"缺少頂層鍵：{missing}")
    else:
        ok(f"頂層鍵齊全（{len(need)} 個）")

    n_ind = len(new.get("indicators", []))
    if n_ind == 0:
        block("indicators 是空的")
    comp = new.get("composite")
    if not isinstance(comp, (int, float)):
        block(f"composite 不是數字：{comp!r}")

    old = prev_data()
    if old is None:
        warn("拿不到 HEAD 的 data.json（第一次跑？），只做了結構檢查——**沒有比較過**")
        print(f"\n總計  OK {R['ok']}　WARN {R['warn']}　BLOCK {R['block']}")
        sys.exit(1 if R["block"] else 0)

    # ---- 檔案大小：截斷型的壞掉，結構檢查抓不到 ----
    try:
        oldsize = len(subprocess.run(["git", "show", "HEAD:data.json"],
                                     capture_output=True, timeout=30).stdout)
        if oldsize and size < oldsize * 0.5:
            block(f"檔案縮到前一版的 {size/oldsize:.0%}（{size}B vs {oldsize}B）——像是被截斷")
        else:
            ok(f"檔案大小合理（前一版的 {size/max(oldsize,1):.0%}）")
    except Exception:
        pass

    # ---- 指標數：變了就是有人改了指標集合，那不該由每日資料跑靜默完成 ----
    n_old = len(old.get("indicators", []))
    if n_ind != n_old:
        (warn if ALLOW_COUNT else block)(
            f"指標數 {n_old} → {n_ind}。若是刻意新增/移除，用 ALLOW_COUNT_CHANGE=1 放行，"
            f"並記得同步 brief、healthcheck 的 LAYER_N、index.html 的「N 項指標」")
    else:
        ok(f"指標數不變（{n_ind}）")

    # ---- 綜合溫度：22 項慢指標的加權平均，一天跳這麼多只可能是抓取壞了 ----
    c_old = old.get("composite")
    if isinstance(comp, (int, float)) and isinstance(c_old, (int, float)):
        jump = abs(comp - c_old)
        if jump > MAX_JUMP:
            block(f"綜合溫度 {c_old} → {comp}（跳 {jump:.1f} 分，門檻 {MAX_JUMP}）"
                  f"——先確認是哪一項在動，不要直接放行")
        else:
            ok(f"綜合溫度 {c_old} → {comp}（動 {jump:.1f} 分）")

    # ---- 整層變 null：合法（設計允許），但影響權重歸一，要人看過 ----
    for k in ("L1", "L2", "L3"):
        o, n = (old.get("dims") or {}).get(k), (new.get("dims") or {}).get(k)
        if o is not None and n is None:
            block(f"{k} 從 {o} 變成 null——整層失效會讓 composite 用剩餘層重新歸一")
    if all((new.get("dims") or {}).get(k) is not None for k in ("L1", "L2", "L3")):
        ok("三層都有值")

    # ---- 待數據指標數暴增 ----
    d_null = nulls(new) - nulls(old)
    if d_null > MAX_NEW_NULL:
        block(f"待數據指標 {nulls(old)} → {nulls(new)}（多 {d_null} 項，門檻 {MAX_NEW_NULL}）")
    else:
        ok(f"待數據指標 {nulls(old)} → {nulls(new)}")

    # ---- 內嵌退路快照：引擎現在會自己重灌它，所以它也進了發布路徑 ----
    # fetch("data.json") 失敗那天，使用者看到的就是這一塊。它壞掉的話頁面仍然是
    # 合法 HTML、只是離線時整頁空白——**平常沒有人看得到，所以沒有人會發現**。
    idx = "index.html"
    if os.path.isfile(idx):
        import re
        h = open(idx, encoding="utf-8").read()
        m = re.search(r'<script[^>]*id="dashboard-data"[^>]*>(.*?)</script>', h, re.S)
        if not m:
            block("index.html 找不到 #dashboard-data 內嵌退路快照")
        else:
            try:
                snap = json.loads(m.group(1))
                ok(f"內嵌退路快照可解析（built={(snap.get('meta') or {}).get('built')}，"
                   f"{len(m.group(1))/1024:.0f} KB）")
            except Exception as e:
                block(f"內嵌退路快照不是合法 JSON：{e}")

    # ---- 戳記：引擎沒跑到底、或寫回更舊的東西 ----
    b_old, b_new = (old.get("meta") or {}).get("built"), (new.get("meta") or {}).get("built")
    if b_new and b_old and str(b_new) < str(b_old):
        block(f"meta.built 倒退：{b_old} → {b_new}")
    elif b_new == b_old:
        warn(f"meta.built 沒變（{b_new}）——引擎可能沒有真的重跑")
    else:
        ok(f"meta.built {b_old} → {b_new}")

    # ---- 失敗數：只提醒。頁面自己會標延遲，擋住反而讓它停在昨天又不承認 ----
    fails = ((new.get("meta") or {}).get("lastAutoRun") or {}).get("fail") or []
    if len(fails) > WARN_FAILS:
        warn(f"本次抓取失敗 {len(fails)} 項（門檻 {WARN_FAILS}）：{fails}")
    else:
        ok(f"本次抓取失敗 {len(fails)} 項：{fails or '無'}")

    print(f"\n總計  OK {R['ok']}　WARN {R['warn']}　BLOCK {R['block']}")
    if R["block"]:
        print("\n**不發布。** 線上維持前一天的 data.json。")
        print("這代表頁面會停在舊資料而且不會自己說延遲——先查清楚再手動觸發一次。")
    sys.exit(1 if R["block"] else 0)


if __name__ == "__main__":
    main()
