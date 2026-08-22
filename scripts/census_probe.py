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

    # v1 漏了 seasonally_adj，Census 回 400「missing required variable/predicate」。
    # 那是個好錯誤——它明講缺什麼。這裡兩種寫法都試（放進 get、或當 predicate）。
    j = show("四、實際撈一年的資料（seasonally_adj 放進 get）",
             f"{BASE}?get=cell_value,category_code,data_type_code,time_slot_id,seasonally_adj"
             f"&for=us:*&time={a.year}", key, dump=4)
    if j is None:
        j = show("四之二、改成 predicate 寫法",
                 f"{BASE}?get=cell_value,category_code,data_type_code,time_slot_id"
                 f"&seasonally_adj=no&for=us:*&time={a.year}", key, dump=4)

    if j and isinstance(j, list) and len(j) > 1:
        hdr = j[0]
        try:
            ci = hdr.index("category_code")
        except ValueError:
            print("\n  **回應裡沒有 category_code 欄**，形狀跟預期不同"); return
        cats = sorted({r[ci] for r in j[1:] if len(r) > ci and r[ci]})
        print(f"\n{'='*74}\n五、這一年實際出現過的 category_code 共 {len(cats)} 個\n{'='*74}")
        for c in cats:
            hit = any(k in str(c).lower() for k in KEYWORDS)
            print(f"  {c:<28}{'**← 關鍵字命中**' if hit else ''}")
        print("\n  **代碼多半是縮寫，看不出中文意思。** 對照 variables.json 的說明，"
              "\n  或到 census.gov/construction/c30/definitions.html 查全名。"
              "\n  在確認哪一個是資料中心之前，不要寫抓取。")


if __name__ == "__main__":
    main()
