#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 泡沫監控儀表板 · 健康檢查（唯讀，不碰 git、不連網）

用法：
    python3 healthcheck.py              # 自動偵測 repo 位置
    python3 healthcheck.py --repo PATH  # 指定 repo

輸出每行為 PASS／WARN／FAIL。維護時把 FAIL 與 WARN 全部帶進報告。
"""
import argparse
import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys

R = {"pass": 0, "warn": 0, "fail": 0}
_LINES = []


def _p(kind, msg):
    R[kind] += 1
    _LINES.append((kind, msg))
    print(f"{kind.upper():4} {msg}")


def days_ago(s):
    """把 YYYY-MM-DD 轉成距今天數；格式不對回 None（不擋流程）。"""
    try:
        return (dt.date.today() - dt.date.fromisoformat(str(s)[:10])).days
    except Exception:
        return None


def ok(m): _p("pass", m)
def warn(m): _p("warn", m)
def bad(m): _p("fail", m)


def find_repo(explicit=None):
    cands = []
    if explicit:
        cands.append(explicit)
    cands.append(os.path.dirname(os.path.abspath(__file__)))
    cands += [os.path.expanduser("~/ai-bubble-monitor"), "/tmp/v2"]
    for base in ("/sessions", os.path.expanduser("~")):
        if os.path.isdir(base):
            for root, dirs, _ in os.walk(base):
                if root.count(os.sep) - base.count(os.sep) > 4:
                    dirs[:] = []
                    continue
                if "ai-bubble-monitor" in dirs:
                    cands.append(os.path.join(root, "ai-bubble-monitor"))
                    dirs[:] = [d for d in dirs if d != "ai-bubble-monitor"]
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "data.json")) and os.path.isfile(os.path.join(c, "index.html")):
            return c
    return None


# ---------------------------------------------------------------- 1. data.json
def check_data(repo):
    path = os.path.join(repo, "data.json")
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as ex:
        bad(f"data.json 無法解析：{ex}")
        return None
    ok("data.json 可解析")

    meta = d.get("meta", {})
    if meta.get("version") != 2:
        warn(f"meta.version = {meta.get('version')}（本檢查針對 v2 撰寫）")

    # 新鮮度
    built = meta.get("built")
    try:
        age = (dt.date.today() - dt.date.fromisoformat(built)).days
        if age <= 1:
            ok(f"資料新鮮度：built={built}（{age} 天前）")
        elif age <= 4:
            warn(f"資料新鮮度：built={built}（{age} 天前；遇連假可能正常）")
        else:
            bad(f"資料新鮮度：built={built}（{age} 天前，Actions 可能已停擺）")
    except Exception:
        bad(f"meta.built 格式異常：{built!r}")

    # 層權重
    dm = d.get("dimMeta", {})
    wsum = sum(v.get("w", 0) for v in dm.values())
    if abs(wsum - 1.0) < 1e-9:
        ok("dimMeta 權重加總 = 1.0（" + "／".join(f"{k} {v['w']}" for k, v in dm.items()) + "）")
    else:
        bad(f"dimMeta 權重加總 = {wsum}，應為 1.0")

    # 指標 → 層分數 → 綜合溫度 → 象限：全部重算比對
    inds = d.get("indicators", [])
    ok(f"indicators 共 {len(inds)} 項") if len(inds) >= 20 else warn(f"indicators 只有 {len(inds)} 項")

    recomputed = {}
    for dk in dm:
        ss = [i["score"] for i in inds if i.get("dim") == dk and i.get("score") is not None]
        recomputed[dk] = round(sum(ss) / len(ss), 1) if ss else 50.0
    stored = d.get("dims", {})
    diffs = [f"{k}: 存 {stored.get(k)} vs 算 {recomputed[k]}" for k in recomputed
             if abs((stored.get(k) or -999) - recomputed[k]) > 0.15]
    if diffs:
        bad("層分數與指標不一致（有人改了分數沒重算）：" + "；".join(diffs))
    else:
        ok(f"層分數與指標一致：{recomputed}")

    comp = round(sum(dm[k]["w"] * recomputed[k] for k in recomputed), 1)
    if abs(comp - (d.get("composite") or -999)) > 0.15:
        bad(f"composite 不一致：存 {d.get('composite')} vs 算 {comp}")
    else:
        ok(f"composite 一致：{comp}")

    heat = round((recomputed["L1"] + recomputed["L2"]) / 2, 1)
    support = round(100 - recomputed["L3"], 1)
    regime = ("泡沫危險區" if heat >= 55 and support < 45 else
              "過熱但有撐（melt-up 風險）" if heat >= 55 else
              "健康擴張" if support >= 45 else "失速風險")
    q = d.get("quadrant", {})
    if abs((q.get("heat") or -999) - heat) > 0.15 or abs((q.get("support") or -999) - support) > 0.15:
        bad(f"quadrant 不一致：存 {q} vs 算 heat={heat} support={support}")
    elif q.get("regime") != regime:
        bad(f"regime 不一致：存「{q.get('regime')}」vs 算「{regime}」")
    else:
        ok(f"象限一致：heat={heat} support={support}｜{regime}")

    # 指標欄位完整性
    need = {"id", "dim", "name", "score", "zone", "asof", "fresh"}
    prob = []
    for i in inds:
        miss = need - set(i)
        if miss:
            prob.append(f"{i.get('id')} 缺 {sorted(miss)}")
            continue
        s = i["score"]
        if s is not None and not (0 <= s <= 100):
            prob.append(f"{i['id']} score={s} 超出 0-100")
        z = "pending" if s is None else ("green" if s < 33 else "yellow" if s < 67 else "orange" if s < 84 else "red")
        if i["zone"] != z:
            prob.append(f"{i['id']} zone={i['zone']} 應為 {z}")
        a = i.get("anchors")
        if a and any(a[k][0] >= a[k + 1][0] for k in range(len(a) - 1)):
            prob.append(f"{i['id']} anchors 的 x 未遞增")
        if i.get("dim") not in dm:
            prob.append(f"{i['id']} dim={i.get('dim')} 不在 dimMeta")
    if prob:
        bad("指標欄位問題：" + "；".join(prob))
    else:
        ok("指標欄位、燈號、錨點單調性皆正常")

    # null 分數（退出平均）
    nulls = [i["id"] for i in inds if i.get("score") is None]
    if nulls:
        warn(f"score 為 null（已退出當層平均）：{', '.join(nulls)}")
    else:
        ok("無 null 分數指標")

    # 質化指標集合
    QUAL = {"narrative", "circular", "weakcredit", "vc", "cloudrev", "tokens"}
    actual = {i["id"] for i in inds if i.get("qual")}
    if actual == QUAL:
        ok(f"質化指標集合符合規格（{len(QUAL)} 項）")
    else:
        bad(f"質化指標集合漂移：多 {sorted(actual - QUAL)}、少 {sorted(QUAL - actual)}")

    # 觸發器
    TRIG = {"hy80", "ccc12", "gsy150", "cpi4", "policy_gap", "y10_5", "megaipo"}
    tr = d.get("triggers", [])
    tids = {t.get("id") for t in tr}
    if tids == TRIG:
        lit = [t["id"] for t in tr if t.get("state")]
        ok(f"觸發器 7 項齊全，點亮 {len(lit)}/7" + ("：" + ", ".join(lit) if lit else ""))
    else:
        bad(f"觸發器集合漂移：多 {sorted(tids - TRIG)}、少 {sorted(TRIG - tids)}")
    if any(t.get("state") not in (0, 1, True, False) for t in tr):
        bad("觸發器 state 必須是 0/1")

    # 台灣
    tw = d.get("tw", {})
    TWI = {t["id"]: t for t in tw.get("items", [])}
    subs_def = {"動能": ["tsmc_200dma", "tsmc_52w", "elec_rel", "twii_pos"],
                "估值": ["tsmc_pe", "odm_pe"], "籌碼": ["tw_margin"],
                "基本面": ["tw_rev", "tw_export"]}
    missing = [i for ids in subs_def.values() for i in ids if i not in TWI]
    if missing:
        bad(f"tw.items 缺少子群成員：{missing}")
    subs = {}
    for k, ids in subs_def.items():
        ss = [TWI[i]["score"] for i in ids if i in TWI and TWI[i].get("score") is not None]
        subs[k] = round(sum(ss) / len(ss), 1) if ss else None
    sd = [f"{k}: 存 {tw.get('subs', {}).get(k)} vs 算 {v}" for k, v in subs.items()
          if (tw.get("subs", {}).get(k) is None) != (v is None)
          or (v is not None and abs((tw.get("subs", {}).get(k) or -999) - v) > 0.15)]
    if sd:
        bad("tw.subs 不一致：" + "；".join(sd))
    else:
        ok(f"tw.subs 一致：{subs}")
    wmap = {"動能": .3, "估值": .3, "籌碼": .2, "基本面": .2}
    valid = {k: v for k, v in subs.items() if v is not None}
    ws = sum(wmap[k] for k in valid)
    if ws:
        h = round(sum(v * wmap[k] for k, v in valid.items()) / ws, 1)
        if abs(h - (tw.get("heat") or -999)) > 0.15:
            bad(f"tw.heat 不一致：存 {tw.get('heat')} vs 算 {h}")
        else:
            ok(f"tw.heat 一致：{h}")
    if "tsmc_weight" in TWI:
        aw = TWI["tsmc_weight"].get("asof")
        try:
            age = (dt.date.today() - dt.date.fromisoformat(str(aw))).days
            (warn if age > 45 else ok)(f"tsmc_weight（人工月更）asof={aw}（{age} 天前）")
        except Exception:
            warn(f"tsmc_weight asof 格式異常：{aw!r}")

    # history
    h = d.get("history", [])
    dates = [x.get("date") for x in h]
    if len(dates) != len(set(dates)):
        dup = sorted({x for x in dates if dates.count(x) > 1})
        bad(f"history 有重複日期：{dup}")
    elif dates != sorted(dates):
        bad("history 未依日期遞增排序")
    elif len(h) > 400:
        bad(f"history 共 {len(h)} 筆，超過 400 上限")
    else:
        ok(f"history {len(h)} 筆，日期唯一且遞增（{dates[0]} → {dates[-1]}）")
    if dates and dates[-1] != built:
        bad(f"history 最後一筆 {dates[-1]} ≠ meta.built {built}")
    noquad = [x["date"] for x in h if "quad" not in x]
    if noquad:
        warn(f"history 有 {len(noquad)} 筆缺 quad（改版前的舊筆屬正常）：{noquad[0]} … {noquad[-1]}")
    trail = [x for x in h if "quad" in x]
    ok(f"象限軌跡目前 {len(trail)} 個點") if trail else bad("象限軌跡沒有任何點")

    # events
    ev = d.get("events", [])
    if not ev:
        bad("events 空白")
    elif len(ev) > 12:
        bad(f"events {len(ev)} 條，超過 12 上限")
    elif any(not x.get("url") for x in ev):
        bad("events 有條目缺 url")
    else:
        ok(f"events {len(ev)} 條、皆有 url（最新 {ev[0].get('d')}）")

    # charts
    ch = d.get("charts", {})
    for k in ("aggQ", "ttm"):
        rows = ch.get(k, [])
        qs = [r.get("q") for r in rows]
        if qs != sorted(qs):
            bad(f"charts.{k} 季別未遞增")
        prov = [r for r in rows if r.get("prov")]
        if prov:
            p = prov[-1]
            if p.get("have") is None:
                # ttm 的初步旗標由 aggQ 帶入，本身不重複記 have／missing
                ok(f"charts.{k} 末筆為初步季 {p['q']}（初步旗標沿用 aggQ）")
            else:
                miss = "／".join(p.get("missing", [])) or "無"
                ok(f"charts.{k} 末筆為初步季 {p['q']}（{p['have']}/5 家，缺 {miss}）")
        else:
            ok(f"charts.{k} 末筆 {qs[-1] if qs else '無'}（無初步季）")

    # lastAutoRun
    lar = meta.get("lastAutoRun", {})
    KNOWN = {"AAII", "CBOE putcall", "TW 台積電權重"}
    fails = set(lar.get("fail", []))
    newf = fails - KNOWN
    if newf:
        bad(f"出現新的失敗來源（非已知清單）：{sorted(newf)}")
    if fails & KNOWN:
        warn(f"已知失敗來源（設計上可降級）：{sorted(fails & KNOWN)}")
    ok(f"最近一次自動更新 {lar.get('date')}：成功 {len(lar.get('ok', []))} 項、失敗 {len(fails)} 項")
    return d


# ------------------------------------------------------------ 2. brief 一致性
def check_brief(repo, d):
    path = os.path.join(repo, "AGENT_BRIEF.md")
    if not os.path.isfile(path):
        bad("找不到 AGENT_BRIEF.md")
        return
    txt = open(path, encoding="utf-8").read()
    ok("AGENT_BRIEF.md 存在")
    if not d:
        return

    # 層權重
    dm = d["dimMeta"]
    for dk, label in (("L1", "L1"), ("L2", "L2"), ("L3", "L3")):
        m = re.search(r"\*\*" + dk + r"\*\*\s*\|[^|]*\|\s*\*\*([0-9.]+)\*\*", txt)
        if not m:
            warn(f"brief 中找不到 {label} 的權重列")
        elif abs(float(m.group(1)) - dm[dk]["w"]) > 1e-9:
            bad(f"brief 的 {label} 權重 {m.group(1)} ≠ data.json 的 {dm[dk]['w']}")
    ok("brief 層權重與 data.json 比對完成")

    # 錨點
    IND = {i["id"]: i for i in d["indicators"]}
    mism, checked = [], 0
    for line in txt.splitlines():
        m = re.match(r"\|\s*`(\w+)`\s*\|", line)
        if not m or m.group(1) not in IND:
            continue
        a = re.findall(r"`(\[\[[^`]*\]\])`", line)
        if not a:
            continue
        try:
            want = ast.literal_eval(a[0])
        except Exception:
            continue
        checked += 1
        got = IND[m.group(1)].get("anchors")
        if got and [[float(x) for x in p] for p in want] != [[float(x) for x in p] for p in got]:
            mism.append(f"{m.group(1)}: brief {want} vs data {got}")
    if mism:
        bad("brief 錨點與 data.json 不符：" + "；".join(mism))
    else:
        ok(f"brief 錨點與 data.json 相符（比對 {checked} 項）")

    # 觸發器門檻文字
    for tid in ("hy80", "ccc12", "gsy150", "cpi4", "policy_gap", "y10_5", "megaipo"):
        if f"`{tid}`" not in txt:
            bad(f"brief 第 3.5 節缺觸發器 {tid}")

    # 台灣籃
    up = os.path.join(repo, "scripts", "update_data.py")
    if os.path.isfile(up):
        src = open(up, encoding="utf-8").read()
        codes = set(re.findall(r'\("(\d{4})", "', src.split("TW_BASKET", 1)[-1][:600]))
        bcodes = set(re.findall(r"`(\d{4}) ", txt)) | set(re.findall(r"`(\d{4})\s", txt))
        miss = codes - bcodes
        if miss:
            bad(f"brief 的台灣籃缺少 update_data.py 有的代號：{sorted(miss)}")
        elif codes:
            ok(f"台灣月營收籃 {len(codes)} 檔，brief 與引擎一致")

    # cron
    wf = os.path.join(repo, ".github", "workflows", "update.yml")
    if os.path.isfile(wf):
        y = open(wf, encoding="utf-8").read()
        m = re.search(r"cron:\s*'([^']+)'", y)
        if m:
            if m.group(1) in txt:
                ok(f"workflow cron `{m.group(1)}` 與 brief 一致")
            else:
                bad(f"workflow cron `{m.group(1)}` 未出現在 brief 第 7 節")
        if "pages/builds" in y:
            ok("workflow 保有 Pages 明確重建步驟（GITHUB_TOKEN 推送不會自動重建）")
        else:
            bad("workflow 缺少 POST /pages/builds 步驟 → 網站會停在舊值")
        if re.search(r"pages:\s*write", y):
            ok("workflow 具備 pages: write 權限")
        else:
            bad("workflow 缺少 pages: write 權限")
    else:
        bad("找不到 .github/workflows/update.yml")


# -------------------------------------------------------- 3-a. 內嵌退路快照
def check_fallback(html, d):
    """index.html 內嵌的 #dashboard-data 是 fetch data.json 失敗時的離線退路。
    它不會自動更新，v1→v2 改版時最容易被遺忘（曾發生整頁退回 v1 舊模型）。"""
    m = re.search(r'<script[^>]*id="dashboard-data"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        bad("index.html 找不到 #dashboard-data 內嵌退路快照")
        return
    try:
        fb = json.loads(m.group(1))
    except Exception as ex:
        bad(f"#dashboard-data 內嵌快照不是合法 JSON：{ex}")
        return

    fv = (fb.get("meta") or {}).get("version")
    dv = (d.get("meta") or {}).get("version") if d else None
    if dv is None:
        warn("data.json 沒有 meta.version，無法比對內嵌快照版本")
    elif fv == dv:
        ok(f"#dashboard-data 內嵌快照版本與 data.json 相同（v{fv}）")
    else:
        bad(f"#dashboard-data 內嵌快照是 v{fv}，data.json 是 v{dv}"
            "（fetch 失敗時整頁會退回舊模型，須以現行 data.json 重新產生）")

    for k in ("triggers", "quadrant", "dims"):
        if k not in fb:
            bad(f"#dashboard-data 內嵌快照缺 v2 區塊 {k}")

    fh, dh = len(fb.get("history") or []), len((d or {}).get("history") or [])
    if fh > 60:
        warn(f"#dashboard-data 內嵌快照 history {fh} 筆，建議只留最後 30 筆以免頁面過大")
    elif fh:
        ok(f"#dashboard-data 內嵌快照 history {fh} 筆（data.json {dh} 筆）")


def engine_spreads(path):
    """用 AST 找出 update_data.py 寫進 sp[...] 的鍵與欄位。
    回傳 {鍵: {欄位, ...}}；只認得字面量寫法（sp["hy"] = {...}、sp["hy"]["y1"] = ...），
    動態組出來的鍵抓不到，所以這裡的結果是「保證有寫」而不是「全部」。"""
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError:
        return out

    def const(node):
        return node.value if isinstance(node, ast.Constant) else None

    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if not isinstance(t, ast.Subscript):
                continue
            base, key = t.value, const(t.slice)
            if isinstance(base, ast.Name) and base.id == "sp" and isinstance(key, str):
                flds = out.setdefault(key, set())
                if isinstance(n.value, ast.Dict):
                    flds.update(k for k in map(const, n.value.keys) if isinstance(k, str))
            elif (isinstance(base, ast.Subscript) and isinstance(base.value, ast.Name)
                  and base.value.id == "sp" and isinstance(const(base.slice), str)
                  and isinstance(key, str)):
                out.setdefault(const(base.slice), set()).add(key)
    return out


# -------------------------------------------------------- 3-b. spreads 欄位對帳
def check_spreads_keys(repo, html, d):
    """前端信用磚塊直接讀 charts.spreads.<鍵>.<欄位>；引擎沒寫的欄位會算成 NaN
    並顯示成「−NaNbp」。曾經真的上線過，所以做成機械檢查。"""
    if "const sp = DATA.charts.spreads" not in html:
        warn("index.html 找不到 const sp = DATA.charts.spreads，略過 spreads 對帳")
        return
    js = "\n".join(re.findall(
        r"<script(?![^>]*application/json)[^>]*>(.*?)</script>", html, re.S))
    read_keys = set(re.findall(r"\bsp\.([A-Za-z_]\w*)", js))
    read_fields = set(re.findall(r"\bsp\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)", js))
    if not read_keys:
        warn("index.html 沒有讀取任何 charts.spreads 鍵，略過對帳")
        return

    up = os.path.join(repo, "scripts", "update_data.py")
    written = engine_spreads(up)
    live = d.get("charts", {}).get("spreads") or {} if d else {}

    miss = sorted(read_keys - set(written) - set(live))
    if miss:
        bad("index.html 讀 charts.spreads 的 " + "／".join(miss) +
            "，但 update_data.py 沒有寫入（該磚塊會空白或顯示 NaN）")
    else:
        ok(f"charts.spreads 前端讀取的 {len(read_keys)} 個鍵，引擎都有寫入")

    unused = sorted(set(written) - read_keys)
    if unused:
        warn("引擎寫了 charts.spreads 的 " + "／".join(unused) +
             "，但前端沒有畫（無害，確認是不是忘了做磚塊）")

    holes, pending = [], []
    for k, f in sorted(read_fields):
        if k not in live or not isinstance(live[k], dict):
            continue          # 鍵本身的問題已在上面報過
        if f in live[k]:
            continue
        (pending if f in written.get(k, set()) else holes).append(f"{k}.{f}")
    if holes:
        bad("前端讀得到鍵但引擎沒寫欄位：" + "／".join(holes) +
            "（相減會變成 NaN，引擎要補寫或前端要略過）")
    if pending:
        warn("引擎已寫但現行 data.json 還沒有的欄位：" + "／".join(pending) +
             "（下次自動更新後生效；在那之前線上仍是舊值）")
    if not holes and not pending:
        ok(f"charts.spreads 前端讀取的 {len(read_fields)} 個欄位在 data.json 中都存在")

    # 月頻序列（FEDFUNDS、USINFO）本來就落後 30–60 天，只抓真的凍住的殘留
    stale = [f"{k}（{v['asof']}）" for k, v in live.items()
             if isinstance(v, dict) and v.get("asof")
             and (days_ago(v["asof"]) or 0) > 120]
    if stale:
        warn("charts.spreads 這些鍵的 asof 超過 120 天，確認引擎是否真的有在抓："
             + "／".join(sorted(stale)))


# -------------------------------------------------------- 3. 引擎與前端
def check_code(repo, d):
    up = os.path.join(repo, "scripts", "update_data.py")
    if not os.path.isfile(up):
        bad("找不到 scripts/update_data.py")
    else:
        try:
            r = subprocess.run([sys.executable, up, "--selftest"], capture_output=True,
                               text=True, timeout=90, cwd=repo)
            if r.returncode == 0 and "selftest OK" in r.stdout:
                ok("update_data.py --selftest 通過")
            else:
                bad(f"update_data.py --selftest 失敗：{(r.stderr or r.stdout).strip()[-300:]}")
        except Exception as ex:
            warn(f"無法執行 selftest：{ex}")

    idx = os.path.join(repo, "index.html")
    if not os.path.isfile(idx):
        bad("找不到 index.html")
        return
    html = open(idx, encoding="utf-8").read()
    if 'fetch("data.json"' in html or "fetch('data.json'" in html:
        ok("index.html 採 fetch-first 讀取 data.json")
    else:
        bad("index.html 沒有 fetch data.json 的邏輯（會永遠顯示內嵌快照）")
    for fn in ("renderQuad", "renderTriggers", "renderTwV2"):
        if fn not in html:
            bad(f"index.html 缺 v2 render 函式 {fn}")

    check_fallback(html, d)
    check_spreads_keys(repo, html, d)

    # JS 語法
    blocks = re.findall(r"<script(?![^>]*application/json)[^>]*>(.*?)</script>", html, re.S)
    js = "\n".join(blocks)
    if not js.strip():
        warn("index.html 找不到可檢查的 <script> 區塊")
        return
    tmp = os.path.join("/tmp", "_bubble_check.js")
    open(tmp, "w", encoding="utf-8").write(js)
    try:
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            ok("index.html 的 JS 語法正常（node --check）")
        else:
            bad(f"index.html JS 語法錯誤：{r.stderr.strip()[:300]}")
    except FileNotFoundError:
        warn("環境無 node，略過 JS 語法檢查")
    except Exception as ex:
        warn(f"JS 語法檢查未完成：{ex}")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    mt = os.path.join(repo, "MAINTENANCE.md")
    ok("MAINTENANCE.md 存在") if os.path.isfile(mt) else bad("找不到 MAINTENANCE.md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    a = ap.parse_args()
    repo = find_repo(a.repo)
    if not repo:
        print("FAIL 找不到 ai-bubble-monitor（用 --repo 指定路徑）")
        sys.exit(2)
    print(f"repo: {repo}\n" + "-" * 60)
    d = check_data(repo)
    print("-" * 60)
    check_brief(repo, d)
    print("-" * 60)
    check_code(repo, d)
    print("-" * 60)
    print(f"總計  PASS {R['pass']}　WARN {R['warn']}　FAIL {R['fail']}")
    sys.exit(1 if R["fail"] else 0)


if __name__ == "__main__":
    main()
