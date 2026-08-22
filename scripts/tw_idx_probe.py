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


def which_elec():
    """**引擎現在到底抓到哪一列？**

    `tw_index_today()` 的精確名是 `nm == "電子類指數"`，但 openapi 的 MI_INDEX
    根本沒有這個名字（它叫「電子工業類指數」），所以每次都落到子字串退路
    `"電子" in nm and "報酬" not in nm`，取第一個命中就 break。
    2026-08-22 的 `idx_hist` 存的是 24,519.06，而電子工業類指數是 2,872.09、
    其他電子類指數是 271.81——**三個都對不起來**。
    這一節把 openapi 所有含「電子」的列照原順序印出來，指出退路實際咬到哪一列。
    """
    print("\n" + "=" * 76)
    print("引擎現行選法實測：openapi MI_INDEX 裡所有含「電子」的列（原順序）")
    print("=" * 76)
    try:
        st, body = get("https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX")
        arr = json.loads(body)
    except Exception as e:
        print(f"  失敗：{e}"); return
    exact = [r for r in arr if r.get("指數") == "電子類指數"]
    print(f"  精確名 nm == 「電子類指數」的列數：{len(exact)}"
          f"　{'← 一列都沒有，所以每次都走退路' if not exact else ''}")
    print(f"\n  {'#':>3}  {'指數名稱':<24}{'收盤指數':>12}   退路會不會咬")
    hit = False
    for i, r in enumerate(arr):
        nm = r.get("指數", "")
        if "電子" not in nm: continue
        take = ("電子" in nm and "報酬" not in nm)
        mark = ""
        if take and not hit:
            mark = "**← 退路取這一列並 break**"; hit = True
        elif take:
            mark = "（也符合，但排在後面）"
        print(f"  {i:>3}  {nm:<24}{str(r.get('收盤指數','')):>12}   {mark}")
    print("\n  正解應該是「電子工業類指數」。若上面 break 的那一列不是它，"
          "\n  **elec_rel 一直在拿另一條序列跟大盤比**，而頁面上看不出來。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="往回試幾個日期")
    ap.add_argument("--which", action="store_true", help="只跑「引擎現在抓到哪一列」")
    a = ap.parse_args()
    if a.which:
        which_elec(); return
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
