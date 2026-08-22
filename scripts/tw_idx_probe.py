#!/usr/bin/env python3
"""TWSE 指數歷史端點探針：`idx_hist` 能不能回補。

## 為什麼要探

`elec_rel`（電子指數相對大盤）需要 21 個交易日的序列，而引擎目前走的
`openapi.twse.com.tw/v1/exchangeReport/MI_INDEX` **只有當日快照**——
所以序列只能一天一天長，中斷過就要重新等 21 天。
`tw_margin` 已經有現成解法（`backfill_margin_hist()` 走 RWD 的 `?date=`），
指數這邊照抄就好——**前提是那條路真的存在，而且回的東西是我以為的樣子。**

這一支不寫 `data.json`、不改任何指標。它只問：
哪個端點吃 `date=`、回什麼形狀、找不找得到「發行量加權股價指數」與「電子類指數」。

## 用法

    python3 tw_idx_probe.py
    python3 tw_idx_probe.py --days 5
"""
import argparse, json, re, sys, time
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
WANT = ("發行量加權股價指數", "電子類指數", "電子工業類指數")

CANDS = [
    ("RWD MI_INDEX type=IND",
     "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=IND&response=json"),
    ("RWD MI_INDEX type=ALL",
     "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALL&response=json"),
    ("RWD BFIAMU（類股成交）",
     "https://www.twse.com.tw/rwd/zh/afterTrading/BFIAMU?date={d}&response=json"),
    ("openapi MI_INDEX（現行，無 date）",
     "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"),
]


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def walk_tables(obj):
    """RWD 的回應把資料放在 tables[].data 或頂層 data，兩種都要認。"""
    out = []
    if isinstance(obj, dict):
        if isinstance(obj.get("tables"), list):
            for t in obj["tables"]:
                out.append((t.get("title", ""), t.get("fields") or [], t.get("data") or []))
        if isinstance(obj.get("data"), list):
            out.append((obj.get("title", "(頂層)"), obj.get("fields") or [], obj["data"]))
    elif isinstance(obj, list):
        out.append(("(裸陣列)", list(obj[0].keys()) if obj and isinstance(obj[0], dict) else [], obj))
    return out


def probe(name, tpl, day):
    url = tpl.format(d=day)
    print(f"\n{'─'*76}\n{name}\n{url}")
    try:
        st, body = get(url)
    except Exception as e:
        print(f"  **失敗**：{e.__class__.__name__}: {str(e)[:90]}"); return
    print(f"  HTTP {st}　{len(body):,} bytes")
    try:
        j = json.loads(body)
    except Exception:
        print(f"  **不是 JSON**，開頭：{body[:120]!r}"); return
    if isinstance(j, dict):
        print(f"  頂層鍵：{sorted(j.keys())}")
        for k in ("stat", "date", "title"):
            if k in j: print(f"    {k} = {j[k]!r}")
    for title, fields, rows in walk_tables(j):
        if not rows: continue
        print(f"  表「{str(title)[:38]}」　欄位 {fields}　{len(rows)} 列")
        hits = []
        for r in rows:
            txt = json.dumps(r, ensure_ascii=False)
            for w in WANT:
                if w in txt: hits.append((w, r))
        if hits:
            print("  **找到目標指數**：")
            for w, r in hits[:4]:
                print(f"    {w} → {json.dumps(r, ensure_ascii=False)[:150]}")
        else:
            print(f"    （沒有目標指數）首列：{json.dumps(rows[0], ensure_ascii=False)[:130]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="往回試幾個日期")
    a = ap.parse_args()
    import datetime as dt
    d = dt.date.today()
    tried = 0
    while tried < a.days:
        d -= dt.timedelta(days=1)
        if d.weekday() >= 5: continue
        tried += 1
        day = d.strftime("%Y%m%d")
        print(f"\n{'='*76}\n日期 {d}（{day}）\n{'='*76}")
        for name, tpl in CANDS:
            probe(name, tpl, day)
            time.sleep(1.2)
        if tried == 1:
            print("\n（第一個日期已涵蓋所有端點；其餘日期只重試吃 date 的那幾個）")
            CANDS[:] = [c for c in CANDS if "{d}" in c[1]]


if __name__ == "__main__":
    main()
