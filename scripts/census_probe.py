#!/usr/bin/env python3
"""Census VIP 探針：確認資料中心的 category_code 到底是什麼。

## 為什麼先探

`MAINTENANCE.md` §5：2026-08-10 已勘查端點
`api.census.gov/data/timeseries/eits/vip`，但**連 `category_code` 的可用值清單
都要金鑰才查得到**（keyless 直接回「A valid key must be included」），
所以資料中心的類別碼從來沒被確認過。VIP 自 2024 起把 Data Center 從 Office
拆出來獨立列示——**但那是二手說法，沒有在 API 上驗過。**

寫一個沒驗證過的抓取違反 §5.1「絕不編造數字」。所以先探，再接。

## 金鑰怎麼給

**用環境變數，不要寫進檔案、不要當參數傳。**

    read -rs CENSUS_API_KEY && export CENSUS_API_KEY
    python3 census_probe.py

`read -rs` 不回顯，值不會進 shell 歷史（指令本身會，值不會）。
這支程式**不會印出金鑰**——所有輸出的 URL 都遮成 `key=***`。

## 用法

    python3 census_probe.py
    python3 census_probe.py --year 2026
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request

BASE = "https://api.census.gov/data/timeseries/eits/vip"
KEYWORDS = ("data center", "datacenter", "computer", "information",
            "office", "資料中心")


def mask(u):
    return re.sub(r"key=[^&]+", "key=***", u)


def fetch(url, key, timeout=45):
    full = url + ("&" if "?" in url else "?") + "key=" + urllib.parse.quote(key)
    req = urllib.request.Request(full, headers={"User-Agent": "ai-bubble-monitor/2.2 probe"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except Exception as e:
        return None, f"{e.__class__.__name__}: {str(e)[:160]}"


def show(name, url, key, dump=0):
    """**回什麼形狀就印什麼形狀。**

    v1 只處理了「list of lists」——於是 `variables.json` 回了 200／2,703 bytes，
    畫面上一個字都沒有。**探針最沒有價值的失敗方式，是成功地什麼都沒告訴你。**
    """
    print(f"\n{'─'*74}\n{name}\n  {mask(url)}")
    st, body = fetch(url, key)
    if st is None:
        print(f"  **連不到**：{body}"); return None
    print(f"  HTTP {st}　{len(body):,} bytes")
    if st != 200:
        print(f"  **回應**：{body[:400]}"); return None
    try:
        j = json.loads(body)
    except Exception:
        print(f"  **不是 JSON**：{body[:300]!r}"); return None

    if isinstance(j, list) and j and isinstance(j[0], list):
        print(f"  表頭：{j[0]}　資料 {len(j)-1} 列")
        for row in j[1:1 + dump]:
            print(f"    {row}")
        return j

    if isinstance(j, dict):
        print(f"  頂層鍵：{sorted(j.keys())}")
        v = j.get("variables")
        if isinstance(v, dict):
            print(f"  變數 {len(v)} 個：")
            for nm, meta in sorted(v.items()):
                meta = meta if isinstance(meta, dict) else {}
                req = "  **required**" if str(meta.get("required", "")).lower() in ("true", "1") else ""
                print(f"    {nm:<22}{str(meta.get('label',''))[:54]}{req}")
        item = j.get("item") or (j.get("values") or {}).get("item")
        if isinstance(item, dict):
            print(f"  可用值 {len(item)} 個：")
            for code, lab in sorted(item.items()):
                hit = any(k in f"{code} {lab}".lower() for k in KEYWORDS)
                print(f"    {str(code):<16}{str(lab)[:58]}{'  **← 關鍵字命中**' if hit else ''}")
        if not v and not item:
            print(f"  （沒有 variables／item 鍵）原始開頭：{body[:400]}")
    return j


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2026")
    a = ap.parse_args()
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    if not key:
        sys.exit("沒有 CENSUS_API_KEY。先跑：read -rs CENSUS_API_KEY && export CENSUS_API_KEY")
    print(f"金鑰已載入（長度 {len(key)}，不顯示內容）")

    show("一、變數清單（哪些是必填）", f"{BASE}/variables.json", key)

    # **這一節才是真正的答案。** EITS 的每個變數都有自己的值清單端點，
    # 直接列出所有 category_code 與它的中文／英文說明，
    # 不必先撈一整年的資料再去 distinct。
    show("二、category_code 的可用值（連說明）",
         f"{BASE}/variables/category_code.json", key)
    show("三、data_type_code 的可用值", f"{BASE}/variables/data_type_code.json", key)

    # 到這裡為止已知：values 端點不存在（只回變數 metadata），
    # seasonally_adj 是必填，API 文件頁也沒有代碼對照表。
    # 38 個 category_code 全是不透明縮寫，而「Data center」在 C30 定義裡
    # 是 Office 底下的子類（census.gov/construction/c30/definitions.html 已查證）。
    # **不再猜形狀，改成三路並進，讓資料自己指認。**

    j = show("四、實際撈一年（seasonally_adj 放進 get）",
             f"{BASE}?get=cell_value,category_code,data_type_code,time_slot_id,seasonally_adj"
             f"&for=us:*&time={a.year}", key, dump=4)

    # 路一：把每個可能帶可讀文字的欄位都撈出來。program_code 的 label 是
    # 「Component Name」，time_slot_name 是「Time Slot Name」——
    # 其中任何一個若帶人看得懂的字串，代碼問題就解決了。
    show("五、撈可讀欄位（program_code／time_slot_name／error_data）",
         f"{BASE}?get=cell_value,category_code,program_code,time_slot_name,"
         f"data_type_code,seasonally_adj&for=us:*&time={a.year}-06", key, dump=8)

    if not isinstance(j, list) or len(j) < 2:
        print("\n四節沒有資料，後面的指認做不了"); return
    hdr = j[0]
    ix = {k: hdr.index(k) for k in hdr}

    # 路二：data_type_code 有哪幾種、各自的量級長什麼樣。
    # MPCP 看起來是百分比變化（值 2.9／−3.2），要找的是金額那一種。
    print(f"\n{'='*74}\n六、data_type_code 的種類與量級\n{'='*74}")
    byd = {}
    for r in j[1:]:
        try: v = float(r[ix["cell_value"]])
        except (ValueError, TypeError): continue
        byd.setdefault(r[ix["data_type_code"]], []).append(abs(v))
    print(f"{'code':<10}{'列數':>7}{'中位':>14}{'最大':>16}  推測")
    for code, vals in sorted(byd.items()):
        vals.sort(); mid = vals[len(vals)//2]
        guess = "金額（百萬美元？）" if mid > 1000 else "百分比或指數"
        print(f"{code:<10}{len(vals):>7}{mid:>14,.1f}{vals[-1]:>16,.1f}  {guess}")

    # 路三：用金額型的 data_type 把 38 個類別依量級排出來。
    # C30 公布表裡 Office 與 Data center 的金額是很有辨識度的數字，
    # **對得上就指認得出來**——這是不靠代碼表也能收斂的一條路。
    money = [c for c, v in byd.items() if sorted(v)[len(v)//2] > 1000]
    for mcode in money[:2]:
        print(f"\n{'='*74}\n七、data_type_code={mcode} 各類別的最新值（依量級排序）\n{'='*74}")
        latest = {}
        for r in j[1:]:
            if r[ix["data_type_code"]] != mcode: continue
            try: v = float(r[ix["cell_value"]])
            except (ValueError, TypeError): continue
            t = r[ix["time"]]
            c = r[ix["category_code"]]
            if c not in latest or t > latest[c][0]: latest[c] = (t, v)
        print(f"{'category_code':<16}{'時間':<10}{'值':>16}")
        for c, (t, v) in sorted(latest.items(), key=lambda x: -x[1][1]):
            print(f"{c:<16}{t:<10}{v:>16,.1f}")
        print("\n  **拿這張表去對 census.gov 公布的 C30 表**："
              "\n  Total、Nonresidential、Office、Data center 的金額都是有辨識度的數字，"
              "\n  對得上就指認得出代碼——不需要代碼對照表。")


if __name__ == "__main__":
    main()
